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
What the sync keeps from being deleted or changed beneath it

**A synced person is not deleted while it is linked** - whether the user sync is on or not: it goes when its user does
(the sync unlinks it). **A mapped person group is not deleted while the user group sync is on**; while it is off the
group is unlocked and may go, its mapping with it.

**A target Type of the user sync is not deleted** (the default or any user's override) while it is chosen - a Type
still holding objects is refused anyway; this covers an empty one. **A target Type stays one the sync can write into**:
an update may not deactivate it or make it require a field the sync cannot fill (``sync_settings_rules``) - nor may a
global section template's update, which is copied into every Type using it. The rules take the settings; the routes
read them
"""
from typing import Any

from cmdb.manager import ObjectsManager, SettingsManager
from cmdb.models.object_model import CmdbObjectKey, SystemRefKind
from cmdb.models.type_model import CmdbType

from cmdb.framework.person_sync.person_sync_constants import SyncGuardProblem
from cmdb.framework.person_sync.sync_documents import linked_kind, linked_record_id
from cmdb.framework.person_sync.sync_reads import linked_person_type_ids
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, read_sync_settings
from cmdb.framework.person_sync.sync_settings_rules import target_type_problems, unfillable_field_names
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'synced_object_delete_refusals',
    'enforce_synced_objects_delete',
    'target_type_delete_refusal',
    'target_type_change_refusal',
    'guarded_person_type_ids',
    'template_change_refusal',
]

# Joins the refusals of one delete selection, and the problems of one Type change
SYNC_GUARD_SEPARATOR: str = ' '


def synced_object_delete_refusals(target_objects: list[dict[str, Any]], group_sync_active: bool) -> list[str]:
    """
    Names every target of a delete the sync keeps: each linked person, each mapped group while the group sync is on

    Args:
        target_objects (list[dict[str, Any]]): The objects being deleted, as stored
        group_sync_active (bool): Whether the user group sync is on

    Returns:
        list[str]: The refusals, in the selection's order; empty when the delete may go ahead
    """
    refusals: list[str] = []

    for document in target_objects:
        kind: Any = linked_kind(document)
        public_id: Any = document.get(CmdbObjectKey.PUBLIC_ID.value)
        record_id: Any = linked_record_id(document)

        if kind == SystemRefKind.USER.value:
            refusals.append(SyncGuardProblem.SYNCED_PERSON_DELETE.value.format(public_id=public_id, user_id=record_id))
        elif kind == SystemRefKind.USER_GROUP.value and group_sync_active:
            refusals.append(SyncGuardProblem.MAPPED_GROUP_DELETE.value.format(public_id=public_id, group_id=record_id))

    return refusals


def enforce_synced_objects_delete(objects_manager: ObjectsManager, target_objects: list[dict[str, Any]]) -> str | None:
    """
    Refuses a delete selection holding an object the sync keeps

    Reads the settings only when the selection holds a mapped person group - an ordinary delete reads nothing

    Args:
        objects_manager (ObjectsManager): Names the tenant database for the settings
        target_objects (list[dict[str, Any]]): The objects being deleted, as stored

    Returns:
        str | None: The refusal, or None when the delete may go ahead
    """
    group_sync_active: bool = False

    if any(linked_kind(document) == SystemRefKind.USER_GROUP.value for document in target_objects):
        settings_manager: SettingsManager = SettingsManager(objects_manager.dbm, objects_manager.db_name)
        group_sync_active = read_sync_settings(settings_manager).groups.active

    refusals: list[str] = synced_object_delete_refusals(target_objects, group_sync_active)

    return SYNC_GUARD_SEPARATOR.join(refusals) if refusals else None


def target_type_delete_refusal(settings: PersonSyncSettings, type_id: int) -> str | None:
    """
    Refuses deleting a Type the user sync is set to write into - the default or a user's override

    Args:
        settings (PersonSyncSettings): The stored sync settings
        type_id (int): The Type being deleted

    Returns:
        str | None: The refusal, or None when the Type is no target
    """
    if type_id in settings.users.target_type_ids():
        return SyncGuardProblem.TARGET_TYPE_DELETE.value.format(type_id=type_id)

    return None


def guarded_person_type_ids(settings: PersonSyncSettings, objects_manager: ObjectsManager) -> set[int]:
    """
    The Types the sync writes persons into: its targets, and every Type a linked person lives in - a person left in a
    Type that is no target any more is still written where it lives

    Args:
        settings (PersonSyncSettings): The stored sync settings
        objects_manager (ObjectsManager): Reads where the linked persons live (one distinct read)

    Returns:
        set[int]: The Type ids
    """
    return settings.users.target_type_ids() | linked_person_type_ids(objects_manager)


def target_type_change_refusal(guarded_type_ids: set[int], new_type: CmdbType) -> str | None:
    """
    Refuses a Type update that leaves a Type the sync writes persons into one it cannot write into

    The update is judged by what it would store: active, still carrying PERSON, no required field the sync cannot fill.
    Any other Type is never judged

    Args:
        guarded_type_ids (set[int]): The Types the sync writes persons into (``guarded_person_type_ids``)
        new_type (CmdbType): The Type the update would store

    Returns:
        str | None: The refusal naming every problem, or None
    """
    if new_type.public_id not in guarded_type_ids:
        return None

    problems: list[str] = target_type_problems(new_type.public_id, new_type)

    if not problems:
        return None

    return SyncGuardProblem.TARGET_TYPE_CHANGE.value.format(
        type_id=new_type.public_id, problems=SYNC_GUARD_SEPARATOR.join(problems),
    )


def template_change_refusal(template_name: str,
                            new_fields: list[dict[str, Any]],
                            in_rows: bool,
                            consuming_target_ids: list[int]) -> str | None:
    """
    Refuses a global section template update that would make a Type the sync writes persons into require an unfillable
    field

    The update is copied into every Type carrying the template's section, so its new fields become those Types'
    fields. Only they are judged - the rest of a target was judged when it was chosen or last changed. A multi-data
    section template's fields live in rows, which the sync never writes

    Args:
        template_name (str): The template's name - its section's name on the Types
        new_fields (list[dict[str, Any]]): The template's fields as the update would store them
        in_rows (bool): Whether the template is a multi-data section
        consuming_target_ids (list[int]): The Types the sync writes persons into that carry the template's section

    Returns:
        str | None: The refusal naming the Types and the fields, or None
    """
    if not consuming_target_ids or in_rows:
        return None

    unfillable: list[str] = unfillable_field_names(new_fields)

    if not unfillable:
        return None

    return SyncGuardProblem.TARGET_TEMPLATE_CHANGE.value.format(
        name=template_name, type_ids=sorted(consuming_target_ids), names=unfillable,
    )
