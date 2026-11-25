# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
The sync engine: one user or user group mirrored into its person or person group

**It writes as the system.** The objects are written through the objects manager without a user, so no Type ACL of
the acting user judges them, and past the lock that keeps clients off the synced values - the sync is the one writer
those values have. The acting user is credited: the author of a created person, the editor of an edit, the user its
change log and webhook name.

**Every write is recorded in the caller's ledger**, so the caller decides what is undone together - the user write
and its sync, say. Nothing is written while the user sync is off: the reconciliation pass that switches it on again
catches up. **The change logs and webhooks follow afterwards**, once the caller's writes all stood: the result names
what was created and edited, ``emit_sync_events`` hands them to the route layer's callbacks, best-effort.

  - ``sync_user``: creates the user's person in its target Type, or brings its values and active state up to date -
    no write when its fingerprint is unchanged; then, while the group sync is on, the mapped person groups of the
    user's user groups and of the groups the person is still in
  - ``sync_user_deleted``: the person is deactivated and unlinked - a former user, editable, still referenced - and
    leaves every mapped person group, whatever the group sync's switch: unlinked, it would stay there as a member
    added by hand
  - ``sync_user_group``: the mapped person group's name and synced members, while both syncs are on
  - ``sync_user_group_deleted``: the person group is unmapped - members kept, unlocked

A person whose Type is not the user's target any more is updated where it is: moving it is the target change's
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Callable

from cmdb.manager import GroupsManager, ObjectsManager, SettingsManager, TypesManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import (
    OBJECT_SYNC_KEYS,
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectSyncKey,
    SystemRefKind,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey

from cmdb.framework.object_edit import (
    ObjectWriteCallback,
    PlannedEdit,
    build_edit_stamp,
    hand_over_object_writes,
    plan_object_edit,
)
from cmdb.framework.object_field_value_rules import build_field_value_rules
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.person_memberships import group_members, holding_members_criteria
from cmdb.framework.person_sync.person_sync_constants import ID_PATH, KIND_PATH
from cmdb.framework.person_sync.sync_documents import (
    build_person_document,
    build_person_group_document,
    former_person,
    group_after_sync,
    group_sync_change,
    group_without_members,
    linked_record_id,
    person_after_sync,
)
from cmdb.framework.person_sync.sync_mapping import (
    SyncedPerson,
    person_group_name,
    synced_member_ids,
    synced_person_from_user,
)
from cmdb.framework.person_sync.sync_reads import synced_person_ids
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings, drop_type_override
from cmdb.framework.person_sync.sync_settings_rules import usable_person_group_type, usable_target_type
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SyncContext',
    'SyncResult',
    'SyncEvents',
    'sync_user',
    'sync_users',
    'sync_user_deleted',
    'sync_user_group',
    'sync_user_group_deleted',
    'emit_sync_events',
    'plan_edit_write',
    'linked_object',
    'insert_linked_object',
    'write_edit',
    'left_synced_members',
    'record_left_members',
]

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class SyncContext:
    """
    What one sync call works with

    Attributes:
        objects_manager (ObjectsManager): Reads and writes the persons and person groups
        types_manager (TypesManager): Reads their Types
        users_manager (UsersManager): Reads a user group's members
        groups_manager (GroupsManager): Reads the user groups
        settings (PersonSyncSettings): The stored sync settings
        acting_user (CmdbUser): The user credited with the writes
        settings_manager (SettingsManager | None): Writes the settings where a sync changes them - a deleted user's
            Type override goes; None where nothing may change them
    """
    objects_manager: ObjectsManager
    types_manager: TypesManager
    users_manager: UsersManager
    groups_manager: GroupsManager
    settings: PersonSyncSettings
    acting_user: CmdbUser
    settings_manager: SettingsManager | None = None


