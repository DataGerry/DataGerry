# DATAGERRY - OpenSource Enterprise CMDB
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
Reads persons and person groups - the CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes

Everything that needs to know who a person or a group is goes through here: the person field enforcement
(does an id name an object of the kind the field allows?), the ISMS reference check, the read-only /persons
and /person_groups routes the ISMS module still reads, and the person relation routes (memberships,
members, assignments, selectable candidates).

Object ids are unique across all CmdbObjects, so an id alone names a person or a group; the 'ref_type'
stored beside it is what the kind *should* be, and the lookups here are what verify it
"""
from typing import Any, Iterable

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.utils import Builder

from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.special_type_model.person_constants import (
    PersonField,
    PersonGroupField,
    PersonRefKind,
    PersonValueKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.cmdb_type import CmdbType

from cmdb.framework.person.person_values import get_person_field_definitions, referenced_ids
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonEntry',
    'LABEL_FIELDS',
    'get_person_type_ids',
    'resolve_person_kinds',
    'object_label',
    'get_person_labels',
    'list_candidates',
    'get_member_ids',
    'get_memberships',
    'get_assignments',
    'to_legacy_person',
    'to_legacy_person_group',
    'list_person_objects',
    'person_lookup_stage',
]

PersonEntry = dict[str, Any]

# The field whose value labels an object of each person SpecialType
LABEL_FIELDS: dict[str, str] = {
    SpecialType.PERSON.value: PersonField.DISPLAY_NAME.value,
    SpecialType.PERSON_GROUP.value: PersonGroupField.NAME.value,
}

_PUBLIC_ID: str = CmdbObjectKey.PUBLIC_ID.value
_TYPE_ID: str = CmdbObjectKey.TYPE_ID.value
_FIELDS: str = CmdbObjectKey.FIELDS.value
_SUMMARY_PROJECTION: dict[str, int] = {_PUBLIC_ID: 1, _TYPE_ID: 1, _FIELDS: 1, '_id': 0}


def get_person_type_ids(types_manager: TypesManager) -> dict[str, list[int]]:
    """
    The CmdbTypes carrying each person SpecialType

    Args:
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        dict[str, list[int]]: {'PERSON': [type ids], 'PERSON_GROUP': [type ids]} - normally one id each, empty
            while the type was not created yet
    """
    return {
        special_type.value: types_manager.get_type_ids_of_special_type(special_type)
        for special_type in (SpecialType.PERSON, SpecialType.PERSON_GROUP)
    }


def _kind_of_type(type_ids: dict[str, list[int]]) -> dict[int, str]:
    """
    Inverts get_person_type_ids: the person SpecialType of each person CmdbType

    Args:
        type_ids (dict[str, list[int]]): The result of get_person_type_ids

    Returns:
        dict[int, str]: {type id: 'PERSON' | 'PERSON_GROUP'}
    """
    return {type_id: kind for kind, ids in type_ids.items() for type_id in ids}


def _kinds_for(ref_kind: str) -> list[str]:
    """
    The person SpecialTypes a PersonRefKind selects

    Args:
        ref_kind (str): A PersonRefKind value

    Returns:
        list[str]: The SpecialType tokens, PERSON before PERSON_GROUP
    """
    if ref_kind == PersonRefKind.PERSON.value:
        return [SpecialType.PERSON.value]

    if ref_kind == PersonRefKind.PERSON_GROUP.value:
        return [SpecialType.PERSON_GROUP.value]

    return [SpecialType.PERSON.value, SpecialType.PERSON_GROUP.value]


def resolve_person_kinds(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        object_ids: Iterable[int]) -> dict[int, str]:
    """
    The person SpecialType of each id that names a person or a person group

    One projected ``$in`` query, however many ids

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        object_ids (Iterable[int]): The ids to resolve

    Returns:
        dict[int, str]: {id: 'PERSON' | 'PERSON_GROUP'} for every id that names such an object; an id naming
            no object, or an object of any other type, is absent
    """
    ids: list[int] = list(set(object_ids))

    if not ids:
        return {}

    kind_of_type: dict[int, str] = _kind_of_type(get_person_type_ids(types_manager))

    if not kind_of_type:
        return {}

    return {
        document[_PUBLIC_ID]: kind_of_type[document[_TYPE_ID]]
        for document in objects_manager.find(
            {_PUBLIC_ID: {'$in': ids}, _TYPE_ID: {'$in': list(kind_of_type)}},
            projection={_PUBLIC_ID: 1, _TYPE_ID: 1, '_id': 0},
        )
    }


def get_person_labels(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        object_ids: Iterable[int]) -> dict[int, str]:
    """
    The labels of the persons and groups among the given ids, in one projected query

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        object_ids (Iterable[int]): The ids to label

    Returns:
        dict[int, str]: {id: full name or group name} for every id naming a person or group
    """
    ids: list[int] = list(set(object_ids))
    kind_of_type: dict[int, str] = _kind_of_type(get_person_type_ids(types_manager)) if ids else {}

    if not kind_of_type:
        return {}

    return {
        document[_PUBLIC_ID]: object_label(document, kind_of_type[document[_TYPE_ID]])
        for document in objects_manager.find(
            {_PUBLIC_ID: {'$in': ids}, _TYPE_ID: {'$in': list(kind_of_type)}},
            projection=_SUMMARY_PROJECTION,
        )
    }


def object_label(document: dict[str, Any], kind: str | None) -> str:
    """
    The label of a person or group object - its full name or group name, '#<id>' when that is empty

    Args:
        document (dict[str, Any]): The object document (at least public_id and fields)
        kind (str | None): Its person SpecialType, None for any other object

    Returns:
        str: The label
    """
    label: Any = extract_field_value(document, LABEL_FIELDS[kind]) if kind in LABEL_FIELDS else None

    if isinstance(label, str) and label.strip():
        return label

    return f"#{document.get(_PUBLIC_ID)}"


def _entry(document: dict[str, Any], kind: str) -> PersonEntry:
    """
    One person or group as the relation routes answer it

    Args:
        document (dict[str, Any]): The object document
        kind (str): Its person SpecialType

    Returns:
        PersonEntry: {'ref_type', 'id', 'label', 'type_id'}
    """
    return {
        PersonValueKey.REF_TYPE.value: kind,
        PersonValueKey.ID.value: document[_PUBLIC_ID],
        'label': object_label(document, kind),
        'type_id': document[_TYPE_ID],
    }


def _sorted_entries(entries: list[PersonEntry]) -> list[PersonEntry]:
    return sorted(entries, key=lambda entry: (entry['label'].casefold(), entry[PersonValueKey.ID.value]))


def list_person_objects(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        kind: str,
        denied_type_ids: Iterable[int] = ()) -> list[dict[str, Any]]:
    """
    Every object of one person SpecialType, as projected documents

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        kind (str): 'PERSON' or 'PERSON_GROUP'
        denied_type_ids (Iterable[int]): CmdbTypes the caller may not read; their objects are left out

    Returns:
        list[dict[str, Any]]: The documents (public_id, type_id, fields), unsorted
    """
    denied: set[int] = set(denied_type_ids)
    type_ids: list[int] = [type_id for type_id in get_person_type_ids(types_manager)[kind] if type_id not in denied]

    if not type_ids:
        return []

    return objects_manager.find({_TYPE_ID: {'$in': type_ids}}, projection=_SUMMARY_PROJECTION)


def list_candidates(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        ref_kind: str,
        denied_type_ids: Iterable[int] = ()) -> list[PersonEntry]:
    """
    The objects a person field of the given kind may select, sorted by label

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        ref_kind (str): A PersonRefKind value
        denied_type_ids (Iterable[int]): CmdbTypes the caller may not read; their objects are left out

    Returns:
        list[PersonEntry]: One entry per selectable person or group
    """
    denied: list[int] = list(denied_type_ids)
    entries: list[PersonEntry] = []

    for kind in _kinds_for(ref_kind):
        entries.extend(_entry(document, kind) for document in list_person_objects(objects_manager, types_manager, kind, denied))

    return _sorted_entries(entries)


def get_member_ids(group_document: dict[str, Any]) -> list[int]:
    """
    The person ids a group object lists in its MEMBERS field

    Args:
        group_document (dict[str, Any]): A PERSON_GROUP object document

    Returns:
        list[int]: The member ids, in stored order
    """
    return [
        object_id for ref_type, object_id in referenced_ids(
            extract_field_value(group_document, PersonGroupField.MEMBERS.value)
        )
        if ref_type == SpecialType.PERSON.value
    ]


def _members_filter(person_id: int) -> dict[str, Any]:
    """
    Matches a group object whose MEMBERS field lists the person

    Args:
        person_id (int): public_id of the person

    Returns:
        dict[str, Any]: The 'fields' element match
    """
    return {
        _FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME.value: PersonGroupField.MEMBERS.value,
                f'{CmdbObjectFieldKey.VALUE.value}.{PersonValueKey.ID.value}': person_id,
            }
        }
    }


def get_memberships(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        person_id: int,
        denied_type_ids: Iterable[int] = ()) -> list[PersonEntry]:
    """
    The groups a person is a member of, sorted by label

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        person_id (int): public_id of the person
        denied_type_ids (Iterable[int]): CmdbTypes the caller may not read; their objects are left out

    Returns:
        list[PersonEntry]: One entry per group listing the person
    """
    denied: set[int] = set(denied_type_ids)
    group_type_ids: list[int] = [
        type_id for type_id in get_person_type_ids(types_manager)[SpecialType.PERSON_GROUP.value]
        if type_id not in denied
    ]

    if not group_type_ids:
        return []

    documents: list[dict[str, Any]] = objects_manager.find(
        {_TYPE_ID: {'$in': group_type_ids}, **_members_filter(person_id)},
        projection=_SUMMARY_PROJECTION,
    )

    return _sorted_entries([_entry(document, SpecialType.PERSON_GROUP.value) for document in documents])


def get_assignments(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        referenced_id: int,
        denied_type_ids: Iterable[int] = ()) -> list[dict[str, Any]]:
    """
    The objects whose person fields select the given person or group

    A group's MEMBERS field is a membership, not an assignment, and is left out. Only the top-level fields
    are read; a person field inside a multi-data-section row counts towards its object as well

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        referenced_id (int): public_id of the person or group
        denied_type_ids (Iterable[int]): CmdbTypes the caller may not read; their objects are left out

    Returns:
        list[dict[str, Any]]: {'object_id', 'type_id', 'type_label', 'label', 'field_name', 'field_label'} per
            selecting field, sorted by type label, object label and field label
    """
    value_id_key: str = f'{CmdbObjectFieldKey.VALUE.value}.{PersonValueKey.ID.value}'
    row_match: dict[str, Any] = {CmdbObjectFieldKey.TYPE.value: FieldType.PERSON.value, value_id_key: referenced_id}

    denied: set[int] = set(denied_type_ids)
    documents: list[dict[str, Any]] = objects_manager.find(
        {'$or': [
            {_FIELDS: {'$elemMatch': row_match}},
            {'multi_data_sections.values.data': {'$elemMatch': row_match}},
        ]},
        projection={_PUBLIC_ID: 1, _TYPE_ID: 1, _FIELDS: 1, 'multi_data_sections': 1, '_id': 0},
    )
    documents = [document for document in documents if document[_TYPE_ID] not in denied]

    if not documents:
        return []

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(list({document[_TYPE_ID] for document in documents}))
    kind_of_type: dict[int, str] = _kind_of_type(get_person_type_ids(types_manager))
    assignments: list[dict[str, Any]] = []

    for document in documents:
        object_type: CmdbType | None = types_lookup.get(document[_TYPE_ID])

        if object_type is None:
            continue

        kind: str | None = kind_of_type.get(document[_TYPE_ID])
        person_fields: dict[str, dict[str, Any]] = get_person_field_definitions(object_type.get_fields())
        summary_label: str = _object_summary(document, object_type, kind)

        for field_name, definition in person_fields.items():
            if kind == SpecialType.PERSON_GROUP.value and field_name == PersonGroupField.MEMBERS.value:
                continue

            if not _field_selects(document, field_name, referenced_id):
                continue

            assignments.append({
                'object_id': document[_PUBLIC_ID],
                'type_id': document[_TYPE_ID],
                'type_label': object_type.get_label(),
                'label': summary_label,
                'field_name': field_name,
                'field_label': definition.get(FieldKey.LABEL.value) or field_name,
            })

    return sorted(assignments, key=lambda row: (
        str(row['type_label']).casefold(), row['label'].casefold(), str(row['field_label']).casefold(),
    ))


def _field_selects(document: dict[str, Any], field_name: str, referenced_id: int) -> bool:
    """
    Whether a named person field of an object - top-level or in any MDS row - selects the id

    Args:
        document (dict[str, Any]): The object document, with fields and multi_data_sections
        field_name (str): The person field's name
        referenced_id (int): public_id of the person or group

    Returns:
        bool: True when any entry of that name selects it
    """
    entries: list[Any] = list(document.get(_FIELDS) or [])

    for section in document.get('multi_data_sections') or []:
        for row in (section or {}).get('values') or []:
            entries.extend((row or {}).get('data') or [])

    return any(
        isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) == field_name
        and any(object_id == referenced_id for _, object_id in referenced_ids(entry.get(CmdbObjectFieldKey.VALUE.value)))
        for entry in entries
    )


def _object_summary(document: dict[str, Any], object_type: CmdbType, kind: str | None) -> str:
    """
    A short label of any object: a person's or group's label, else the values of its type's summary fields

    Args:
        document (dict[str, Any]): The object document
        object_type (CmdbType): Its CmdbType
        kind (str | None): Its person SpecialType, None for any other object

    Returns:
        str: The label, '#<id>' when no summary value is set
    """
    if kind is not None:
        return object_label(document, kind)

    values: list[str] = [
        str(value) for value in (extract_field_value(document, name) for name in object_type.render_meta.summary.fields)
        if value not in (None, '', [])
    ]

    return ' | '.join(values) if values else f"#{document.get(_PUBLIC_ID)}"


def to_legacy_person(document: dict[str, Any], group_ids: list[int]) -> dict[str, Any]:
    """
    A PERSON object in the shape the former ``management.person`` documents had

    The ISMS module still reads persons through GET /persons in that shape

    Args:
        document (dict[str, Any]): The PERSON object document
        group_ids (list[int]): The groups listing the person

    Returns:
        dict[str, Any]: {'public_id', 'display_name', 'first_name', 'last_name', 'phone_number', 'email',
            'groups'}
    """
    def text(field: PersonField) -> str:
        value: Any = extract_field_value(document, field.value)

        return value if isinstance(value, str) else ''

    return {
        'public_id': document[_PUBLIC_ID],
        'display_name': object_label(document, SpecialType.PERSON.value),
        'first_name': text(PersonField.FIRST_NAME),
        'last_name': text(PersonField.LAST_NAME),
        'phone_number': text(PersonField.PHONE_NUMBER),
        'email': text(PersonField.EMAIL),
        'groups': group_ids,
    }


def to_legacy_person_group(document: dict[str, Any]) -> dict[str, Any]:
    """
    A PERSON_GROUP object in the shape the former ``management.personGroup`` documents had

    Args:
        document (dict[str, Any]): The PERSON_GROUP object document

    Returns:
        dict[str, Any]: {'public_id', 'name', 'email', 'group_members'}
    """
    email: Any = extract_field_value(document, PersonGroupField.EMAIL.value)

    return {
        'public_id': document[_PUBLIC_ID],
        'name': object_label(document, SpecialType.PERSON_GROUP.value),
        'email': email if isinstance(email, str) else '',
        'group_members': get_member_ids(document),
    }


def _field_value_expression(field_name: str) -> dict[str, Any]:
    """
    An aggregation expression reading one field's value of the current object document

    Args:
        field_name (str): The field's name

    Returns:
        dict[str, Any]: The value of the first 'fields' entry of that name, missing when there is none
    """
    return {
        '$let': {
            'vars': {
                'entry': {
                    '$arrayElemAt': [
                        {'$filter': {'input': f'${_FIELDS}', 'cond': {'$eq': ['$$this.name', field_name]}}},
                        0,
                    ]
                }
            },
            'in': '$$entry.value',
        }
    }


def person_lookup_stage(local_field: str, as_field: str) -> dict[str, Any]:
    """
    A ``$lookup`` joining person or group objects in the shape of the former person documents

    The ISMS reports join a reference field and read ``display_name`` (a person) or ``name`` (a group) of the
    joined document. Persons and groups are CmdbObjects, so the join goes to the object collection and projects
    both keys from the label fields. Object ids are unique, so the same stage serves a person-only, a
    group-only and a polymorphic reference - the report picks the alias by '_ref_type' as before. A list-valued
    local field (the interviewed persons) joins every listed id

    Args:
        local_field (str): The reference field of the joined document
        as_field (str): The alias the matches are added under

    Returns:
        dict[str, Any]: The ``$lookup`` stage
    """
    return Builder.lookup_(
        CmdbObject.COLLECTION,
        local_field,
        _PUBLIC_ID,
        as_field,
        pipeline=[{
            '$project': {
                '_id': 0,
                _PUBLIC_ID: 1,
                'display_name': _field_value_expression(PersonField.DISPLAY_NAME.value),
                'name': _field_value_expression(PersonGroupField.NAME.value),
            }
        }],
    )
