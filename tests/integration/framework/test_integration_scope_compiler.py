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
Integration tests: the scope compiler's filters against real documents in MongoDB (phase 9 step 2)

A scratch collection holds objects shaped like CmdbObjects - a field entry with a value, an empty one (null, '', []),
none at all, a number stored as text (T583) - and each operator is asked which it matches. Pinned: equality, lists,
negations never matching an empty or missing field, exists / is_empty (a missing entry is empty), contains on text
(escaped) and on a multi-value person field, starts_with, number order, day-granular dates and a relative date, and a
scope as the AND of its conditions
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.scope_compiler import MULTIPLE_PERSON_KIND, ScopeField, compile_scope
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH: str = 'scope-compiler.objects'
NOW: datetime = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
FIELDS: dict[str, ScopeField] = {'host': ScopeField('text'), 'size': ScopeField('number'),
                                 'seen': ScopeField('date'), 'team': ScopeField(MULTIPLE_PERSON_KIND)}


def _object(public_id: int, **values: Any) -> dict[str, Any]:
    """An object with an entry per given field"""
    return {'public_id': public_id, 'fields': [{'name': name, 'value': value} for name, value in values.items()]}


OBJECTS: list[dict[str, Any]] = [
    _object(1, host='web.01', size=4, seen=datetime(2026, 11, 1, 14, 30), team=[7, 8]),
    _object(2, host='db-01', size=16, seen=datetime(2026, 10, 1), team=[9]),
    _object(3, host=None, size=None, seen=None, team=[]),
    _object(4, host='', size='12'),
    _object(5),
]


@pytest.fixture(name='objects', autouse=True)
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The scratch collection, dropped after"""
    collection = database_manager.connector.client[database_name][SCRATCH]
    collection.drop()
    collection.insert_many([dict(document) for document in OBJECTS])

    yield collection

    collection.drop()


def _matched(objects: Any, *blocks: dict[str, Any]) -> list[int]:
    """The ids the scope matches"""
    return sorted(document['public_id'] for document in objects.find(compile_scope(list(blocks), FIELDS, NOW)))


@pytest.mark.parametrize('block, expected', [
    ({'field': 'host', 'op': 'equals', 'value': 'db-01'}, [2]),
    ({'field': 'host', 'op': 'not_equals', 'value': 'db-01'}, [1]),
    ({'field': 'size', 'op': 'in', 'value': [4, 12]}, [1]),
    ({'field': 'size', 'op': 'not_in', 'value': [4]}, [2]),
    ({'field': 'size', 'op': 'not_equals', 'value': 4}, [2]),
    ({'field': 'host', 'op': 'not_in', 'value': ['db-01']}, [1]),
    ({'field': 'host', 'op': 'exists'}, [1, 2]),
    ({'field': 'host', 'op': 'is_empty'}, [3, 4, 5]),
    ({'field': 'team', 'op': 'is_empty'}, [3, 4, 5]),
    ({'field': 'host', 'op': 'contains', 'value': 'b.0'}, [1]),
    ({'field': 'host', 'op': 'starts_with', 'value': 'db'}, [2]),
    ({'field': 'team', 'op': 'contains', 'value': 8}, [1]),
    ({'field': 'size', 'op': 'gt', 'value': 5}, [2]),
    ({'field': 'size', 'op': 'between', 'value': [4, 16]}, [1, 2]),
    ({'field': 'seen', 'op': 'equals', 'value': '2026-11-01'}, [1]),
    ({'field': 'seen', 'op': 'lte', 'value': '2026-11-01'}, [1, 2]),
    ({'field': 'seen', 'op': 'lt', 'value': {'days_ago': 30}}, [2]),
    ({'field': 'seen', 'op': 'not_equals', 'value': '2026-11-01'}, [2]),
], ids=['equals', 'not-equals-skips-empty', 'in-on-type-only', 'not-in-skips-empty-and-mistyped',
        'not-equals-skips-mistyped', 'not-in-text', 'exists', 'is-empty-missing', 'is-empty-list', 'contains-escaped',
        'starts-with', 'member', 'gt', 'between', 'date-whole-day', 'date-lte-day',
        'relative-date', 'date-not-equals'])
def test_each_operator(objects: Any, block: dict[str, Any], expected: list[int]) -> None:
    """A number stored as text never matches; a missing or empty field never satisfies a negation"""
    assert _matched(objects, block) == expected


def test_a_scope_is_the_and_of_its_conditions(objects: Any) -> None:
    """Both must hold"""
    assert _matched(objects, {'field': 'size', 'op': 'gt', 'value': 1},
                    {'field': 'host', 'op': 'starts_with', 'value': 'web'}) == [1]