@dataclass
class SyncResult:
    """
    What a sync call wrote, for the change logs, webhooks and ConfigItem report that follow

    Attributes:
        created (list[int]): The persons created
        edits (dict[int, PlannedEdit]): The persons and person groups edited, by public_id
        config_items_changed (bool): Whether a link was added to or removed from an object that was already stored -
            a linked object is no ConfigItem (``config_item_criteria``), so the ConfigItem count moved. An object the
            sync creates linked never was one, so a create alone leaves it False
        left_members (dict[int, list[int]]): mapped person group -> the synced persons the sync took out of it because
            its user group does not hold them (any longer) - also ones added by hand; the routes report them
    """
    created: list[int] = field(default_factory=list)
    edits: dict[int, PlannedEdit] = field(default_factory=dict)
    config_items_changed: bool = False
    left_members: dict[int, list[int]] = field(default_factory=dict)


    def merge(self, other: "SyncResult") -> None:
        """
        Adds another call's writes to this one - an object edited twice keeps its first state as its before

        Args:
            other (SyncResult): The other call's writes
        """
        self.created.extend(other.created)
        self.config_items_changed = self.config_items_changed or other.config_items_changed

        for group_id, person_ids in other.left_members.items():
            self.left_members[group_id] = sorted(set(self.left_members.get(group_id, [])) | set(person_ids))

        for public_id, plan in other.edits.items():
            first: PlannedEdit | None = self.edits.get(public_id)
            self.edits[public_id] = plan if first is None else PlannedEdit(first.before, plan.version, plan.changes)


@dataclass(frozen=True)
class SyncEvents:
    """
    The route layer's callbacks for what the sync wrote

    Attributes:
        on_create (Callable[[CmdbObject], None]): Receives each created person - its CREATE log and webhook
        on_edit (ObjectWriteCallback): Receives each edit - its EDIT / ACTIVE_CHANGE log and UPDATE webhook
        on_config_items_changed (Callable[[], None]): Called once when the writes moved the ConfigItem count - the
            report to the service portal
    """
    on_create: Callable[[CmdbObject], None]
    on_edit: ObjectWriteCallback
    on_config_items_changed: Callable[[], None]

# ------------------------------------------------------- reads ------------------------------------------------------ #

def linked_object(objects_manager: ObjectsManager, kind: SystemRefKind, record_id: int) -> dict[str, Any] | None:
    """
    Reads the object mirroring a user-management record

    Args:
        objects_manager (ObjectsManager): Reads the object
        kind (SystemRefKind): User or user group
        record_id (int): The record's public_id

    Returns:
        dict[str, Any] | None: The object, None when the record is mirrored nowhere
    """
    found: list[dict[str, Any]] = objects_manager.find(criteria={KIND_PATH: kind.value, ID_PATH: record_id})

    return found[0] if found else None


def _usable_type(context: SyncContext, type_id: int | None) -> CmdbType:
    """
    Reads a Type the sync writes a person into, refusing one it cannot write into (``usable_target_type``)

    Args:
        context (SyncContext): The managers
        type_id (int | None): The Type's id; None when no target is chosen

    Raises:
        PersonSyncTargetError: When no Type is chosen, it is gone or it is no longer usable

    Returns:
        CmdbType: The Type
    """
    return usable_target_type(
        type_id, context.types_manager.get_type_instance(type_id) if type_id is not None else None,
    )

# ------------------------------------------------------ writes ------------------------------------------------------ #

def plan_edit_write(acting_user: CmdbUser, stored: dict[str, Any], after: dict[str, Any],
                    unset: tuple[str, ...] = ()) -> tuple[PlannedEdit, dict[str, Any]]:
    """
    Plans the write of an edit: what it records and the update document - fields, active state, fingerprint, version
    and edit stamp

    Args:
        acting_user (CmdbUser): The user credited as the editor
        stored (dict[str, Any]): The object as stored
        after (dict[str, Any]): The object as the sync leaves it
        unset (tuple[str, ...]): Top-level keys the edit removes

    Returns:
        tuple[PlannedEdit, dict[str, Any]]: The before, version and diff; the update document of operators
    """
    plan: PlannedEdit = plan_object_edit(stored, after)
    to_set: dict[str, Any] = {
        CmdbObjectKey.FIELDS.value: after[CmdbObjectKey.FIELDS.value],
        CmdbObjectKey.ACTIVE.value: after[CmdbObjectKey.ACTIVE.value],
        CmdbObjectKey.VERSION.value: plan.version,
        **build_edit_stamp(acting_user),
    }

    if CmdbObjectSyncKey.SYNC_HASH.value in after:
        to_set[CmdbObjectSyncKey.SYNC_HASH.value] = after[CmdbObjectSyncKey.SYNC_HASH.value]

    operations: dict[str, Any] = {'$set': to_set}

    if unset:
        operations['$unset'] = {key: '' for key in unset}

    return plan, operations


