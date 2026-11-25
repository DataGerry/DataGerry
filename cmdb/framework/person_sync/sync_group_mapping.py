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
Mapping a user group to an existing person group - adopting it instead of the one the sync created

A mapping is the person group's link (``system_ref`` of kind ``user_group``) and nothing else - one person group per
user group and one user group per person group, the unique index holding both under concurrency. A mapping is stored
whatever the switches; while the user group sync is on, the person group takes its user group's name and synced
members at once. The sync itself creates a user group's person group in its default Type (``sync_engine``)

**Adopting an existing person group** links it, its fields untouched until the group sync writes them, and unlinks the
person group the user group was mapped to - kept, unlocked, its unlink logged. Refused when the object is gone, is no
person group, is deactivated, or mirrors another user group.

The judgements are pure; the writes go into the caller's ledger
"""
from typing import Any

from cmdb.manager import ObjectsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind
from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.person_sync_constants import (
    KIND_PATH,
    GroupMappingKey,
    GroupMappingProblem,
)
from cmdb.framework.person_sync.sync_documents import linked_record_id, system_ref_of
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult, sync_user_group, write_edit
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'read_group_mappings',
    'existing_person_group_problems',
    'map_user_group',
]


def read_group_mappings(objects_manager: ObjectsManager) -> list[dict[str, int]]:
    """
    Reads every user group mapping - one read of the mapped person groups' links

    Args:
        objects_manager (ObjectsManager): Reads the person groups

    Returns:
        list[dict[str, int]]: ``{user_group_id, person_group_id}`` entries in user group id order
    """
    linked: list[dict[str, Any]] = objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.SYSTEM_REF.value: 1},
    )

    return sorted(
        (
            {
                GroupMappingKey.USER_GROUP_ID.value: linked_record_id(document),
                GroupMappingKey.PERSON_GROUP_ID.value: document[CmdbObjectKey.PUBLIC_ID.value],
            }
            for document in linked
        ),
        key=lambda mapping: mapping[GroupMappingKey.USER_GROUP_ID.value],
    )


def existing_person_group_problems(public_id: int, stored: dict[str, Any] | None) -> list[str]:
    """
    Judges an existing object chosen to mirror a user group: it exists, is an active person group and mirrors nothing
    yet

    Args:
        public_id (int): The chosen object's id
        stored (dict[str, Any] | None): The stored object, None when there is none

    Returns:
        list[str]: The problems; at most one
    """
    if stored is None:
        return [GroupMappingProblem.OBJECT_MISSING.value.format(public_id=public_id)]

    if stored.get(CmdbObjectKey.SPECIAL_TYPE.value) != SpecialType.PERSON_GROUP.value:
        return [GroupMappingProblem.NOT_PERSON_GROUP.value.format(public_id=public_id)]

    if (user_group_id := linked_record_id(stored)) is not None:
        return [GroupMappingProblem.PERSON_GROUP_MAPPED.value.format(public_id=public_id, user_group_id=user_group_id)]

    if stored.get(CmdbObjectKey.ACTIVE.value) is False:
        return [GroupMappingProblem.PERSON_GROUP_INACTIVE.value.format(public_id=public_id)]

    return []


def map_user_group(context: SyncContext, ledger: WriteLedger, user_group: CmdbUserGroup,
                   person_group: dict[str, Any], previous: dict[str, Any] | None = None) -> tuple[int, SyncResult]:
    """
    Maps a user group to an existing person group - judged by the caller - unlinking the person group it was mapped to

    The previous person group is unlinked first (the link index allows one per user group): it keeps its name and
    members, is unlocked from then on, and its unlink is logged like a former user's. While both syncs are on, the
    chosen person group takes the user group's name and synced members in the same ledger

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write
        user_group (CmdbUserGroup): The user group
        person_group (dict[str, Any]): The existing person group (``existing_person_group_problems``)
        previous (dict[str, Any] | None): The person group the user group is mapped to now; None when it is mapped
            nowhere

    Returns:
        tuple[int, SyncResult]: The person group's id and what the sync wrote - the unlink among the edits
    """
    result = SyncResult(config_items_changed=True)

    if previous is not None:
        unlinked: dict[str, Any] = {key: value for key, value in previous.items()
                                    if key != CmdbObjectKey.SYSTEM_REF.value}
        result.edits[previous[CmdbObjectKey.PUBLIC_ID.value]] = write_edit(
            context, ledger, previous, unlinked, unset=(CmdbObjectKey.SYSTEM_REF.value,))

    public_id: int = person_group[CmdbObjectKey.PUBLIC_ID.value]
    ledger.updated(context.objects_manager, public_id, person_group)
    context.objects_manager.update({CmdbObjectKey.PUBLIC_ID.value: public_id},
                                   {CmdbObjectKey.SYSTEM_REF.value: system_ref_of(SystemRefKind.USER_GROUP,
                                                                                  user_group.public_id)})
    result.merge(sync_user_group(context, ledger, user_group))

    return public_id, result
