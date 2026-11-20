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
The documents the sync writes, built without reading anything

A new person is a complete object of its target Type: the synced values, the Type's usable defaults for every other
field (as the object create fills them), the PERSON marker, the link and the fingerprint. An edit replaces only the
synced values and the active state on a copy of the stored person - the person's own fields stay - and an edit of a
mapped person group only its name and members. Every field entry is a name / value / type triple, the type taken from
the Type's definition
"""
import copy
from datetime import datetime
from typing import Any

from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    CmdbObjectSyncKey,
    CmdbObjectSystemRefKey,
    SystemRefKind,
    OBJECT_SYNC_KEYS,
    extract_field_value,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldKey

from cmdb.framework.object_field_defaults import fill_object_defaults
from cmdb.framework.object_required_fields import mds_section_field_names
from cmdb.framework.person_types.person_memberships import group_members
from cmdb.framework.person_sync.sync_mapping import SyncedPerson, merge_group_members, person_group_name
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'system_ref_of',
    'linked_kind',
    'linked_record_id',
    'with_field_values',
    'build_person_document',
    'build_person_group_document',
    'person_after_sync',
    'group_after_sync',
    'group_without_members',
    'group_sync_change',
    'relocated_person',
    'former_person',
]


def system_ref_of(kind: SystemRefKind, record_id: int) -> dict[str, Any]:
    """
    Builds the link of an object mirroring a user-management record

    Args:
        kind (SystemRefKind): User or user group
        record_id (int): The record's public_id

    Returns:
        dict[str, Any]: The ``system_ref`` value
    """
    return {CmdbObjectSystemRefKey.KIND.value: kind.value, CmdbObjectSystemRefKey.ID.value: record_id}


def _link(document: dict[str, Any]) -> dict[str, Any]:
    """The object's ``system_ref``; empty for an object that mirrors nothing"""
    system_ref: Any = document.get(CmdbObjectKey.SYSTEM_REF.value)

    return system_ref if isinstance(system_ref, dict) else {}


def linked_kind(document: dict[str, Any]) -> Any:
    """
    Returns the kind of record an object mirrors

    Args:
        document (dict[str, Any]): The object

    Returns:
        Any: ``user`` or ``user_group``; None for an object that mirrors nothing
    """
    return _link(document).get(CmdbObjectSystemRefKey.KIND.value)


def linked_record_id(document: dict[str, Any]) -> Any:
    """
    Returns the id of the user-management record an object mirrors

    Args:
        document (dict[str, Any]): The object

    Returns:
        Any: The record's public_id; None for an object that mirrors nothing
    """
    return _link(document).get(CmdbObjectSystemRefKey.ID.value)


def _field_kinds(type_instance: CmdbType) -> dict[str, Any]:
    """
    Returns each field's kind by name, as the Type declares it

    Args:
        type_instance (CmdbType): The Type

    Returns:
        dict[str, Any]: field name -> kind
    """
    return {field.get(FieldKey.NAME.value): field.get(FieldKey.TYPE.value) for field in type_instance.get_fields()}