def write_edit(context: SyncContext, ledger: WriteLedger, stored: dict[str, Any], after: dict[str, Any],
               unset: tuple[str, ...] = ()) -> PlannedEdit:
    """
    Writes an edit of a stored object (``plan_edit_write``) and records it in the ledger

    Args:
        context (SyncContext): The managers and the acting user
        ledger (WriteLedger): Records the write
        stored (dict[str, Any]): The object as stored
        after (dict[str, Any]): The object as the sync leaves it
        unset (tuple[str, ...]): Top-level keys the edit removes

    Returns:
        PlannedEdit: What the edit records - the before, the version, the diff
    """
    plan, operations = plan_edit_write(context.acting_user, stored, after, unset)
    public_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]
    ledger.updated(context.objects_manager, public_id, stored)
    context.objects_manager.update({CmdbObjectKey.PUBLIC_ID.value: public_id}, operations)

    return plan


def insert_linked_object(context: SyncContext, ledger: WriteLedger, build: Callable[[int], dict[str, Any]]) -> int:
    """
    Inserts an object the sync creates under a new id from the object counter, recorded in the ledger

    Args:
        context (SyncContext): The objects manager
        ledger (WriteLedger): Records the insert
        build (Callable[[int], dict[str, Any]]): Builds the object for its new id

    Returns:
        int: The object's public_id
    """
    public_id: int = context.objects_manager.get_new_object_public_id()
    context.objects_manager.insert(build(public_id), id_from_counter=True)
    ledger.inserted(context.objects_manager, public_id)

    return public_id


def create_person_group(context: SyncContext, ledger: WriteLedger, user_group: CmdbUserGroup,
                        type_instance: CmdbType) -> int:
    """
    Creates the person group mirroring a user group, named after it and without members

    Args:
        context (SyncContext): The managers and the acting user
        ledger (WriteLedger): Records the insert
        user_group (CmdbUserGroup): The user group
        type_instance (CmdbType): The judged Type carrying PERSON_GROUP

    Returns:
        int: The person group's public_id
    """
    return insert_linked_object(context, ledger, lambda public_id: build_person_group_document(
        public_id, type_instance, user_group.public_id, person_group_name(user_group),
        context.acting_user.public_id, datetime.now(timezone.utc),
    ))


def usable_group_type(context: SyncContext) -> CmdbType:
    """
    Reads the group sync's default Type, refusing one the sync cannot create person groups in

    Args:
        context (SyncContext): The managers and the settings

    Raises:
        PersonSyncTargetError: When no default is chosen, it is gone or it is no longer usable

    Returns:
        CmdbType: The Type
    """
    type_id: int | None = context.settings.groups.default_type_id

    return usable_person_group_type(
        type_id, context.types_manager.get_type_instance(type_id) if type_id is not None else None,
    )


def _create_person(context: SyncContext, ledger: WriteLedger, user: CmdbUser) -> int:
    """
    Creates a user's person in its target Type - the user's override, else the default

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records the insert
        user (CmdbUser): The user

    Raises:
        PersonSyncTargetError: When the target Type is gone or unusable

    Returns:
        int: The person's public_id
    """
    users_settings: UserSyncSettings = context.settings.users
    type_instance: CmdbType = _usable_type(
        context, users_settings.type_overrides.get(user.public_id, users_settings.default_type_id),
    )
    synced: SyncedPerson = synced_person_from_user(user, build_field_value_rules(type_instance.get_fields()))

    return insert_linked_object(context, ledger, lambda public_id: build_person_document(
        public_id, type_instance, user.public_id, synced, context.acting_user.public_id, datetime.now(timezone.utc),
    ))


def _update_person(context: SyncContext, ledger: WriteLedger, stored: dict[str, Any],
                   user: CmdbUser) -> PlannedEdit | None:
    """
    Brings a user's person up to date in the Type it lives in - nothing is written when its fingerprint is unchanged

    Args:
        context (SyncContext): The managers and the acting user
        ledger (WriteLedger): Records the write
        stored (dict[str, Any]): The person as stored
        user (CmdbUser): Its user

    Raises:
        PersonSyncTargetError: When the person's Type is gone or unusable

    Returns:
        PlannedEdit | None: The edit, None when nothing changed
    """
    type_instance: CmdbType = _usable_type(context, stored.get(CmdbObjectKey.TYPE_ID.value))
    synced: SyncedPerson = synced_person_from_user(user, build_field_value_rules(type_instance.get_fields()))

    if stored.get(CmdbObjectSyncKey.SYNC_HASH.value) == synced.fingerprint():
        return None

    return write_edit(context, ledger, stored, person_after_sync(stored, type_instance, synced))


