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
What the person sync routes do: judge and store the settings, run the pass, map and unmap user groups, read a link

**Settings are judged whole before anything is written** - every problem in one 400: the rules of
``sync_settings_rules``, and a linked person keeps its Type, so no new target may place a user's person elsewhere.

**Switching on, a change while on and a resync run the reconciliation pass** on the new settings before they are
stored: a Type it cannot write into is a 400 with nothing written, and a pass that fails midway leaves the settings as
they were - running it again finishes it. **Switching the user sync off** stores the settings first (the hooks stop
syncing), then deactivates the persons; switching off again finishes a switch-off that failed. The pass's change logs
and webhooks follow, credited to the caller.

**A mapping is written with its sync on one ledger** (``write_with_person_sync``); the unique index decides a race
"""
from dataclasses import replace
from typing import Any, Callable

from flask import abort

from cmdb.manager import ObjectsManager, SettingsManager, UsersManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.person_sync_constants import PersonSyncKey, TypeOverrideKey
from cmdb.framework.person_sync.sync_engine import (
    SyncContext,
    SyncResult,
    emit_sync_events,
    linked_object,
)
from cmdb.framework.person_sync.sync_group_mapping import (
    existing_person_group_problems,
    map_user_group,
    read_group_mappings,
)
from cmdb.framework.person_sync.sync_pass import run_sync_pass, switch_off_pass
from cmdb.framework.person_sync.sync_settings import (
    GroupSyncSettings,
    PersonSyncSettings,
    UserSyncSettings,
    read_sync_settings,
    settings_to_document,
    switch_user_sync_off,
    write_sync_settings,
)
from cmdb.framework.person_sync.sync_relocation import RelocationStores, plan_relocations
from cmdb.framework.person_sync.sync_relocation_rules import PersonRelocation
from cmdb.framework.person_sync.sync_settings_rules import find_sync_settings_problems
from cmdb.interface.route_utils import abort_if_too_large
from cmdb.interface.rest_api.routes.routes_helper import abort_if_duplicate, abort_on_problems
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper import build_sync_events
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_hook_helper import (
    person_sync_context,
    write_with_person_sync,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_relocation_helper import (
    apply_relocations,
    refuse_blocked,
    relocation_stores,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_route_constants import (
    ON_BLOCKED_KEY,
    GroupMappingBodyKey,
    LeftMembersKey,
    PersonSyncAnswerKey,
    PersonSyncMessage,
    UserPersonKey,
)

from cmdb.errors.manager import BaseManagerInsertError, BaseManagerUpdateError
from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

# What mapping an existing person group needs on its Type - the sync rewrites its name and members
MAPPED_GROUP_PERMISSIONS: tuple[AccessControlPermission, ...] = (
    AccessControlPermission.READ, AccessControlPermission.UPDATE,
)

__all__: list[str] = [
    'user_sync_view',
    'group_sync_view',
    'pass_counts',
    'user_sync_from_body',
    'check_user_sync',
    'store_user_sync',
    'store_group_sync',
    'resync',
    'map_group',
    'read_settings',
    'read_mappings',
    'user_person_link',
]


SyncPass = Callable[[SyncContext], SyncResult]


def user_sync_view(settings: PersonSyncSettings) -> dict[str, Any]:
    """
    Answers the user sync's settings as they are stored

    Args:
        settings (PersonSyncSettings): The settings

    Returns:
        dict[str, Any]: ``active``, ``default_type_id`` and ``type_overrides``
    """
    return settings_to_document(settings)[PersonSyncKey.USERS.value]


def group_sync_view(settings: PersonSyncSettings, mappings: list[dict[str, int]]) -> dict[str, Any]:
    """
    Answers the user group sync's switch and every mapping

    Args:
        settings (PersonSyncSettings): The settings
        mappings (list[dict[str, int]]): The mappings (``sync_group_mapping.read_group_mappings``)

    Returns:
        dict[str, Any]: ``active`` and ``mappings``
    """
    return {PersonSyncKey.ACTIVE.value: settings.groups.active,
            PersonSyncKey.DEFAULT_TYPE_ID.value: settings.groups.default_type_id,
            PersonSyncAnswerKey.MAPPINGS.value: mappings}


def left_members_view(result: SyncResult) -> list[dict[str, Any]]:
    """
    Names the synced persons the sync took out of mapped person groups - also ones added by hand: in a mapped group,
    every synced person is the sync's

    Args:
        result (SyncResult): What the sync wrote

    Returns:
        list[dict[str, Any]]: ``{person_group_id, person_ids}`` per group, in group id order; empty when none left
    """
    return [{LeftMembersKey.PERSON_GROUP_ID.value: group_id, LeftMembersKey.PERSON_IDS.value: person_ids}
            for group_id, person_ids in sorted(result.left_members.items())]


def pass_counts(result: SyncResult) -> dict[str, Any]:
    """
    Counts what a pass wrote, for the answer next to the settings, and names who left a mapped person group

    Args:
        result (SyncResult): What the pass wrote

    Returns:
        dict[str, Any]: ``created`` and ``edited`` (counts), ``left`` (``left_members_view``)
    """
    return {PersonSyncAnswerKey.CREATED.value: len(result.created), PersonSyncAnswerKey.EDITED.value: len(result.edits),
            PersonSyncAnswerKey.LEFT.value: left_members_view(result)}


def user_sync_from_body(body: dict[str, Any]) -> UserSyncSettings:
    """
    Reads the user sync's settings from a validated body, refusing a user with two overrides

    Args:
        body (dict[str, Any]): The body (``USER_SYNC_SCHEMA``)

    Raises:
        HTTPException: 400 when a user carries more than one override

    Returns:
        UserSyncSettings: The settings
    """
    user_ids: list[int] = [entry[TypeOverrideKey.USER_ID.value] for entry in body[PersonSyncKey.TYPE_OVERRIDES.value]]

    if duplicates := sorted({user_id for user_id in user_ids if user_ids.count(user_id) > 1}):
        abort(400, PersonSyncMessage.DUPLICATE_OVERRIDE.value.format(user_ids=duplicates))

    return UserSyncSettings(
        active=body[PersonSyncKey.ACTIVE.value],
        default_type_id=body[PersonSyncKey.DEFAULT_TYPE_ID.value],
        type_overrides={
            entry[TypeOverrideKey.USER_ID.value]: entry[TypeOverrideKey.TYPE_ID.value]
            for entry in body[PersonSyncKey.TYPE_OVERRIDES.value]
        },
    )


def _run_pass(context: SyncContext, sync_pass: SyncPass) -> SyncResult:
    """
    Runs a pass, answering a Type it cannot write into as the caller's problem

    Args:
        context (SyncContext): The managers, the settings the pass runs on and the acting user
        sync_pass (SyncPass): The pass

    Raises:
        HTTPException: 400 when a person's Type is gone or unusable - nothing was written

    Returns:
        SyncResult: What the pass wrote
    """
    try:
        return sync_pass(context)
    except PersonSyncTargetError as err:
        abort(400, str(err))


def _store_and_sync(request_user: CmdbUser, context: SyncContext, settings: PersonSyncSettings,
                    sync_pass: SyncPass | None, pass_first: bool) -> SyncResult:
    """
    Stores judged settings and runs their pass in the given order, then the pass's change logs and webhooks

    Args:
        request_user (CmdbUser): The caller, credited with the writes
        context (SyncContext): The managers and the acting user
        settings (PersonSyncSettings): The judged settings
        sync_pass (SyncPass | None): The pass to run; None for none
        pass_first (bool): Whether the pass runs before the settings are stored

    Returns:
        SyncResult: What the pass wrote
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    run_context: SyncContext = replace(context, settings=settings)
    result = SyncResult()

    if sync_pass is not None and pass_first:
        result = _run_pass(run_context, sync_pass)

    write_sync_settings(settings_manager, settings)

    if sync_pass is not None and not pass_first:
        result = _run_pass(run_context, sync_pass)

    emit_sync_events(context.objects_manager, result, build_sync_events(request_user))

    return result


