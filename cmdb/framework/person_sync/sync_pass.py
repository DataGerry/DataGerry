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
The reconciliation pass: every user and user group mirrored at once - switching the sync on, back on, or a resync

**In batches, not user by user.** One read each of the users, the linked persons, the Types they need and the user
groups; one reservation of ids for the persons to create; one bulk write of the persons, one of the mapped person
groups. Every target Type is judged before anything is written.

  - A user with a person: written only when its fingerprint changed - an unchanged person costs nothing
  - A user without one: a new person in its target Type - always a new one, never an existing person matched by name
    or email
  - A person whose user is gone: a former user - deactivated, unlinked, and out of every mapped person group, whatever
    the group sync's switch
  - With the group sync on, every mapped person group: its name and synced members; one whose user group is gone is
    unmapped
  - Every ``sync_pending`` mark goes: the pass has caught its user up

**Switching the user sync off** (``switch_off_pass``) deactivates every synced person and removes its fingerprint,
keeping the link: the persons stay locked, and the pass that switches the sync on again rewrites every one of them.

**Re-run safe, so not undone.** A pass touches every person; instead of a ledger of thousands of snapshots it relies on
running again: a person written already carries its new fingerprint and is skipped, a person created already is found
by its link (the unique index refuses a second one), a former user is linked no more. The result names what was
created and edited, for the change logs and webhooks (``emit_sync_events``)
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Callable

from pymongo import InsertOne, UpdateOne

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import (
    OBJECT_SYNC_KEYS,
    CmdbObjectKey,
    CmdbObjectSyncKey,
    SystemRefKind,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey

from cmdb.framework.object_field_value_rules import build_field_value_rules
from cmdb.framework.person_types.person_memberships import group_members, holding_members_criteria
from cmdb.framework.person_sync.person_sync_constants import KIND_PATH
from cmdb.framework.person_sync.sync_documents import (
    build_person_document,
    former_person,
    group_after_sync,
    group_sync_change,
    group_without_members,
    linked_record_id,
    person_after_sync,
)
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult, plan_edit_write, record_left_members
from cmdb.framework.person_sync.sync_mapping import (
    SyncedPerson,
    synced_member_ids,
    synced_person_from_user,
)
from cmdb.framework.person_sync.sync_settings_rules import usable_target_type

from cmdb.manager.users_manager_constants import WITHOUT_PASSWORD_PROJECTION
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'run_sync_pass',
    'switch_off_pass',
]

LOGGER: Logger = getLogger(__name__)


@dataclass
class _PersonPlan:
    """
    The writes the pass plans for the persons

    Attributes:
        operations (list[Any]): The inserts and updates
        result (SyncResult): What they create and edit
        person_id_by_user (dict[int, int]): user id -> its person, after the writes
        former_ids (set[int]): The persons whose user is gone
    """
    operations: list[Any]
    result: SyncResult
    person_id_by_user: dict[int, int]
    former_ids: set[int]


def _read_users(context: SyncContext) -> dict[int, CmdbUser]:
    """
    Reads every user, without the password digest

    Args:
        context (SyncContext): The managers

    Returns:
        dict[int, CmdbUser]: The users by public_id
    """
    users: list[dict[str, Any]] = context.users_manager.find(criteria={}, projection=WITHOUT_PASSWORD_PROJECTION)

    return {user.public_id: user for user in (CmdbUser.from_data(document) for document in users)}


