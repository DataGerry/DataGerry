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
Integration tests: the in-memory matcher answers exactly as MongoDB (phase 9 step 8, ruled R21)

A scratch collection holds objects covering the shapes that matter - typed, mistyped (a number as text, T583), empty
(null, '', []), missing entries, lists, dates, scope blocks (phase 10) - and every condition the compiler can emit (each
operator per kind, negations, dates absolute and relative, tokens, within, in_network) is compiled and asked of both
MongoDB and ``document_matches``. They must pick the same objects, object by object
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.scope_compiler import (
    MULTIPLE_PERSON_KIND,
    ScopeContext,
    ScopeField,
    compile_scope,
    document_matches,
)
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH: str = 'scope-matcher.objects'
NOW: datetime = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
FIELDS: dict[str, ScopeField] = {
    'host': ScopeField('text'), 'size': ScopeField('number'), 'seen': ScopeField('date'),
    'on': ScopeField('checkbox'), 'state': ScopeField('select', frozenset({'a', 'b'})), 'ref': ScopeField('ref'),
    'owner': ScopeField('person', selectable=frozenset({'PERSON'})),
    'team': ScopeField(MULTIPLE_PERSON_KIND, selectable=frozenset({'PERSON_GROUP'})),
}
CONTEXT: ScopeContext = ScopeContext(person_ids=(70,), group_ids=(80, 81))
# The materialised scope blocks: 2 and 3 placed below location 1, 6 in subnet 500 of supernet 5, 7 with an IPv6 address
BLOCKS: dict[int, dict[str, Any]] = {
    2: {'locations': [1], 'networks': [], 'ips': []},
    3: {'locations': [1, 2], 'networks': [], 'ips': []},
    4: {'locations': [], 'networks': [], 'ips': []},
    6: {'locations': [], 'networks': [5, 500], 'ips': ['4:0a000001', '4:0b000005'],
        'related': [{'object': 1, 'relation': 3}, {'object': 2, 'relation': 4}]},
    7: {'locations': [99], 'networks': [501], 'ips': ['6:fd000000000000000000000000000001'],
        'related': [{'object': 2, 'relation': 3}]},
}


def _object(public_id: int, mds: Any = None, **values: Any) -> dict[str, Any]:
    """An object with an entry per given field"""
    document: dict[str, Any] = {'public_id': public_id, 'type_id': 1,
                                'fields': [{'name': name, 'value': value} for name, value in values.items()]}

    if mds is not None:
        document['multi_data_sections'] = mds

    if public_id in BLOCKS:
        document['_scope'] = BLOCKS[public_id]

    return document


def _interfaces(*subnets: Any) -> list[dict[str, Any]]:
    """Interface rows"""
    return [{'section_id': 'dg-ipam-interface', 'values': [
        {'multi_data_id': index, 'data': [{'name': 'dg-interface-subnet', 'value': subnet}]}
        for index, subnet in enumerate(subnets)]}]


OBJECTS: list[dict[str, Any]] = [
    _object(1, host='web.01', size=4, seen=datetime(2026, 11, 1, 14, 30), on=True, state='a', ref=9, owner=70,
            team=[80, 1]),
    _object(2, host='db-01', size=16.5, seen=datetime(2026, 10, 1), on=False, state='b', ref=8, owner=71, team=[2]),
    _object(3, host=None, size=None, seen=None, on=None, state=None, ref=None, owner=None, team=[]),
    _object(4, host='', size='12', seen='2026-11-01', on=1, state='', ref='9', owner='70', team=None),
    _object(5),
    _object(6, mds=_interfaces(500, 9), host='WEB.02', size=0, seen=datetime(2026, 11, 25, 23, 0), on=True),
    _object(7, mds=_interfaces(501), host=['x', 'web'], size=[3, 30], team=[81]),
    {'public_id': 8, 'type_id': 1},
    {'public_id': 9, 'type_id': 1, 'fields': [{'name': 'host'}, {'name': 'size', 'value': 7.0}]},
]