def _judged_user_sync(request_user: CmdbUser, body: dict[str, Any]) -> tuple[SyncContext, PersonSyncSettings]:
    """
    Reads new user sync settings from a body and judges them - switched off, the group sync goes off with them

    Args:
        request_user (CmdbUser): The caller
        body (dict[str, Any]): The validated body (``USER_SYNC_SCHEMA``)

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        tuple[SyncContext, PersonSyncSettings]: The context on the stored settings, and the new settings
    """
    context: SyncContext = person_sync_context(request_user)
    users: UserSyncSettings = user_sync_from_body(body)
    settings: PersonSyncSettings = replace(context.settings, users=users)

    if not users.active:
        settings = switch_user_sync_off(settings)

    abort_on_problems(find_sync_settings_problems(settings, context.types_manager, context.users_manager))

    return context, settings


def check_user_sync(request_user: CmdbUser, body: dict[str, Any]) -> list[PersonRelocation]:
    """
    Judges new user sync settings and plans the persons they relocate - nothing is written

    Args:
        request_user (CmdbUser): The caller
        body (dict[str, Any]): The validated body (``USER_SYNC_SCHEMA``)

    Raises:
        HTTPException: 400 naming every problem of the settings

    Returns:
        list[PersonRelocation]: Every person whose Type changes, each with what keeps it from moving
    """
    context, settings = _judged_user_sync(request_user, body)

    return plan_relocations(context, relocation_stores(request_user), settings.users)