def _checked_types(context: SyncContext, users: dict[int, CmdbUser],
                   persons: dict[int, dict[str, Any]]) -> dict[int, CmdbType]:
    """
    Reads and judges the Type every user's person is written into - its person's Type, else its target - in one read

    Args:
        context (SyncContext): The managers and the settings
        users (dict[int, CmdbUser]): Every user by id
        persons (dict[int, dict[str, Any]]): Every linked person by its user's id

    Raises:
        PersonSyncTargetError: When one of them is gone or unusable

    Returns:
        dict[int, CmdbType]: user id -> the Type its person is written into
    """
    overrides: dict[int, int] = context.settings.users.type_overrides
    type_of: dict[int, int | None] = {
        user_id: persons[user_id][CmdbObjectKey.TYPE_ID.value] if user_id in persons
        else overrides.get(user_id, context.settings.users.default_type_id)
        for user_id in users
    }
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({type_id for type_id in type_of.values() if type_id is not None}))

    return {user_id: usable_target_type(type_id, types.get(type_id) if type_id is not None else None)
            for user_id, type_id in type_of.items()}


def _plan_user(context: SyncContext, plan: _PersonPlan, user: CmdbUser, type_instance: CmdbType,
               stored: dict[str, Any] | None, new_ids: list[int]) -> None:
    """
    Plans one user's person: created with the next reserved id, or edited when its fingerprint changed

    Args:
        context (SyncContext): The acting user
        plan (_PersonPlan): The plan to add to
        user (CmdbUser): The user
        type_instance (CmdbType): The Type its person is written into
        stored (dict[str, Any] | None): Its person, None when it has none
        new_ids (list[int]): The reserved ids not handed out yet - the next one is taken for a new person
    """
    synced: SyncedPerson = synced_person_from_user(user, build_field_value_rules(type_instance.get_fields()))

    if stored is None:
        public_id: int = new_ids.pop(0)
        plan.operations.append(InsertOne(build_person_document(
            public_id, type_instance, user.public_id, synced, context.acting_user.public_id,
            datetime.now(timezone.utc))))
        plan.result.created.append(public_id)
        plan.person_id_by_user[user.public_id] = public_id
        return

    plan.person_id_by_user[user.public_id] = stored[CmdbObjectKey.PUBLIC_ID.value]

    if stored.get(CmdbObjectSyncKey.SYNC_HASH.value) != synced.fingerprint():
        _plan_edit(context, plan, stored, person_after_sync(stored, type_instance, synced))


def _plan_former(context: SyncContext, plan: _PersonPlan, stored: dict[str, Any]) -> None:
    """
    Plans a person whose user is gone: deactivated and unlinked, its values kept

    Args:
        context (SyncContext): The acting user
        plan (_PersonPlan): The plan to add to
        stored (dict[str, Any]): The person
    """
    plan.former_ids.add(stored[CmdbObjectKey.PUBLIC_ID.value])
    _plan_edit(context, plan, stored, former_person(stored), OBJECT_SYNC_KEYS)
    plan.result.config_items_changed = True


def _plan_persons(context: SyncContext, users: dict[int, CmdbUser], persons: dict[int, dict[str, Any]]) -> _PersonPlan:
    """
    Plans every person write: the changed persons updated, the missing ones created, the former users unlinked

    Every Type a person is written into is judged before an id is reserved or an operation planned

    Args:
        context (SyncContext): The managers, the settings and the acting user
        users (dict[int, CmdbUser]): Every user by id
        persons (dict[int, dict[str, Any]]): Every linked person by its user's id

    Raises:
        PersonSyncTargetError: When a Type a person is written into is gone or unusable

    Returns:
        _PersonPlan: The operations, what they create and edit, and the persons by user
    """
    types: dict[int, CmdbType] = _checked_types(context, users, persons)
    missing: int = sum(1 for user_id in users if user_id not in persons)
    new_ids: list[int] = context.objects_manager.reserve_public_ids(missing) if missing else []
    plan = _PersonPlan([], SyncResult(), {}, set())

    for user_id, user in users.items():
        _plan_user(context, plan, user, types[user_id], persons.get(user_id), new_ids)

    for user_id, stored in persons.items():
        if user_id not in users:
            _plan_former(context, plan, stored)

    return plan