def _member_users(context: SyncContext, user_group_ids: list[int]) -> dict[int, list[int]]:
    """
    Reads the users of the given user groups, with their group ids - one projected read

    Args:
        context (SyncContext): The users manager
        user_group_ids (list[int]): The user groups

    Returns:
        dict[int, list[int]]: user id -> the user's group ids
    """
    users: list[dict[str, Any]] = context.users_manager.find(
        criteria={CmdbUserKey.GROUP_IDS.value: {'$in': user_group_ids}},
        projection={CmdbUserKey.PUBLIC_ID.value: 1, CmdbUserKey.GROUP_IDS.value: 1},
    )

    return {user[CmdbUserKey.PUBLIC_ID.value]: list(user.get(CmdbUserKey.GROUP_IDS.value) or []) for user in users}


def _persons_by_user(context: SyncContext, user_ids: list[int]) -> dict[int, int]:
    """
    Reads the persons of the given users - one projected read on the link index

    Args:
        context (SyncContext): The objects manager
        user_ids (list[int]): The users

    Returns:
        dict[int, int]: user id -> the id of the user's person; a user without one is no key
    """
    if not user_ids:
        return {}

    persons: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER.value, ID_PATH: {'$in': user_ids}},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.SYSTEM_REF.value: 1},
    )

    return {linked_record_id(person): person[CmdbObjectKey.PUBLIC_ID.value] for person in persons}


def _sync_groups(context: SyncContext, ledger: WriteLedger, criteria: dict[str, Any]) -> SyncResult:
    """
    Brings the mapped person groups matching the criteria in line with their user groups - their names and synced
    members (``group_sync_change``); nothing is written for a group already in line, or one whose Type is gone

    In batches, whatever the number of groups: one read each of the groups, their user groups, the users of those, the
    users' persons, the synced persons among the stored members and the groups' Types

    Args:
        context (SyncContext): The managers and the acting user
        ledger (WriteLedger): Records the writes
        criteria (dict[str, Any]): Selects mapped person groups

    Returns:
        SyncResult: The groups edited
    """
    result = SyncResult()
    stored_groups: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value, **criteria},
    )

    if not stored_groups:
        return result

    user_group_ids: list[int] = sorted({linked_record_id(document) for document in stored_groups})
    user_groups: dict[int, CmdbUserGroup] = {
        group.public_id: group for group in context.groups_manager.get_groups(user_group_ids)
    }
    group_ids_by_user: dict[int, list[int]] = _member_users(context, user_group_ids)
    person_id_by_user: dict[int, int] = _persons_by_user(context, sorted(group_ids_by_user))
    synced_ids: set[int] = synced_person_ids(
        context.objects_manager, {member for stored in stored_groups for member in group_members(stored)},
    ) | set(person_id_by_user.values())
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({stored[CmdbObjectKey.TYPE_ID.value] for stored in stored_groups}))

    for stored in stored_groups:
        user_group: CmdbUserGroup | None = user_groups.get(linked_record_id(stored))

        if user_group is None:
            continue

        change: tuple[str, list[int]] | None = group_sync_change(
            stored, user_group, synced_ids,
            synced_member_ids(user_group.public_id, group_ids_by_user, person_id_by_user),
        )

        if change is not None and (type_instance := _known_type(stored, types)) is not None:
            result.edits[stored[CmdbObjectKey.PUBLIC_ID.value]] = write_edit(
                context, ledger, stored, group_after_sync(stored, type_instance, *change),
            )
            record_left_members(result, stored, change[1])

    return result


def left_synced_members(stored: dict[str, Any], members: list[int]) -> list[int]:
    """
    Returns the members a group sync takes out of a mapped person group - stored, but not among the new members

    Args:
        stored (dict[str, Any]): The stored person group
        members (list[int]): Its new members (``group_sync_change``)

    Returns:
        list[int]: The persons that leave, ascending
    """
    kept: set[int] = set(members)

    return sorted(member for member in group_members(stored) if member not in kept)


def record_left_members(result: SyncResult, stored: dict[str, Any], members: list[int]) -> None:
    """
    Adds the persons a group sync takes out of a mapped person group to the result, for the routes' report

    Args:
        result (SyncResult): Receives them under the group's id
        stored (dict[str, Any]): The stored person group
        members (list[int]): Its new members
    """
    if left := left_synced_members(stored, members):
        result.left_members[stored[CmdbObjectKey.PUBLIC_ID.value]] = left