CONDITIONS: list[dict[str, Any]] = [
    *[{'field': 'host', 'op': op, 'value': 'web'} for op in ('equals', 'not_equals', 'contains', 'starts_with')],
    {'field': 'host', 'op': 'in', 'value': ['db-01', 'web']}, {'field': 'host', 'op': 'not_in', 'value': ['db-01']},
    *[{'field': name, 'op': op} for name in FIELDS for op in ('exists', 'is_empty')],
    *[{'field': 'size', 'op': op, 'value': 7} for op in ('equals', 'not_equals', 'lt', 'lte', 'gt', 'gte')],
    {'field': 'size', 'op': 'between', 'value': [4, 16.5]}, {'field': 'size', 'op': 'in', 'value': [4, 12, 30]},
    {'field': 'size', 'op': 'not_in', 'value': [4, 0]},
    *[{'field': 'seen', 'op': op, 'value': '2026-11-01'} for op in ('equals', 'not_equals', 'lt', 'lte', 'gt', 'gte')],
    {'field': 'seen', 'op': 'lt', 'value': {'days_ago': 30}}, {'field': 'seen', 'op': 'gte', 'value': {'days_ago': 0}},
    {'field': 'seen', 'op': 'between', 'value': ['2026-10-01', {'days_ago': 1}]},
    {'field': 'on', 'op': 'equals', 'value': True}, {'field': 'on', 'op': 'not_equals', 'value': True},
    {'field': 'state', 'op': 'in', 'value': ['a']}, {'field': 'state', 'op': 'not_equals', 'value': 'a'},
    {'field': 'ref', 'op': 'equals', 'value': 9}, {'field': 'ref', 'op': 'not_in', 'value': [9]},
    {'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}},
    {'field': 'owner', 'op': 'in', 'value': [70, 71]},
    {'field': 'team', 'op': 'contains', 'value': {'user': 'groups'}}, {'field': 'team', 'op': 'contains', 'value': 2},
    {'within': 1}, {'within': 2}, {'within': 99}, {'within': 100}, {'in_network': 5}, {'in_network': 500},
    {'in_network': 9}, {'in_network': '10.0.0.0/8'}, {'in_network': '11.0.0.0/30'}, {'in_network': '11.0.0.0/32'},
    {'in_network': 'fd00::/64'}, {'in_network': '0.0.0.0/0'},
    {'related_to': 1}, {'related_to': 2}, {'related_to': 2, 'relation': 3}, {'related_to': 1, 'relation': 4},
    {'related_to': 9},
]


@pytest.fixture(name='objects', scope='module')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The scratch collection, dropped after"""
    collection = database_manager.connector.client[database_name][SCRATCH]
    collection.drop()
    collection.insert_many([dict(document) for document in OBJECTS])

    yield collection

    collection.drop()


@pytest.mark.parametrize('condition', CONDITIONS, ids=[str(index) for index in range(len(CONDITIONS))])
def test_the_matcher_answers_as_mongodb(objects: Any, condition: dict[str, Any]) -> None:
    """The same objects, object by object"""
    criteria: dict[str, Any] = compile_scope([condition], FIELDS, NOW, CONTEXT)
    stored: list[dict[str, Any]] = list(objects.find({}, {'_id': 0}))

    by_mongo: list[int] = sorted(document['public_id'] for document in objects.find(criteria))
    by_matcher: list[int] = sorted(document['public_id'] for document in stored
                                   if document_matches(document, criteria))

    assert by_matcher == by_mongo, condition


def test_combined_and_or_filters(objects: Any) -> None:
    """An $or of a type clause and a scope, as the engine builds them"""
    scope = compile_scope([{'field': 'size', 'op': 'gt', 'value': 3}, {'within': 1}], FIELDS, NOW, CONTEXT)
    criteria = {'$or': [{'type_id': {'$nin': [1]}}, {'$and': [{'type_id': {'$in': [1]}}, scope]}]}
    stored: list[dict[str, Any]] = list(objects.find({}, {'_id': 0}))

    assert sorted(d['public_id'] for d in stored if document_matches(d, criteria)) == sorted(
        d['public_id'] for d in objects.find(criteria))
