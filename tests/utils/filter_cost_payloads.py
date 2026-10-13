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
Client ``?filter=`` payloads shared by the guard's unit, functional and integration tests

Two kinds: the payloads that made one document cost more than the query's whole time budget, each with what its
refusal names, and a transcription of the frontend's largest object search - the filter the guard's caps are
measured against, which every tier has to keep accepting
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FIFTY_FIELDS',
    'nested_map',
    'let_doubling',
    'MEASURED_PAYLOADS',
    'FRONTEND_OBJECTS_BY_TYPE_SEARCH',
]

FIFTY_FIELDS: str = '$fields'


def nested_map(depth: int) -> dict[str, Any]:
    """
    `$map` nested `depth` deep over the stored fields - 50**depth evaluations per document

    Built from allow-listed operators only (the measured one summed with `$sum` / `$add`), so what refuses
    it is the nesting rule and not the operator list
    """
    expression: Any = {'$toString': f'$$v{depth}.value'}

    for level in range(depth, 0, -1):
        expression = {'$size': {'$map': {'input': FIFTY_FIELDS, 'as': f'v{level}', 'in': expression}}}

    return expression


def let_doubling(times: int) -> dict[str, Any]:
    """`$let` + `$concatArrays` doubling the fields `times` times inside one expression"""
    expression: Any = {'$size': f'$$a{times}'}

    for level in range(times, 0, -1):
        previous: str = FIFTY_FIELDS if level == 1 else f'$$a{level - 1}'
        expression = {'$let': {'vars': {f'a{level}': {'$concatArrays': [previous, previous]}}, 'in': expression}}

    return expression


#: Each of these passed the guard and ran past the 10 s budget, or would have exhausted mongod's memory
#: first, on three object-shaped documents (MongoDB 7.0.34). Each is paired with what its refusal names
MEASURED_PAYLOADS: list[tuple[str, list[dict[str, Any]], str]] = [
    ('$map nested five deep - 104 s', [{'$addFields': {'x': nested_map(5)}}], 'inside the'),
    ('$let doubling twenty times', [{'$addFields': {'x': let_doubling(20)}}], r'\$let'),
    ('twenty stages each doubling the last', [
        {'$addFields': {'fields': {'$concatArrays': [FIFTY_FIELDS, FIFTY_FIELDS]}}} for _ in range(20)
    ], 'at most'),
    ('$reduce doubling its running value', [{'$addFields': {'x': {'$reduce': {
        'input': FIFTY_FIELDS, 'initialValue': [1], 'in': {'$concatArrays': ['$$value', '$$value']},
    }}}}], 'only once'),
    ('$range burn - the first reproduction', [{'$addFields': {'x': {'$reduce': {
        'input': {'$range': [0, 5000000]}, 'initialValue': 0, 'in': {'$add': ['$$value', '$$this']},
    }}}}], r'\$range'),
]


#: `objects-by-type.component.ts` - the type-scoped object table's search: the reference join of
#: `referenceFieldQuery`, the date-to-string `$map` of `dateFieldValuesQuery` and the column `$or`. It holds
#: the most array-building operators of any frontend filter (four), which is what the cap is measured against
FRONTEND_OBJECTS_BY_TYPE_SEARCH: list[dict[str, Any]] = [
    {'$match': {'type_id': 7}},
    {'$lookup': {'from': 'framework.objects', 'localField': 'fields.value',
                 'foreignField': 'public_id', 'as': 'data'}},
    {'$project': {'_id': 1, 'public_id': 1, 'type_id': 1, 'active': 1, 'author_id': 1,
                  'creation_time': 1, 'last_edit_time': 1, 'fields': 1,
                  'simple': {'$reduce': {'input': '$data.fields', 'initialValue': [],
                                         'in': {'$setUnion': ['$$value', '$$this']}}}}},
    {'$group': {'_id': '$_id', 'public_id': {'$first': '$public_id'}, 'type_id': {'$first': '$type_id'},
                'fields': {'$first': '$fields'}, 'simple': {'$first': '$simple'}}},
    {'$project': {'_id': '$_id', 'public_id': 1, 'type_id': 1, 'fields': 1,
                  'references': {'$concatArrays': ['$fields', '$simple']}}},
    {'$addFields': {'creationString': {'$dateToString': {'format': '%Y-%m-%dT%H:%M:%S.%LZ',
                                                         'date': '$creation_time'}}}},
    {'$addFields': {'references': {'$map': {
        'input': '$references',
        'as': 'new_fields',
        'in': {'$cond': [
            {'$eq': [{'$type': '$$new_fields.value'}, 'date']},
            {'name': '$$new_fields.name',
             'value': {'$dateToString': {'format': '%Y-%m-%dT%H:%M:%S.%LZ', 'date': '$$new_fields.value'}}},
            {'name': '$$new_fields.name', 'value': '$$new_fields.value'},
        ]},
    }}}},
    {'$addFields': {'public_id': {'$toString': '$public_id'}}},
    {'$match': {'$or': [{'public_id': {'$regex': 'abc', '$options': 'ismx'}},
                        {'references': {'$elemMatch': {'value': {'$regex': 'abc', '$options': 'ismx'}}}},
                        {'fields.value': 42}]}},
]