def _plan_edit(context: SyncContext, plan: _PersonPlan, stored: dict[str, Any], after: dict[str, Any],
               unset: tuple[str, ...] = ()) -> None:
    """
    Adds one edit to a plan: its update operation and what it records

    Args:
        context (SyncContext): The acting user
        plan (_PersonPlan): The plan to add to
        stored (dict[str, Any]): The object as stored
        after (dict[str, Any]): The object as the pass leaves it
        unset (tuple[str, ...]): Top-level keys the edit removes
    """
    public_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]
    edit, operations = plan_edit_write(context.acting_user, stored, after, unset)
    plan.operations.append(UpdateOne({CmdbObjectKey.PUBLIC_ID.value: public_id}, operations))
    plan.result.edits[public_id] = edit


def _plan_group(context: SyncContext, plan: _PersonPlan, stored: dict[str, Any], user_group: CmdbUserGroup | None,
                type_instance: CmdbType | None, members_of: Callable[[int], list[int]], synced_ids: set[int]) -> None:
    """
    Plans one mapped person group: unmapped when its user group is gone, else its name and synced members

    Args:
        context (SyncContext): The acting user
        plan (_PersonPlan): The plan to add to
        stored (dict[str, Any]): The person group
        user_group (CmdbUserGroup | None): Its user group, None when gone
        type_instance (CmdbType | None): Its Type
        members_of (Callable[[int], list[int]]): A user group's id -> the persons of its users
        synced_ids (set[int]): Every synced person and former user - the members the sync decides about
    """
    public_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]

    if user_group is None:
        plan.operations.append(UpdateOne({CmdbObjectKey.PUBLIC_ID.value: public_id},
                                         {'$unset': {CmdbObjectKey.SYSTEM_REF.value: ''}}))
        plan.result.config_items_changed = True
        return

    change: tuple[str, list[int]] | None = group_sync_change(stored, user_group, synced_ids,
                                                             members_of(user_group.public_id))

    if change is None:
        return

    if type_instance is None:
        LOGGER.warning("[person sync] Person group %s skipped - its Type %s is gone", public_id,
                       stored[CmdbObjectKey.TYPE_ID.value])
        return

    _plan_edit(context, plan, stored, group_after_sync(stored, type_instance, *change))
    record_left_members(plan.result, stored, change[1])


def _plan_groups(context: SyncContext, users: dict[int, CmdbUser], person_plan: _PersonPlan) -> _PersonPlan:
    """
    Plans every mapped person group: its name and synced members, or its unmapping when its user group is gone

    Args:
        context (SyncContext): The managers and the acting user
        users (dict[int, CmdbUser]): Every user by id
        person_plan (_PersonPlan): The persons as the pass leaves them

    Returns:
        _PersonPlan: The group operations and edits (its persons maps unused)
    """
    plan = _PersonPlan([], SyncResult(), {}, set())
    stored_groups: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value})

    if not stored_groups:
        return plan

    user_groups: dict[int, CmdbUserGroup] = {
        group.public_id: group
        for group in context.groups_manager.get_groups(sorted({linked_record_id(stored) for stored in stored_groups}))
    }
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({stored[CmdbObjectKey.TYPE_ID.value] for stored in stored_groups}))
    group_ids_by_user: dict[int, list[int]] = {user_id: list(user.group_ids) for user_id, user in users.items()}

    def members_of(user_group_id: int) -> list[int]:
        return synced_member_ids(user_group_id, group_ids_by_user, person_plan.person_id_by_user)

    for stored in stored_groups:
        _plan_group(context, plan, stored, user_groups.get(linked_record_id(stored)),
                    types.get(stored[CmdbObjectKey.TYPE_ID.value]), members_of,
                    set(person_plan.person_id_by_user.values()) | person_plan.former_ids)

    return plan