def store_user_sync(request_user: CmdbUser,
                    body: dict[str, Any]) -> tuple[PersonSyncSettings, SyncResult, list[PersonRelocation]]:
    """
    Judges and stores the user sync's settings: the persons whose Type changes are relocated first; on runs the pass,
    off switches the group sync off too and deactivates the persons

    Args:
        request_user (CmdbUser): The caller
        body (dict[str, Any]): The validated body (``USER_SYNC_SCHEMA``)

    Raises:
        HTTPException: 400 naming every problem, the persons that cannot move (unless copied), or a Type the pass
            cannot write into

    Returns:
        tuple[PersonSyncSettings, SyncResult, list[PersonRelocation]]: The stored settings, what was written, and the
            relocations
    """
    context, settings = _judged_user_sync(request_user, body)
    stores: RelocationStores = relocation_stores(request_user)
    relocations: list[PersonRelocation] = plan_relocations(context, stores, settings.users)
    refuse_blocked(relocations, body[ON_BLOCKED_KEY])

    result: SyncResult = apply_relocations(request_user, replace(context, settings=settings), stores, relocations)
    sync_pass: SyncPass = run_sync_pass if settings.users.active else switch_off_pass
    result.merge(_store_and_sync(request_user, context, settings, sync_pass, pass_first=settings.users.active))

    return settings, result, relocations


def store_group_sync(request_user: CmdbUser, active: bool,
                     default_type_id: int | None) -> tuple[PersonSyncSettings, SyncResult]:
    """
    Judges and stores the user group sync's settings; switched on, the pass gives every user group its person group
    and brings each in line

    Switched off, nothing is written but the settings: the mapped person groups are unlocked, kept as they are. A new
    default Type applies to person groups created afterwards

    Args:
        request_user (CmdbUser): The caller
        active (bool): The switch
        default_type_id (int | None): The PERSON_GROUP Type person groups are created in

    Raises:
        HTTPException: 400 naming every problem, or a Type the pass cannot write into

    Returns:
        tuple[PersonSyncSettings, SyncResult]: The stored settings and what the pass wrote
    """
    context: SyncContext = person_sync_context(request_user)
    settings: PersonSyncSettings = replace(context.settings,
                                           groups=GroupSyncSettings(active=active, default_type_id=default_type_id))

    abort_on_problems(find_sync_settings_problems(settings, context.types_manager, context.users_manager))

    return settings, _store_and_sync(request_user, context, settings, run_sync_pass if active else None,
                                     pass_first=True)


def resync(request_user: CmdbUser) -> tuple[PersonSyncSettings, SyncResult]:
    """
    Runs the pass on the stored settings - catching up whatever a failed sync left

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 while the user sync is off, or for a Type the pass cannot write into

    Returns:
        tuple[PersonSyncSettings, SyncResult]: The settings the pass ran on, and what it wrote
    """
    context: SyncContext = person_sync_context(request_user)

    if not context.settings.users.active:
        abort(400, PersonSyncMessage.USER_SYNC_OFF.value)

    result: SyncResult = _run_pass(context, run_sync_pass)
    emit_sync_events(context.objects_manager, result, build_sync_events(request_user))

    return context.settings, result


def _read_user_group(context: SyncContext, user_group_id: int) -> CmdbUserGroup:
    """
    Reads a user group, answering a missing one

    Args:
        context (SyncContext): The managers
        user_group_id (int): The user group

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        CmdbUserGroup: The user group
    """
    user_group: CmdbUserGroup | None = context.groups_manager.get_group(user_group_id)

    if user_group is None:
        abort(404, PersonSyncMessage.USER_GROUP_NOT_FOUND.value.format(user_group_id=user_group_id))

    return user_group


def _abort_unless_permitted(request_user: CmdbUser, type_id: Any,
                            permissions: tuple[AccessControlPermission, ...], message: str) -> None:
    """
    Refuses a mapping the caller's Type ACL does not allow - the sync writes as the system, so the caller is judged
    on what it chose

    Args:
        request_user (CmdbUser): The caller
        type_id (Any): The Type judged
        permissions (tuple[AccessControlPermission, ...]): Every permission the caller needs on it
        message (str): The 403's message

    Raises:
        HTTPException: 403 when one permission is denied
    """
    if any(type_id in resolve_denied_type_ids(request_user, permission) for permission in permissions):
        abort(403, message)