def _known_type(stored: dict[str, Any], types: dict[int, CmdbType]) -> CmdbType | None:
    """
    Returns a mapped person group's Type from the read ones - a group whose Type is gone is skipped, logged, never
    failing the sync: its Type is no target the sync writes persons into

    Args:
        stored (dict[str, Any]): The person group
        types (dict[int, CmdbType]): The Types read

    Returns:
        CmdbType | None: The Type; None when it is gone
    """
    type_instance: CmdbType | None = types.get(stored[CmdbObjectKey.TYPE_ID.value])

    if type_instance is None:
        LOGGER.warning("[person sync] Person group %s skipped - its Type %s is gone",
                       stored[CmdbObjectKey.PUBLIC_ID.value], stored[CmdbObjectKey.TYPE_ID.value])

    return type_instance


# ---------------------------------------------------- the calls ----------------------------------------------------- #

def _clear_sync_pending(context: SyncContext, ledger: WriteLedger, users: list[CmdbUser]) -> None:
    """
    Removes the users' ``sync_pending`` marks once their sync succeeded - recorded, so an undo puts the marks back

    Reads nothing when no user carries the mark; else one read of the marked users still stored with it (the ledger's
    snapshots) and one write for all of them

    Args:
        context (SyncContext): The users manager
        ledger (WriteLedger): Records the update
        users (list[CmdbUser]): The users as stored after their own writes
    """
    marked: list[int] = sorted({user.public_id for user in users if user.sync_pending})

    if not marked:
        return

    stored: list[dict[str, Any]] = context.users_manager.find(criteria={
        CmdbUserKey.PUBLIC_ID.value: {'$in': marked}, CmdbUserKey.SYNC_PENDING.value: {'$exists': True},
    })

    if not stored:
        return

    for document in stored:
        ledger.updated(context.users_manager, document[CmdbUserKey.PUBLIC_ID.value], document)

    context.users_manager.update_many_raw(
        {CmdbUserKey.PUBLIC_ID.value: {'$in': [document[CmdbUserKey.PUBLIC_ID.value] for document in stored]}},
        {'$unset': {CmdbUserKey.SYNC_PENDING.value: ''}},
    )


def _sync_person(context: SyncContext, ledger: WriteLedger, user: CmdbUser, result: SyncResult) -> int:
    """
    Mirrors one user into its person - created, or brought up to date - adding the write to the result

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records the write
        user (CmdbUser): The user as stored after its own write
        result (SyncResult): Receives the create or the edit

    Raises:
        PersonSyncTargetError: When the person's Type is gone or unusable

    Returns:
        int: The person's public_id
    """
    stored: dict[str, Any] | None = linked_object(context.objects_manager, SystemRefKind.USER, user.public_id)

    if stored is None:
        person_id: int = _create_person(context, ledger, user)
        result.created.append(person_id)

        return person_id

    person_id = stored[CmdbObjectKey.PUBLIC_ID.value]

    if plan := _update_person(context, ledger, stored, user):
        result.edits[person_id] = plan

    return person_id


def sync_users(context: SyncContext, ledger: WriteLedger, users: list[CmdbUser]) -> SyncResult:
    """
    Mirrors users into their persons, then - while the group sync is on - every mapped person group of their user
    groups and of the groups their persons are still in, each once; and removes the users' ``sync_pending`` marks,
    which this sync settles

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write - the caller undoes them together with its own
        users (list[CmdbUser]): The users as stored after their own writes

    Raises:
        PersonSyncTargetError: When a person's Type is gone or unusable
        ObjectsManager / TypesManager / UsersManager / GroupsManager errors: When a read or write fails

    Returns:
        SyncResult: What was created and edited; empty while the user sync is off
    """
    result = SyncResult()

    if not context.settings.users.active or not users:
        return result

    person_ids: list[int] = [_sync_person(context, ledger, user, result) for user in users]

    if context.settings.groups.active:
        result.merge(_sync_groups(context, ledger, {'$or': [
            {ID_PATH: {'$in': sorted({group_id for user in users for group_id in user.group_ids})}},
            holding_members_criteria(person_ids),
        ]}))

    _clear_sync_pending(context, ledger, users)

    return result


def sync_user(context: SyncContext, ledger: WriteLedger, user: CmdbUser) -> SyncResult:
    """
    Mirrors one user into its person, and its memberships into the mapped person groups (``sync_users``)

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write - the caller undoes them together with its own
        user (CmdbUser): The user as stored after its own write

    Raises:
        PersonSyncTargetError: When the person's Type is gone or unusable
        ObjectsManager / TypesManager / UsersManager / GroupsManager errors: When a read or write fails

    Returns:
        SyncResult: What was created and edited; empty while the user sync is off
    """
    return sync_users(context, ledger, [user])