def with_field_values(entries: list[dict[str, Any]], values: dict[str, Any],
                      field_kinds: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Returns a copy of field entries with the given values set - an entry the list lacks is appended

    Args:
        entries (list[dict[str, Any]]): The stored field entries; not changed
        values (dict[str, Any]): field name -> value to set
        field_kinds (dict[str, Any]): field name -> kind, stamped as each set entry's ``type``

    Returns:
        list[dict[str, Any]]: The entries, in their stored order, the missing ones after them in the values' order
    """
    updated: list[dict[str, Any]] = copy.deepcopy(entries)
    by_name: dict[Any, dict[str, Any]] = {entry.get(CmdbObjectFieldKey.NAME.value): entry for entry in updated}

    for name, value in values.items():
        entry: dict[str, Any] | None = by_name.get(name)

        if entry is None:
            entry = {CmdbObjectFieldKey.NAME.value: name}
            updated.append(entry)

        entry[CmdbObjectFieldKey.VALUE.value] = value
        entry[CmdbObjectFieldKey.TYPE.value] = field_kinds.get(name)

    return updated


def _new_linked_object(public_id: int, type_instance: CmdbType, marker: SpecialType, link: dict[str, Any],
                       values: dict[str, Any], active: bool, author_id: int, now: datetime) -> dict[str, Any]:
    """
    Builds an object the sync creates, complete as the object create would store it: the values, the Type's usable
    defaults for every other field, the marker and the link

    Args:
        public_id (int): The id reserved for the object
        type_instance (CmdbType): Its Type
        marker (SpecialType): PERSON or PERSON_GROUP
        link (dict[str, Any]): Its ``system_ref`` (``system_ref_of``)
        values (dict[str, Any]): field name -> value
        active (bool): Its active state
        author_id (int): The user credited with the create
        now (datetime): The creation time

    Returns:
        dict[str, Any]: The object
    """
    document: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID.value: public_id,
        CmdbObjectKey.TYPE_ID.value: type_instance.public_id,
        CmdbObjectKey.AUTHOR_ID.value: author_id,
        CmdbObjectKey.CREATION_TIME.value: now,
        CmdbObjectKey.VERSION.value: CmdbObject.DEFAULT_VERSION,
        CmdbObjectKey.ACTIVE.value: active,
        CmdbObjectKey.SPECIAL_TYPE.value: marker.value,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [],
        CmdbObjectKey.FIELDS.value: with_field_values([], values, _field_kinds(type_instance)),
    }
    fill_object_defaults(document, type_instance)
    document[CmdbObjectKey.SYSTEM_REF.value] = link

    return document


def build_person_document(public_id: int, type_instance: CmdbType, user_id: int, synced: SyncedPerson,
                          author_id: int, now: datetime) -> dict[str, Any]:
    """
    Builds the person the sync creates for a user, complete as the object create would store it

    Args:
        public_id (int): The id reserved for the person
        type_instance (CmdbType): Its target Type
        user_id (int): The user it mirrors
        synced (SyncedPerson): The user's values and active state
        author_id (int): The user credited with the create
        now (datetime): The creation time

    Returns:
        dict[str, Any]: The person, with its link and fingerprint
    """
    document: dict[str, Any] = _new_linked_object(
        public_id, type_instance, SpecialType.PERSON, system_ref_of(SystemRefKind.USER, user_id), synced.values,
        synced.active, author_id, now,
    )
    document[CmdbObjectSyncKey.SYNC_HASH.value] = synced.fingerprint()

    return document


def build_person_group_document(public_id: int, type_instance: CmdbType, user_group_id: int, name: str,
                                author_id: int, now: datetime) -> dict[str, Any]:
    """
    Builds the person group the sync creates for a user group, complete as the object create would store it

    It starts without members: the group sync, when on, adds the user group's persons

    Args:
        public_id (int): The id of the person group
        type_instance (CmdbType): Its Type, carrying PERSON_GROUP
        user_group_id (int): The user group it mirrors
        name (str): Its name (``sync_mapping.person_group_name``)
        author_id (int): The user credited with the create
        now (datetime): The creation time

    Returns:
        dict[str, Any]: The person group, with its link
    """
    return _new_linked_object(
        public_id, type_instance, SpecialType.PERSON_GROUP, system_ref_of(SystemRefKind.USER_GROUP, user_group_id),
        {PersonGroupField.NAME.value: name, PersonGroupField.MEMBERS.value: []}, True, author_id, now,
    )


def person_after_sync(stored: dict[str, Any], type_instance: CmdbType, synced: SyncedPerson) -> dict[str, Any]:
    """
    Builds a stored person as the sync leaves it: its synced values and active state its user's, the rest kept

    Args:
        stored (dict[str, Any]): The stored person; not changed
        type_instance (CmdbType): Its Type
        synced (SyncedPerson): The user's values and active state

    Returns:
        dict[str, Any]: The person after the sync, its fingerprint the new one
    """
    after: dict[str, Any] = copy.deepcopy(stored)
    after[CmdbObjectKey.FIELDS.value] = with_field_values(
        stored.get(CmdbObjectKey.FIELDS.value) or [], synced.values, _field_kinds(type_instance),
    )
    after[CmdbObjectKey.ACTIVE.value] = synced.active
    after[CmdbObjectSyncKey.SYNC_HASH.value] = synced.fingerprint()

    return after


def group_after_sync(stored: dict[str, Any], type_instance: CmdbType, name: str, members: list[int]) -> dict[str, Any]:
    """
    Builds a stored mapped person group as the sync leaves it: its name and members set, the rest kept

    Args:
        stored (dict[str, Any]): The stored person group; not changed
        type_instance (CmdbType): Its Type
        name (str): The user group's label
        members (list[int]): The members (``sync_mapping.merge_group_members``)

    Returns:
        dict[str, Any]: The person group after the sync
    """
    after: dict[str, Any] = copy.deepcopy(stored)
    after[CmdbObjectKey.FIELDS.value] = with_field_values(
        stored.get(CmdbObjectKey.FIELDS.value) or [],
        {PersonGroupField.NAME.value: name, PersonGroupField.MEMBERS.value: members},
        _field_kinds(type_instance),
    )

    return after


def group_sync_change(stored: dict[str, Any], user_group: CmdbUserGroup, synced_ids: set[int],
                      synced_members: list[int]) -> tuple[str, list[int]] | None:
    """
    Decides what the sync sets on a mapped person group: its user group's name, the hand-added persons then the synced
    members (``merge_group_members``)

    Args:
        stored (dict[str, Any]): The stored person group
        user_group (CmdbUserGroup): The user group it mirrors
        synced_ids (set[int]): Every synced person (and former user) among its stored members - the members the sync
            decides about
        synced_members (list[int]): The persons the user group gives it (``synced_member_ids``)

    Returns:
        tuple[str, list[int]] | None: The name and members to write; None when both are as stored
    """
    stored_members: list[int] = group_members(stored)
    members: list[int] = merge_group_members(stored_members, synced_ids, synced_members)
    name: str = person_group_name(user_group)

    if members == stored_members and extract_field_value(stored, PersonGroupField.NAME.value) == name:
        return None

    return name, members


def group_without_members(stored: dict[str, Any], type_instance: CmdbType, person_ids: set[int]) -> dict[str, Any]:
    """
    Builds a stored person group with the given persons taken out of its members - its name and every other member
    kept

    Args:
        stored (dict[str, Any]): The stored person group; not changed
        type_instance (CmdbType): Its Type
        person_ids (set[int]): The persons leaving it

    Returns:
        dict[str, Any]: The person group after the persons left
    """
    return group_after_sync(
        stored, type_instance, extract_field_value(stored, PersonGroupField.NAME.value),
        [member for member in group_members(stored) if member not in person_ids],
    )


def _kept_entries(entries: list[dict[str, Any]], kinds: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    """
    Keeps the entries the new Type declares among the allowed names with the same kind - copies, in their order

    Args:
        entries (list[dict[str, Any]]): Field entries - an object's ``fields`` or one row's ``data``
        kinds (dict[str, Any]): The new Type's kinds by field name
        allowed (set[str]): The names the list may carry in the new Type

    Returns:
        list[dict[str, Any]]: The entries kept
    """
    return [
        copy.deepcopy(entry) for entry in entries
        if entry.get(CmdbObjectFieldKey.NAME.value) in allowed
        and kinds.get(entry.get(CmdbObjectFieldKey.NAME.value)) == entry.get(CmdbObjectFieldKey.TYPE.value)
    ]


def relocated_person(stored: dict[str, Any], to_type: CmdbType) -> dict[str, Any]:
    """
    Builds a stored person as it lives in its new Type - the same object, its ``public_id`` kept

    The values the new Type declares with the same kind are kept, the rest is dropped (the pre-check refuses a move
    that would drop a value); the multi-data sections the new Type declares keep their rows; the new Type's usable
    defaults fill what is missing. The fingerprint goes, so the next sync rewrites the synced values under the new
    Type's rules

    Args:
        stored (dict[str, Any]): The stored person; not changed
        to_type (CmdbType): Its new Type

    Returns:
        dict[str, Any]: The person in the new Type
    """
    kinds: dict[str, Any] = _field_kinds(to_type)
    sections: dict[str, list[str]] = mds_section_field_names(to_type)
    row_names: set[str] = {name for names in sections.values() for name in names}
    after: dict[str, Any] = copy.deepcopy(stored)
    after.pop(CmdbObjectSyncKey.SYNC_HASH.value, None)
    after[CmdbObjectKey.TYPE_ID.value] = to_type.public_id
    after[CmdbObjectKey.FIELDS.value] = _kept_entries(stored.get(CmdbObjectKey.FIELDS.value) or [], kinds,
                                                      set(kinds) - row_names)
    after[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = [
        {**copy.deepcopy(section), CmdbObjectMdsKey.VALUES.value: [
            {**copy.deepcopy(row), CmdbObjectMdsRowKey.DATA.value: _kept_entries(
                row.get(CmdbObjectMdsRowKey.DATA.value) or [], kinds,
                set(sections[section[CmdbObjectMdsKey.SECTION_ID.value]]))}
            for row in section.get(CmdbObjectMdsKey.VALUES.value) or []
        ]}
        for section in stored.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []
        if section.get(CmdbObjectMdsKey.SECTION_ID.value) in sections
    ]
    fill_object_defaults(after, to_type)

    return after


def former_person(stored: dict[str, Any]) -> dict[str, Any]:
    """
    Builds a stored person as a former user's: unlinked (no ``system_ref``, no ``sync_hash``), deactivated, its values
    kept - so it is unlocked, deletable and a ConfigItem again

    The caller writes it with ``OBJECT_SYNC_KEYS`` unset

    Args:
        stored (dict[str, Any]): The stored person; not changed

    Returns:
        dict[str, Any]: The former user's person
    """
    after: dict[str, Any] = {key: value for key, value in stored.items() if key not in OBJECT_SYNC_KEYS}
    after[CmdbObjectKey.ACTIVE.value] = False

    return after
