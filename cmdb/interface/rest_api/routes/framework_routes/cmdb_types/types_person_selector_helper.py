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
Narrowing a person selector (``FieldType.PERSON``) of a CmdbType - refused while Objects hold what it would not allow

A person selector narrows in two ways: from several objects to one (``multiple`` true to false), and by no longer
selecting a kind (a marker leaves ``selectable``). Both are refused with a 400 while an Object of the Type - in its
flat fields or in any multi-data row - holds what the narrowed selector would not allow: more than one object, or an
object of a type carrying the dropped marker. Widening is always allowed. The type update and the type import update
ask the same blocker (``person_selector_narrowing_blocker``), and the pre-check route answers the usage it is decided
by (``build_person_field_usage_payload``), so the type builder can tell before saving.

One aggregation per narrowed field reads the usage: the selected values of every Object of the Type, the Objects
holding several (the first ``PERSON_SELECTOR_OBJECT_ID_LIMIT``) and the types of the selected objects, joined in
the database; the markers of those types are one more projected read
"""
from dataclasses import dataclass
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.person_selector_rules import is_multiple, is_person_selector, selectable_kinds
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.utils import Builder
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    PERSON_SELECTOR_KIND_MESSAGE,
    PERSON_SELECTOR_NOT_DECLARED_MESSAGE,
    PERSON_SELECTOR_OBJECT_ID_LIMIT,
    PERSON_SELECTOR_SINGLE_MESSAGE,
    PersonFieldUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Names the usage aggregation gives its intermediate values
SELECTED: str = 'selected'
SELECTED_IDS: str = 'selected_ids'
SEVERAL: str = 'several'
SELECTED_TYPES: str = 'selected_types'
JOINED_OBJECT: str = 'joined_object'
MONGO_ID: str = '_id'


@dataclass(frozen=True)
class SelectorNarrowing:
    """One person selector an update narrows: to one object, and / or by the kinds it no longer selects"""
    name: str
    becomes_single: bool
    dropped_kinds: list[str]


@dataclass(frozen=True)
class PersonFieldUsage:
    """What the Objects of a Type hold in one person selector"""
    objects_with_several: list[int]
    kinds_used: list[str]


def person_selector_narrowings(old_fields: list[dict[str, Any]], new_fields: list[dict[str, Any]]) -> list[
        SelectorNarrowing]:
    """
    The person selectors both versions declare that the new version narrows

    A field that is no person selector on either side is not judged here - a removed field or a changed kind loses
    its values by the type alignment, as for every other kind

    Args:
        old_fields (list[dict[str, Any]]): The stored field definitions
        new_fields (list[dict[str, Any]]): The field definitions the update writes

    Returns:
        list[SelectorNarrowing]: The narrowed selectors, in the new version's order
    """
    stored: dict[Any, dict[str, Any]] = {
        field.get(FieldKey.NAME.value): field for field in old_fields if is_person_selector(field)
    }
    narrowings: list[SelectorNarrowing] = []

    for field in new_fields:
        old: dict[str, Any] | None = stored.get(field.get(FieldKey.NAME.value)) if is_person_selector(field) else None

        if old is None:
            continue

        becomes_single: bool = is_multiple(old) and not is_multiple(field)
        dropped: list[str] = [kind for kind in selectable_kinds(old) if kind not in selectable_kinds(field)]

        if becomes_single or dropped:
            narrowings.append(SelectorNarrowing(field[FieldKey.NAME.value], becomes_single, dropped))

    return narrowings


def selected_values_expression(field_name: str) -> dict[str, Any]:
    """
    Every value an Object holds in one field: its flat entry and the entry in each row of each multi-data section

    Args:
        field_name (str): The field's name

    Returns:
        dict[str, Any]: An aggregation expression answering the list of values
    """
    def values_of(entries: str, variable: str) -> dict[str, Any]:
        return {'$map': {
            'input': {'$filter': {
                'input': {'$ifNull': [entries, []]}, 'as': variable,
                'cond': {'$eq': [f'$${variable}.{CmdbObjectFieldKey.NAME.value}', {'$literal': field_name}]},
            }},
            'as': variable, 'in': f'$${variable}.{CmdbObjectFieldKey.VALUE.value}',
        }}

    rows_values: dict[str, Any] = {'$reduce': {
        'input': {'$ifNull': [f'$$this.{CmdbObjectMdsKey.VALUES.value}', []]}, 'initialValue': [],
        'in': {'$concatArrays': ['$$value', values_of(f'$$this.{CmdbObjectMdsRowKey.DATA.value}', 'entry')]},
    }}

    return {'$concatArrays': [
        values_of(f'${CmdbObjectKey.FIELDS.value}', 'field'),
        {'$reduce': {
            'input': {'$ifNull': [f'${CmdbObjectKey.MULTI_DATA_SECTIONS.value}', []]}, 'initialValue': [],
            'in': {'$concatArrays': ['$$value', rows_values]},
        }},
    ]}


def build_person_field_usage_pipeline(type_id: int, field_name: str) -> list[dict[str, Any]]:
    """
    The aggregation reading what the Objects of a Type hold in one person selector

    Answers one document: ``several`` - the first Objects (by public_id) holding more than one object -, and
    ``selected_types`` - the distinct types of the selected objects, joined from ``framework.objects``. An id that no
    longer resolves joins nothing

    Args:
        type_id (int): public_id of the CmdbType
        field_name (str): The person selector's name

    Returns:
        list[dict[str, Any]]: The pipeline
    """
    holds_several: dict[str, Any] = {'$anyElementTrue': [{'$map': {
        'input': f'${SELECTED}', 'as': 'value',
        'in': {'$gt': [{'$size': {'$cond': [{'$isArray': '$$value'}, '$$value', []]}}, 1]},
    }}]}
    flattened: dict[str, Any] = {'$reduce': {
        'input': f'${SELECTED}', 'initialValue': [],
        'in': {'$concatArrays': ['$$value', {'$cond': [
            {'$isArray': '$$this'},
            '$$this',
            {'$cond': [{'$eq': [{'$ifNull': ['$$this', None]}, None]}, [], ['$$this']]},
        ]}]},
    }}

    return [
        Builder.match_({CmdbObjectKey.TYPE_ID.value: type_id}),
        Builder.project_({CmdbObjectKey.PUBLIC_ID.value: 1, SELECTED: selected_values_expression(field_name)}),
        Builder.facet_({
            SEVERAL: [
                Builder.match_({'$expr': holds_several}),
                Builder.sort_(CmdbObjectKey.PUBLIC_ID.value, 1),
                Builder.limit_(PERSON_SELECTOR_OBJECT_ID_LIMIT),
                Builder.project_({MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1}),
            ],
            SELECTED_TYPES: [
                Builder.project_({SELECTED_IDS: flattened}),
                Builder.unwind_(f'${SELECTED_IDS}'),
                Builder.group_(f'${SELECTED_IDS}'),
                Builder.lookup_(CmdbObject.COLLECTION, MONGO_ID, CmdbObjectKey.PUBLIC_ID.value, JOINED_OBJECT,
                                pipeline=[Builder.project_({MONGO_ID: 0, CmdbObjectKey.TYPE_ID.value: 1})]),
                Builder.unwind_(f'${JOINED_OBJECT}'),
                Builder.group_(f'${JOINED_OBJECT}.{CmdbObjectKey.TYPE_ID.value}'),
            ],
        }),
    ]


def read_person_field_usage(request_user: CmdbUser, type_id: int, field_name: str) -> PersonFieldUsage:
    """
    Reads what the Objects of a Type hold in one person selector

    Args:
        request_user (CmdbUser): User performing the request
        type_id (int): public_id of the CmdbType
        field_name (str): The person selector's name

    Raises:
        BaseManagerIterationError: When the aggregation fails
        BaseManagerGetError: When the types of the selected objects could not be read

    Returns:
        PersonFieldUsage: The Objects holding several (the first few) and the markers of the selected objects
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    result: list[dict[str, Any]] = objects_manager.aggregate_all(
        build_person_field_usage_pipeline(type_id, field_name),
    )
    usage: dict[str, Any] = result[0] if result else {}
    type_ids: list[Any] = [
        entry[MONGO_ID] for entry in usage.get(SELECTED_TYPES, []) if entry.get(MONGO_ID) is not None
    ]

    markers: set[str] = {
        document[TypeSchemaKey.SPECIAL_TYPE.value]
        for document in (types_manager.find(
            {TypeSchemaKey.PUBLIC_ID.value: {'$in': type_ids}},
            projection={MONGO_ID: 0, TypeSchemaKey.SPECIAL_TYPE.value: 1},
        ) if type_ids else [])
        if document.get(TypeSchemaKey.SPECIAL_TYPE.value)
    }

    return PersonFieldUsage(
        objects_with_several=[entry[CmdbObjectKey.PUBLIC_ID.value] for entry in usage.get(SEVERAL, [])],
        kinds_used=sorted(markers),
    )