def sync_user_deleted(context: SyncContext, ledger: WriteLedger, user_id: int) -> SyncResult:
    """
    Turns a deleted user's person into a former user: deactivated, unlinked, out of every mapped person group -
    whatever the switches: with the user gone there is nothing left to mirror, and a person kept linked would stay
    locked and undeletable until the sync is switched on again. The user's Type override goes from the settings too
    (``drop_type_override``), given a settings manager

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write
        user_id (int): The deleted user

    Returns:
        SyncResult: What was edited; empty when the user had no person
    """
    result = SyncResult()

    if context.settings_manager is not None:
        drop_type_override(context.settings_manager, ledger, user_id)

    stored: dict[str, Any] | None = linked_object(context.objects_manager, SystemRefKind.USER, user_id)

    if stored is None:
        return result

    person_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]

    groups: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value, **holding_members_criteria([person_id])})
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({group[CmdbObjectKey.TYPE_ID.value] for group in groups})) if groups else {}

    for group in groups:
        if (type_instance := _known_type(group, types)) is not None:
            result.edits[group[CmdbObjectKey.PUBLIC_ID.value]] = write_edit(
                context, ledger, group, group_without_members(group, type_instance, {person_id}),
            )

    result.edits[person_id] = write_edit(context, ledger, stored, former_person(stored), unset=OBJECT_SYNC_KEYS)
    result.config_items_changed = True

    return result


def sync_user_group(context: SyncContext, ledger: WriteLedger, user_group: CmdbUserGroup) -> SyncResult:
    """
    Brings a user group's person group in line: one is created in the default Type when the user group has none, then
    its name and synced members follow

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write
        user_group (CmdbUserGroup): The user group as stored after its own write

    Raises:
        PersonSyncTargetError: When a person group is to be created and the default Type is unusable - nothing written

    Returns:
        SyncResult: What was created and edited; empty while either sync is off
    """
    if not (context.settings.users.active and context.settings.groups.active):
        return SyncResult()

    result = SyncResult()

    if linked_object(context.objects_manager, SystemRefKind.USER_GROUP, user_group.public_id) is None:
        result.created.append(create_person_group(context, ledger, user_group, usable_group_type(context)))

    result.merge(_sync_groups(context, ledger, {ID_PATH: user_group.public_id}))

    return result


def sync_user_group_deleted(context: SyncContext, ledger: WriteLedger, user_group_id: int) -> SyncResult:
    """
    Unmaps a user group's person group - the user group deleted or unmapped; its members kept, the group unlocked,
    whatever the switches

    No field changes, so nothing is logged

    Args:
        context (SyncContext): The managers
        ledger (WriteLedger): Records the write
        user_group_id (int): The user group

    Returns:
        SyncResult: No edits; the ConfigItem count moved when a person group was unmapped
    """
    stored: dict[str, Any] | None = linked_object(context.objects_manager, SystemRefKind.USER_GROUP, user_group_id)

    if stored is None:
        return SyncResult()

    public_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]
    ledger.updated(context.objects_manager, public_id, stored)
    context.objects_manager.update({CmdbObjectKey.PUBLIC_ID.value: public_id},
                                   {'$unset': {CmdbObjectKey.SYSTEM_REF.value: ''}})

    return SyncResult(config_items_changed=True)


def emit_sync_events(objects_manager: ObjectsManager, result: SyncResult, events: SyncEvents | None) -> None:
    """
    Hands what the sync wrote to the route layer's change logs and webhooks, then reports a moved ConfigItem count
    once - after the writes stood, best-effort

    Args:
        objects_manager (ObjectsManager): Reads the written objects back
        result (SyncResult): What was created and edited, and whether the ConfigItem count moved
        events (SyncEvents | None): The callbacks; None emits nothing
    """
    if events is None:
        return

    if result.created:
        try:
            created: list[dict[str, Any]] = objects_manager.find_objects(
                {CmdbObjectKey.PUBLIC_ID.value: {'$in': result.created}}, as_dict=True,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            LOGGER.error("[emit_sync_events] The created persons %s could not be read back", result.created,
                         exc_info=True)
            created = []

        for document in created:
            events.on_create(CmdbObject.from_data(document))

    hand_over_object_writes(objects_manager, result.edits, events.on_edit)

    if result.config_items_changed:
        events.on_config_items_changed()
