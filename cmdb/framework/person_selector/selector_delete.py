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
What deleting CmdbObjects does to the person selectors that hold them

**Refused while a required selector would be left empty** (``find_required_selector_blockers``): an object outside the
deleted selection whose required person selector - flat, or in a multi-data row - holds deleted objects and nothing
else would be left without the value its type requires. A cascade never empties a required value.

**Otherwise every selector lets go of the deleted ids** (``scrub_person_selectors``): a selector holding several drops
them from its list, one holding one becomes None - flat and in every row, in one pipeline ``update_many``. Both read
only the objects of the types that declare a selector (the types are found in one projected read), so a delete in an
installation without selectors reads no object
"""
from typing import Any

from cmdb.utils import Builder
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.objects_propagation_helper import RawUpdate, map_if_array
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_selector_scrub_update',
    'find_required_selector_blockers',
    'scrub_person_selectors',
    'selector_type_ids',
]

MONGO_ID: str = '_id'
# How many blocking objects the guard reads at most - enough to name the first few and count
BLOCKER_READ_LIMIT: int = 200
PERSON_KIND: str = FieldType.PERSON.value
ROWS_DATA_PATH: str = (f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}.'
                       f'{CmdbObjectMdsRowKey.DATA.value}')


def selector_type_ids(types_manager: TypesManager) -> list[int]:
    """
    The types that declare a person selector

    Raises:
        BaseManagerGetError: When the read fails

    Returns:
        list[int]: Their public_ids
    """
    return [
        document[TypeSchemaKey.PUBLIC_ID.value]
        for document in types_manager.find(
            {f'{TypeSchemaKey.FIELDS.value}.{FieldKey.TYPE.value}': PERSON_KIND},
            projection={MONGO_ID: 0, TypeSchemaKey.PUBLIC_ID.value: 1},
        )
    ]


def _holds_any(ids: list[int]) -> dict[str, Any]:
    """The element match of a selector entry holding one of the ids"""
    return {'$elemMatch': {CmdbObjectFieldKey.TYPE.value: PERSON_KIND, CmdbObjectFieldKey.VALUE.value: {'$in': ids}}}


def build_selector_scrub_update(type_ids: list[int], deleted_ids: list[int]) -> RawUpdate:
    """
    The update letting every selector of the given types' objects go of the deleted ids

    Args:
        type_ids (list[int]): The types declaring a person selector
        deleted_ids (list[int]): The deleted objects

    Returns:
        RawUpdate: One pipeline ``update_many``, matching only the objects holding a deleted id
    """
    deleted: dict[str, Any] = {'$literal': sorted(deleted_ids)}

    def scrubbed(variable: str) -> dict[str, Any]:
        entry: str = f'$${variable}'
        value: str = f'{entry}.{CmdbObjectFieldKey.VALUE.value}'

        return {'$cond': [
            {'$eq': [f'{entry}.{CmdbObjectFieldKey.TYPE.value}', PERSON_KIND]},
            {'$mergeObjects': [entry, {CmdbObjectFieldKey.VALUE.value: {'$cond': [
                {'$isArray': value},
                {'$filter': {'input': value, 'as': 'id', 'cond': {'$not': [{'$in': ['$$id', deleted]}]}}},
                {'$cond': [{'$in': [{'$ifNull': [value, None]}, deleted]}, None, value]},
            ]}}]},
            entry,
        ]}

    rows: dict[str, Any] = map_if_array(f'$$section.{CmdbObjectMdsKey.VALUES.value}', 'row', {'$mergeObjects': [
        '$$row', {CmdbObjectMdsRowKey.DATA.value: map_if_array(f'$$row.{CmdbObjectMdsRowKey.DATA.value}', 'entry',
                                                               scrubbed('entry'))},
    ]})

    return RawUpdate(
        filter_query={
            CmdbObjectKey.TYPE_ID.value: {'$in': sorted(type_ids)},
            '$or': [{CmdbObjectKey.FIELDS.value: _holds_any(sorted(deleted_ids))},
                    {ROWS_DATA_PATH: _holds_any(sorted(deleted_ids))}],
        },
        update=[Builder.set_({
            CmdbObjectKey.FIELDS.value: map_if_array(f'${CmdbObjectKey.FIELDS.value}', 'field', scrubbed('field')),
            CmdbObjectKey.MULTI_DATA_SECTIONS.value: map_if_array(
                f'${CmdbObjectKey.MULTI_DATA_SECTIONS.value}', 'section',
                {'$mergeObjects': ['$$section', {CmdbObjectMdsKey.VALUES.value: rows}]},
            ),
        })],
    )


def scrub_person_selectors(objects_manager: ObjectsManager, types_manager: TypesManager,
                           deleted_ids: list[int]) -> None:
    """
    Lets every person selector go of the deleted objects

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        deleted_ids (list[int]): The deleted objects

    Raises:
        BaseManagerGetError: When the types could not be read
        ObjectsManagerUpdateError: When the update fails
    """
    if not deleted_ids:
        return

    type_ids: list[int] = selector_type_ids(types_manager)

    if type_ids:
        objects_manager.apply_raw_updates([build_selector_scrub_update(type_ids, deleted_ids)])


def _left_empty(entries: str, names: list[str], deleted: dict[str, Any]) -> dict[str, Any]:
    """
    Whether one of the entries is a required selector holding deleted ids and nothing else

    Args:
        entries (str): The ``$`` / ``$$`` path of a list of field entries
        names (list[str]): The required selector names of the type
        deleted (dict[str, Any]): The deleted ids as a ``$literal``

    Returns:
        dict[str, Any]: The aggregation expression
    """
    value: str = f'$$entry.{CmdbObjectFieldKey.VALUE.value}'
    ids: dict[str, Any] = {'$cond': [{'$isArray': value}, value,
                                     {'$cond': [{'$eq': [{'$ifNull': [value, None]}, None]}, [], [value]]}]}

    return {'$anyElementTrue': [{'$map': {'input': {'$ifNull': [entries, []]}, 'as': 'entry', 'in': {'$and': [
        {'$in': [f'$$entry.{CmdbObjectFieldKey.NAME.value}', {'$literal': names}]},
        {'$gt': [{'$size': ids}, 0]},
        {'$eq': [{'$size': {'$setDifference': [ids, deleted]}}, 0]},
    ]}}}]}


def find_required_selector_blockers(objects_manager: ObjectsManager, types_manager: TypesManager,
                                    deleted_ids: list[int]) -> list[tuple[int, int]]:
    """
    The objects outside the deletion whose required person selector holds deleted objects and nothing else

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        deleted_ids (list[int]): The objects about to be deleted

    Raises:
        BaseManagerGetError: When the types could not be read
        BaseManagerIterationError: When the objects could not be read

    Returns:
        list[tuple[int, int]]: (public_id, type_id) of the first ``BLOCKER_READ_LIMIT`` blocking objects
    """
    if not deleted_ids:
        return []

    required_by_type: dict[int, list[str]] = {}

    for document in types_manager.find(
            {TypeSchemaKey.FIELDS.value: {'$elemMatch': {
                FieldKey.TYPE.value: PERSON_KIND, FieldKey.REQUIRED.value: True,
            }}},
            projection={MONGO_ID: 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1}):
        required_by_type[document[TypeSchemaKey.PUBLIC_ID.value]] = [
            field[FieldKey.NAME.value] for field in document.get(TypeSchemaKey.FIELDS.value) or []
            if field.get(FieldKey.TYPE.value) == PERSON_KIND and field.get(FieldKey.REQUIRED.value) is True
        ]

    if not required_by_type:
        return []

    deleted: dict[str, Any] = {'$literal': sorted(deleted_ids)}
    rows_entries: dict[str, Any] = {'$reduce': {
        'input': {'$ifNull': [f'${CmdbObjectKey.MULTI_DATA_SECTIONS.value}', []]}, 'initialValue': [],
        'in': {'$concatArrays': ['$$value', {'$reduce': {
            'input': {'$ifNull': [f'$$this.{CmdbObjectMdsKey.VALUES.value}', []]}, 'initialValue': [],
            'in': {'$concatArrays': ['$$value', {'$ifNull': [f'$$this.{CmdbObjectMdsRowKey.DATA.value}', []]}]},
        }}]},
    }}
    per_type: list[dict[str, Any]] = [
        {'$and': [{'$eq': [f'${CmdbObjectKey.TYPE_ID.value}', type_id]}, {'$or': [
            _left_empty(f'${CmdbObjectKey.FIELDS.value}', names, deleted), _left_empty(rows_entries, names, deleted),
        ]}]}
        for type_id, names in required_by_type.items()
    ]

    blockers: list[dict[str, Any]] = objects_manager.aggregate_all([
        Builder.match_({
            CmdbObjectKey.TYPE_ID.value: {'$in': sorted(required_by_type)},
            CmdbObjectKey.PUBLIC_ID.value: {'$nin': sorted(deleted_ids)},
            '$or': [{CmdbObjectKey.FIELDS.value: _holds_any(sorted(deleted_ids))},
                    {ROWS_DATA_PATH: _holds_any(sorted(deleted_ids))}],
        }),
        Builder.match_({'$expr': {'$or': per_type}}),
        Builder.sort_(CmdbObjectKey.PUBLIC_ID.value, 1),
        Builder.limit_(BLOCKER_READ_LIMIT),
        Builder.project_({MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1}),
    ])

    return [(document[CmdbObjectKey.PUBLIC_ID.value], document[CmdbObjectKey.TYPE_ID.value]) for document in blockers]
