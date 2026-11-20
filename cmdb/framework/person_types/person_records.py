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
The person and person group records of the old ``/persons`` and ``/person_groups`` routes, read off the objects

Since the migration a person is an object of a Type carrying PERSON, a group one of a Type carrying PERSON_GROUP. The
old routes keep their request and response shape: a record is an object reshaped into the keys the old documents had -
its ``public_id`` the object's id, each key the value of the base field of the same name (a group's ``group_members``
its ``members``). A person's ``groups`` are not stored on the person: they are the groups whose members hold it
(membership lives on the group side).

  - ``record_stages``: the aggregation stages turning the objects of a marker the reader may read into records, so a
    client's filter and sort run on the old keys
  - ``record_of``: one object as a record
  - ``field_entries``: the object field entries a record body sets - only the keys it carries
  - ``groups_of_persons``: the readable groups whose members hold each person - one read
"""
from typing import Any, Iterable

from cmdb.utils import Builder
from cmdb.manager import ObjectsManager
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import PersonField, PersonGroupField
from cmdb.framework.person_types.person_memberships import group_members, holding_members_criteria
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'GROUP_MEMBERS_KEY',
    'PERSON_GROUPS_KEY',
    'RECORD_FIELDS',
    'field_entries',
    'field_value_expression',
    'groups_of_persons',
    'record_of',
    'record_stages',
]

MONGO_ID: str = '_id'
PUBLIC_ID: str = CmdbObjectKey.PUBLIC_ID.value

# The record key of a person's groups (computed) and of a group's members (the base field 'members')
PERSON_GROUPS_KEY: str = 'groups'
GROUP_MEMBERS_KEY: str = 'group_members'

# Per marker: each record key with the base field it is read from and written to
RECORD_FIELDS: dict[SpecialType, dict[str, str]] = {
    SpecialType.PERSON: {
        PersonField.DISPLAY_NAME.value: PersonField.DISPLAY_NAME.value,
        PersonField.FIRST_NAME.value: PersonField.FIRST_NAME.value,
        PersonField.LAST_NAME.value: PersonField.LAST_NAME.value,
        PersonField.PHONE_NUMBER.value: PersonField.PHONE_NUMBER.value,
        PersonField.EMAIL.value: PersonField.EMAIL.value,
    },
    SpecialType.PERSON_GROUP: {
        PersonGroupField.NAME.value: PersonGroupField.NAME.value,
        PersonGroupField.EMAIL.value: PersonGroupField.EMAIL.value,
        GROUP_MEMBERS_KEY: PersonGroupField.MEMBERS.value,
    },
}


def field_value_expression(field_name: str) -> dict[str, Any]:
    """
    The value of the object's field of that name, null without one

    Args:
        field_name (str): The field

    Returns:
        dict[str, Any]: The aggregation expression
    """
    return {'$first': {'$map': {
        'input': {'$filter': {
            'input': {'$ifNull': [f'${CmdbObjectKey.FIELDS.value}', []]},
            'cond': {'$eq': [f'$$this.{CmdbObjectFieldKey.NAME.value}', field_name]},
        }},
        'in': f'$$this.{CmdbObjectFieldKey.VALUE.value}',
    }}}


def record_stages(marker: SpecialType, denied_type_ids: Iterable[int]) -> list[dict[str, Any]]:
    """
    The stages turning the objects of the marker the reader may read into records

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        denied_type_ids (Iterable[int]): The Types the reader may not READ

    Returns:
        list[dict[str, Any]]: A ``$match`` and a ``$project`` - a person's ``groups`` are added after the read
    """
    return [
        Builder.match_({
            CmdbObjectKey.SPECIAL_TYPE.value: marker.value,
            CmdbObjectKey.TYPE_ID.value: {'$nin': sorted(set(denied_type_ids))},
        }),
        Builder.project_({
            MONGO_ID: 0,
            PUBLIC_ID: 1,
            **{key: field_value_expression(field) for key, field in RECORD_FIELDS[marker].items()},
        }),
    ]


def record_of(document: dict[str, Any], marker: SpecialType) -> dict[str, Any]:
    """
    One object as a record

    Args:
        document (dict[str, Any]): The object document
        marker (SpecialType): PERSON or PERSON_GROUP

    Returns:
        dict[str, Any]: The record - a person's ``groups`` are the caller's to add
    """
    values: dict[Any, Any] = {
        entry.get(CmdbObjectFieldKey.NAME.value): entry.get(CmdbObjectFieldKey.VALUE.value)
        for entry in document.get(CmdbObjectKey.FIELDS.value) or [] if isinstance(entry, dict)
    }

    return {PUBLIC_ID: document.get(PUBLIC_ID),
            **{key: values.get(field) for key, field in RECORD_FIELDS[marker].items()}}


def field_entries(marker: SpecialType, body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The object field entries a record body sets - one per record key it carries

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        body (dict[str, Any]): The record body

    Returns:
        list[dict[str, Any]]: ``{name, value}`` entries
    """
    return [
        {CmdbObjectFieldKey.NAME.value: field, CmdbObjectFieldKey.VALUE.value: body[key]}
        for key, field in RECORD_FIELDS[marker].items() if key in body
    ]


def groups_of_persons(objects_manager: ObjectsManager, person_ids: Iterable[int],
                      denied_type_ids: Iterable[int]) -> dict[int, list[int]]:
    """
    The readable groups whose members hold each person - one projected read for all of them

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        person_ids (Iterable[int]): The persons
        denied_type_ids (Iterable[int]): The Types the reader may not READ

    Raises:
        BaseManagerGetError: When the read fails

    Returns:
        dict[int, list[int]]: The group ids per person, ascending; every person given is a key
    """
    wanted: list[int] = sorted(set(person_ids))
    groups: dict[int, list[int]] = {person_id: [] for person_id in wanted}

    if not wanted:
        return groups

    documents: list[dict[str, Any]] = objects_manager.find(
        {
            CmdbObjectKey.SPECIAL_TYPE.value: SpecialType.PERSON_GROUP.value,
            CmdbObjectKey.TYPE_ID.value: {'$nin': sorted(set(denied_type_ids))},
            **holding_members_criteria(wanted),
        },
        projection={MONGO_ID: 0, PUBLIC_ID: 1, CmdbObjectKey.FIELDS.value: 1},
    )

    for document in sorted(documents, key=lambda group: group[PUBLIC_ID]):
        members: list[int] = group_members(document)

        for person_id in wanted:
            if person_id in members:
                groups[person_id].append(document[PUBLIC_ID])

    return groups