def _judge_person_group(context: SyncContext, person_group_id: int) -> dict[str, Any]:
    """
    Reads and judges the person group a user group adopts: READ and UPDATE on its Type, then the person group rules

    Args:
        context (SyncContext): The managers and the acting user
        person_group_id (int): The person group's public_id

    Raises:
        HTTPException: 400 naming the problem; 403 for a Type the caller's ACL denies

    Returns:
        dict[str, Any]: The person group as stored
    """
    found: list[dict[str, Any]] = context.objects_manager.find(
        criteria={CmdbObjectKey.PUBLIC_ID.value: person_group_id})
    stored: dict[str, Any] | None = found[0] if found else None

    if stored is not None:
        group_type_id: Any = stored.get(CmdbObjectKey.TYPE_ID.value)
        _abort_unless_permitted(context.acting_user, group_type_id, MAPPED_GROUP_PERMISSIONS,
                                PersonSyncMessage.MAPPED_GROUP_DENIED.value.format(
                                    public_id=person_group_id, type_id=group_type_id))

    abort_on_problems(existing_person_group_problems(person_group_id, stored))

    return stored


def map_group(request_user: CmdbUser, user_group_id: int, body: dict[str, Any]) -> tuple[int, SyncResult]:
    """
    Maps a user group to an existing person group, unlinking the one it was mapped to, with the group sync's writes on
    one ledger

    Adopting the person group the user group is mapped to already changes nothing

    Args:
        request_user (CmdbUser): The caller, credited with the writes
        user_group_id (int): The user group
        body (dict[str, Any]): The validated body (``GROUP_MAPPING_SCHEMA``)

    Raises:
        HTTPException: 404 for a missing user group; 400 for an unusable person group or a mapping a concurrent
            request took first; 403 for a person group whose Type the caller's ACL denies; 500 when the sync failed
            (nothing kept)

    Returns:
        tuple[int, SyncResult]: The person group's id and what the sync wrote (``left_members_view`` names who left;
            the previous person group's unlink among the edits)
    """
    context: SyncContext = person_sync_context(request_user)
    user_group: CmdbUserGroup = _read_user_group(context, user_group_id)
    person_group_id: int = body[GroupMappingBodyKey.PERSON_GROUP_ID.value]
    previous: dict[str, Any] | None = linked_object(context.objects_manager, SystemRefKind.USER_GROUP, user_group_id)

    if previous is not None and previous[CmdbObjectKey.PUBLIC_ID.value] == person_group_id:
        return person_group_id, SyncResult()

    person_group: dict[str, Any] = _judge_person_group(context, person_group_id)
    mapped: list[tuple[int, SyncResult]] = []

    def _map_and_sync(ledger: WriteLedger, write_context: SyncContext) -> SyncResult:
        public_id, result = map_user_group(write_context, ledger, user_group, person_group, previous)
        mapped.append((public_id, result))

        return result

    try:
        write_with_person_sync(request_user, _map_and_sync)
    except (BaseManagerInsertError, BaseManagerUpdateError) as err:
        abort_if_too_large(err)
        abort_if_duplicate(err, PersonSyncMessage.MAPPING_TAKEN.value)

    return mapped[0]


def read_settings(request_user: CmdbUser) -> PersonSyncSettings:
    """
    Reads the person sync settings of the caller's tenant

    Args:
        request_user (CmdbUser): The caller

    Returns:
        PersonSyncSettings: The settings; both syncs off when never written
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    return read_sync_settings(settings_manager)


def read_mappings(request_user: CmdbUser) -> list[dict[str, int]]:
    """
    Reads every user group mapping on the caller's tenant

    Args:
        request_user (CmdbUser): The caller

    Returns:
        list[dict[str, int]]: The mappings in user group id order
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    return read_group_mappings(objects_manager)


def user_person_link(request_user: CmdbUser, user_id: int) -> dict[str, Any]:
    """
    Answers a user's person: its id and Type, both None while the user has none

    Args:
        request_user (CmdbUser): The caller
        user_id (int): The user

    Raises:
        HTTPException: 404 for a missing user; 403 when the person is in a Type the caller may not READ

    Returns:
        dict[str, Any]: ``user_id``, ``person_id`` and ``type_id``
    """
    users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

    if users_manager.get_user(user_id) is None:
        abort(404, PersonSyncMessage.USER_NOT_FOUND.value.format(user_id=user_id))

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    person: dict[str, Any] | None = linked_object(objects_manager, SystemRefKind.USER, user_id)

    if person is None:
        return {UserPersonKey.USER_ID.value: user_id, UserPersonKey.PERSON_ID.value: None,
                UserPersonKey.TYPE_ID.value: None}

    type_id: int = person[CmdbObjectKey.TYPE_ID.value]

    if type_id in resolve_denied_type_ids(request_user, AccessControlPermission.READ):
        abort(403, PersonSyncMessage.PERSON_NOT_READABLE.value.format(user_id=user_id))

    return {UserPersonKey.USER_ID.value: user_id, UserPersonKey.PERSON_ID.value: person[CmdbObjectKey.PUBLIC_ID.value],
            UserPersonKey.TYPE_ID.value: type_id}