def _plan_former_exits(context: SyncContext, former_ids: set[int]) -> _PersonPlan:
    """
    Plans the former users' persons out of every mapped person group - while the group sync is off, when nothing else
    writes the groups; their names and other members kept. Reported (``left``) and logged as the group sync does

    Args:
        context (SyncContext): The managers and the acting user
        former_ids (set[int]): The persons whose user is gone

    Returns:
        _PersonPlan: The group operations and edits (its persons maps unused)
    """
    plan = _PersonPlan([], SyncResult(), {}, set())

    if not former_ids:
        return plan

    stored_groups: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value, **holding_members_criteria(sorted(former_ids))})
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({stored[CmdbObjectKey.TYPE_ID.value] for stored in stored_groups})) if stored_groups else {}

    for stored in stored_groups:
        type_instance: CmdbType | None = types.get(stored[CmdbObjectKey.TYPE_ID.value])

        if type_instance is None:
            LOGGER.warning("[person sync] Person group %s skipped - its Type %s is gone",
                           stored[CmdbObjectKey.PUBLIC_ID.value], stored[CmdbObjectKey.TYPE_ID.value])
            continue

        after: dict[str, Any] = group_without_members(stored, type_instance, former_ids)
        _plan_edit(context, plan, stored, after)
        record_left_members(plan.result, stored, group_members(after))

    return plan


def run_sync_pass(context: SyncContext) -> SyncResult:
    """
    Brings every person, and with the group sync on every mapped person group, in line with user management

    Args:
        context (SyncContext): The managers, the settings and the acting user (credited with every write)

    Raises:
        PersonSyncTargetError: When a Type a person is written into is gone or unusable - before anything is written
        Manager errors: When a read or write fails - a second pass finishes what this one left

    Returns:
        SyncResult: What was created and edited; empty while the user sync is off
    """
    if not context.settings.users.active:
        return SyncResult()

    users: dict[int, CmdbUser] = _read_users(context)
    persons: dict[int, dict[str, Any]] = {
        linked_record_id(person): person
        for person in context.objects_manager.find(criteria={KIND_PATH: SystemRefKind.USER.value})
    }
    person_plan: _PersonPlan = _plan_persons(context, users, persons)

    if person_plan.operations:
        context.objects_manager.bulk_write(person_plan.operations)

    group_plan: _PersonPlan = (_plan_groups(context, users, person_plan) if context.settings.groups.active
                               else _plan_former_exits(context, person_plan.former_ids))

    if group_plan.operations:
        context.objects_manager.bulk_write(group_plan.operations)

    person_plan.result.merge(group_plan.result)

    context.users_manager.update_many_raw({CmdbUserKey.SYNC_PENDING.value: {'$exists': True}},
                                          {'$unset': {CmdbUserKey.SYNC_PENDING.value: ''}})

    return person_plan.result


def switch_off_pass(context: SyncContext) -> SyncResult:
    """
    Deactivates every synced person and removes its fingerprint - the link stays, and with it the lock

    The persons still active are edited (their ACTIVE_CHANGE logged); the ones deactivated already only lose the
    fingerprint, so the pass that switches the sync on again rewrites every person

    Args:
        context (SyncContext): The managers and the acting user

    Returns:
        SyncResult: The persons deactivated
    """
    plan = _PersonPlan([], SyncResult(), {}, set())

    for stored in context.objects_manager.find(criteria={KIND_PATH: SystemRefKind.USER.value,
                                                         CmdbObjectKey.ACTIVE.value: True}):
        after: dict[str, Any] = {key: value for key, value in stored.items()
                                 if key != CmdbObjectSyncKey.SYNC_HASH.value}
        after[CmdbObjectKey.ACTIVE.value] = False
        _plan_edit(context, plan, stored, after, (CmdbObjectSyncKey.SYNC_HASH.value,))

    if plan.operations:
        context.objects_manager.bulk_write(plan.operations)

    context.objects_manager.update_many_raw(
        {KIND_PATH: SystemRefKind.USER.value, CmdbObjectSyncKey.SYNC_HASH.value: {'$exists': True}},
        {'$unset': {CmdbObjectSyncKey.SYNC_HASH.value: ''}},
    )

    return plan.result