def person_selector_narrowing_blocker(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> str | None:
    """
    Reports why an update may not narrow a person selector, if it may not

    Reads nothing when the update narrows no selector

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The refusal naming the first refused selector, or None when the update may be written
    """
    for narrowing in person_selector_narrowings(old_type.get_fields(), new_type.get_fields()):
        usage: PersonFieldUsage = read_person_field_usage(request_user, old_type.public_id, narrowing.name)

        if narrowing.becomes_single and usage.objects_with_several:
            return PERSON_SELECTOR_SINGLE_MESSAGE.format(name=narrowing.name, object_ids=usage.objects_with_several)

        refused_kinds: list[str] = sorted(set(narrowing.dropped_kinds) & set(usage.kinds_used))

        if refused_kinds:
            return PERSON_SELECTOR_KIND_MESSAGE.format(name=narrowing.name, kinds=refused_kinds)

    return None


def guard_person_selector_narrowing(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update narrows a person selector while Objects hold what it would no longer allow

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 naming the refused selector
    """
    blocker: str | None = person_selector_narrowing_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def build_person_field_usage_payload(request_user: CmdbUser, target_type: CmdbType, field_name: str) -> dict[str, Any]:
    """
    Builds the "may this person selector be narrowed" pre-check payload

    ``objects_with_several`` empty means it may hold only one object; a kind missing from ``kinds_used`` may leave
    ``selectable``

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect
        field_name (str): The person selector's name

    Raises:
        HTTPException: 404 when the Type declares no person selector of that name

    Returns:
        dict[str, Any]: ``{objects_with_several: [public_id, ...], kinds_used: [marker, ...]}``
    """
    if not any(is_person_selector(field) and field.get(FieldKey.NAME.value) == field_name
               for field in target_type.get_fields()):
        abort(404, PERSON_SELECTOR_NOT_DECLARED_MESSAGE.format(public_id=target_type.public_id, name=field_name))

    usage: PersonFieldUsage = read_person_field_usage(request_user, target_type.public_id, field_name)

    return {
        PersonFieldUsageKey.OBJECTS_WITH_SEVERAL.value: usage.objects_with_several,
        PersonFieldUsageKey.KINDS_USED.value: usage.kinds_used,
    }
