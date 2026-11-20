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
Mapping a user group to a person group: an existing one, or one the sync creates

A mapping is the person group's link (``system_ref`` of kind ``user_group``) and nothing else - one person group per
user group and one user group per person group, the unique index holding both under concurrency. A mapping is stored
whatever the switches; while the user group sync is on, the person group takes its user group's name and synced
members at once.

**Mapping an existing person group** links it, its fields untouched until the group sync writes them. Refused when the
object is gone, is no person group, is deactivated, or mirrors a user group already.

**Creating one** writes a person group in a Type carrying PERSON_GROUP, named after the user group, without members;
the Type must be active and require nothing but the name and members without a usable default.

The judgements are pure; the writes go into the caller's ledger
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.manager import ObjectsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.person_sync_constants import (
    KIND_PATH,
    PERSON_GROUP_FILLED_FIELDS,
    GroupMappingKey,
    GroupMappingProblem,
    PersonSyncProblem,
)
from cmdb.framework.person_sync.sync_documents import build_person_group_document, linked_record_id, system_ref_of
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult, insert_linked_object, sync_user_group
from cmdb.framework.person_sync.sync_mapping import person_group_name
from cmdb.framework.person_sync.sync_settings_rules import unfillable_required_fields
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'read_group_mappings',
    'existing_person_group_problems',
    'person_group_type_problems',
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


def person_group_type_problems(type_id: int, type_instance: CmdbType | None) -> list[str]:
    """
    Judges the Type a new mapped person group is created in: it exists, carries PERSON_GROUP, is active and requires
    nothing but the name and members without a usable default

    Args:
        type_id (int): The chosen Type's id
        type_instance (CmdbType | None): The stored Type, None when there is none

    Returns:
        list[str]: The problems; a missing Type has only that one
    """
    if type_instance is None:
        return [PersonSyncProblem.TYPE_MISSING.value.format(type_id=type_id)]

    if type_instance.special_type != SpecialType.PERSON_GROUP.value:
        return [GroupMappingProblem.TYPE_NOT_PERSON_GROUP.value.format(type_id=type_id)]

    problems: list[str] = []

    if not type_instance.active:
        problems.append(PersonSyncProblem.TYPE_INACTIVE.value.format(type_id=type_id))

    if unfillable := unfillable_required_fields(type_instance, PERSON_GROUP_FILLED_FIELDS):
        problems.append(PersonSyncProblem.TYPE_UNFILLABLE_FIELDS.value.format(type_id=type_id, names=unfillable))

    return problems


def _create_person_group(context: SyncContext, ledger: WriteLedger, user_group: CmdbUserGroup,
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


def map_user_group(context: SyncContext, ledger: WriteLedger, user_group: CmdbUserGroup,
                   person_group: dict[str, Any] | None = None,
                   type_instance: CmdbType | None = None) -> tuple[int, SyncResult]:
    """
    Maps a user group to an existing person group, or to one created in the given Type - judged by the caller

    While both syncs are on, the person group takes the user group's name and synced members in the same ledger

    Args:
        context (SyncContext): The managers, the settings and the acting user
        ledger (WriteLedger): Records every write
        user_group (CmdbUserGroup): The user group, mapped nowhere yet
        person_group (dict[str, Any] | None): The existing person group (``existing_person_group_problems``)
        type_instance (CmdbType | None): The Type of a new one (``person_group_type_problems``); used without
            ``person_group``

    Raises:
        ValueError: When neither a person group nor a Type is given

    Returns:
        tuple[int, SyncResult]: The person group's id and what the sync wrote - the create among it
    """
    result = SyncResult()

    if person_group is not None:
        public_id: int = person_group[CmdbObjectKey.PUBLIC_ID.value]
        ledger.updated(context.objects_manager, public_id, person_group)
        context.objects_manager.update({CmdbObjectKey.PUBLIC_ID.value: public_id},
                                       {CmdbObjectKey.SYSTEM_REF.value: system_ref_of(SystemRefKind.USER_GROUP,
                                                                                      user_group.public_id)})
        result.config_items_changed = True
    elif type_instance is not None:
        public_id = _create_person_group(context, ledger, user_group, type_instance)
        result.created.append(public_id)
    else:
        raise ValueError("A user group is mapped to an existing person group or to a new one in a Type")

    result.merge(sync_user_group(context, ledger, user_group))

    return public_id, result
