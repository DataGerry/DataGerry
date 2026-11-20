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
What a write may not change on a synced object - the user and the user group decide it

**A synced person** (``system_ref.kind = user``): its synced fields (display name, first name, last name, email) and
its active state change only through its user - by nobody, whatever their rights, and also while the user sync is
off, so switching it on again overwrites nothing anyone edited. Its own fields stay free.

**A mapped person group** (``system_ref.kind = user_group``), while the user group sync is on: its name changes only
through its user group, and its synced members only when a user joins or leaves the user group - a synced person is
neither removed nor added by hand. A person added by hand (one that is not synced) comes and goes freely, and a synced
person may be added by hand to a person group that is not mapped. While the group sync is off, the group is unlocked.

**A synced object keeps its Type** - the routes refuse a type change anyway; the import's overwrite may not either.

The judgement is pure (``locked_change_reasons``); ``enforce_sync_lock`` reads what it needs - nothing for an object
that is not synced, nothing more for a person, the settings and the members' links for a mapped person group
"""
from typing import Any

from cmdb.manager import ObjectsManager, SettingsManager
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind, extract_field_value
from cmdb.models.special_type_model.person_type_constants import PersonGroupField

from cmdb.framework.object_field_value_rules import has_no_value
from cmdb.framework.person_types.person_memberships import group_members
from cmdb.framework.person_sync.person_sync_constants import SYNCED_PERSON_FIELDS, SyncLockProblem
from cmdb.framework.person_sync.sync_documents import linked_kind, linked_record_id
from cmdb.framework.person_sync.sync_reads import synced_person_ids as read_synced_person_ids
from cmdb.framework.person_sync.sync_settings import read_sync_settings
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'locked_change_reasons',
    'enforce_sync_lock',
]

# Joins the reasons of one refused write
SYNC_LOCK_SEPARATOR: str = ' '


def _same_value(before: Any, after: Any) -> bool:
    """
    Whether a field keeps its value - an absent, null and empty value are the same empty value

    Args:
        before (Any): The stored value
        after (Any): The candidate's value

    Returns:
        bool: True when the value is unchanged
    """
    return (has_no_value(before) and has_no_value(after)) or before == after


def _person_reasons(previous: dict[str, Any], candidate: dict[str, Any], user_id: Any) -> list[str]:
    """
    Names what a write changes on a synced person that only its user may change

    Args:
        previous (dict[str, Any]): The stored person
        candidate (dict[str, Any]): The person as the write would store it
        user_id (Any): The user it mirrors

    Returns:
        list[str]: The reasons; empty when the write keeps them
    """
    public_id: Any = previous.get(CmdbObjectKey.PUBLIC_ID.value)
    reasons: list[str] = []
    changed: list[str] = [
        name for name in SYNCED_PERSON_FIELDS
        if not _same_value(extract_field_value(previous, name), extract_field_value(candidate, name))
    ]

    if changed:
        reasons.append(SyncLockProblem.PERSON_FIELDS.value.format(public_id=public_id, user_id=user_id, names=changed))

    if previous.get(CmdbObjectKey.ACTIVE.value) != candidate.get(CmdbObjectKey.ACTIVE.value):
        reasons.append(SyncLockProblem.PERSON_ACTIVE.value.format(public_id=public_id, user_id=user_id))

    return reasons


def _group_reasons(previous: dict[str, Any],
                   candidate: dict[str, Any],
                   group_id: Any,
                   synced_person_ids: set[int]) -> list[str]:
    """
    Names what a write changes on a mapped person group that only its user group may change

    Args:
        previous (dict[str, Any]): The stored person group
        candidate (dict[str, Any]): The person group as the write would store it
        group_id (Any): The user group it mirrors
        synced_person_ids (set[int]): Which of the stored and the candidate's members are synced persons

    Returns:
        list[str]: The reasons; empty when the write keeps them
    """
    public_id: Any = previous.get(CmdbObjectKey.PUBLIC_ID.value)
    reasons: list[str] = []
    name: str = PersonGroupField.NAME.value

    if not _same_value(extract_field_value(previous, name), extract_field_value(candidate, name)):
        reasons.append(SyncLockProblem.GROUP_NAME.value.format(public_id=public_id, group_id=group_id))

    synced_before: set[Any] = set(group_members(previous)) & synced_person_ids
    synced_after: set[Any] = set(group_members(candidate)) & synced_person_ids

    if synced_before != synced_after:
        reasons.append(SyncLockProblem.GROUP_MEMBERS.value.format(
            public_id=public_id, group_id=group_id,
            added=sorted(synced_after - synced_before), removed=sorted(synced_before - synced_after),
        ))

    return reasons


def locked_change_reasons(previous: dict[str, Any] | None,
                          candidate: dict[str, Any],
                          group_sync_active: bool = False,
                          synced_person_ids: set[int] | None = None) -> list[str]:
    """
    Names what a write changes on a synced object that user management alone may change

    Args:
        previous (dict[str, Any] | None): The stored object; None for a create, which no lock concerns
        candidate (dict[str, Any]): The object as the write would store it
        group_sync_active (bool): Whether the user group sync is on - a mapped person group is locked only then
        synced_person_ids (set[int] | None): Which of a person group's stored and candidate members are synced persons

    Returns:
        list[str]: The reasons; empty when the write may go ahead
    """
    if previous is None:
        return []

    kind: Any = linked_kind(previous)
    record_id: Any = linked_record_id(previous)

    if kind is None:
        return []

    reasons: list[str] = []

    if previous.get(CmdbObjectKey.TYPE_ID.value) != candidate.get(CmdbObjectKey.TYPE_ID.value):
        reasons.append(SyncLockProblem.TYPE.value.format(public_id=previous.get(CmdbObjectKey.PUBLIC_ID.value)))

    if kind == SystemRefKind.USER.value:
        reasons.extend(_person_reasons(previous, candidate, record_id))
    elif kind == SystemRefKind.USER_GROUP.value and group_sync_active:
        reasons.extend(_group_reasons(previous, candidate, record_id, synced_person_ids or set()))

    return reasons


def enforce_sync_lock(objects_manager: ObjectsManager,
                      candidate: dict[str, Any],
                      previous: dict[str, Any] | None) -> str | None:
    """
    Refuses a write that changes what user management alone may change on a synced object

    Reads nothing for an object that is not synced or a person; for a mapped person group the settings (one read) and,
    while the group sync is on, which of its stored and new members are synced persons (one query)

    Args:
        objects_manager (ObjectsManager): Reads the members, and names the tenant database for the settings
        candidate (dict[str, Any]): The object as the write would store it
        previous (dict[str, Any] | None): The stored object; None for a create

    Raises:
        ObjectsManagerGetError / DocumentGetError: When a read fails - the database's failure, never a refusal

    Returns:
        str | None: The refusal, or None when the write may go ahead
    """
    kind: Any = linked_kind(previous or {})

    if kind is None:
        return None

    group_sync_active: bool = False
    synced_person_ids: set[int] = set()

    if kind == SystemRefKind.USER_GROUP.value:
        settings_manager: SettingsManager = SettingsManager(objects_manager.dbm, objects_manager.db_name)
        group_sync_active = read_sync_settings(settings_manager).groups.active

        if group_sync_active:
            synced_person_ids = read_synced_person_ids(
                objects_manager, set(group_members(previous or {})) | set(group_members(candidate)),
            )

    reasons: list[str] = locked_change_reasons(previous, candidate, group_sync_active, synced_person_ids)

    return SYNC_LOCK_SEPARATOR.join(reasons) if reasons else None
