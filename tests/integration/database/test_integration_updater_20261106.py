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
Integration tests for updater_20261106 against a real MongoDB

Every entry of a declared field - flat and in every MDS row - carries its field's type afterwards, with its value
KEPT (the bug report's objects: a select field whose entries still said `text`); an undeclared entry, an object of a
type that does not exist and an untyped field stay as they were; a second run modifies nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261106 import Update20261106
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 96501
MISSING_TYPE_ID: int = 96599
OBJECT_ID: int = 96511
ORPHAN_ID: int = 96512
SECTION_ID: str = 'rows'

TYPE_FIELDS: list[dict[str, Any]] = [
    {'name': 'status', 'type': 'select'},
    {'name': 'note', 'type': 'text'},
    {'name': 'plain'},
]


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """One type, one of its objects with stale entries, and one object of a type that does not exist"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': [OBJECT_ID, ORPHAN_ID]}})

    _purge()
    types.insert_one({'public_id': TYPE_ID, 'name': 'updater-20261106', 'fields': TYPE_FIELDS})
    objects.insert_many([
        {'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'fields': [
            {'name': 'status', 'type': 'text', 'value': 'in_betrieb'},
            {'name': 'note', 'value': 'untyped'},
            {'name': 'plain', 'type': 'date', 'value': 'p'},
            {'name': 'ghost', 'type': 'text', 'value': 'g'},
        ], 'multi_data_sections': [{'section_id': SECTION_ID, 'values': [
            {'multi_data_id': 1, 'data': [{'name': 'status', 'type': 'text', 'value': 'row'}]},
        ]}]},
        {'public_id': ORPHAN_ID, 'type_id': MISSING_TYPE_ID, 'fields': [
            {'name': 'status', 'type': 'text', 'value': 'orphan'},
        ]},
    ])
    yield objects
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261106(database_manager, database_name).start_update()


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """One object as stored."""
    return objects.find_one({'public_id': public_id}, {'_id': 0})


def test_every_declared_entry_carries_its_type_and_keeps_its_value(objects, database_manager, database_name) -> None:
    """The reported case and its neighbours: stamped, never cleared; an undeclared entry left alone"""
    _run(database_manager, database_name)

    stored = _stored(objects, OBJECT_ID)
    assert stored['fields'] == [
        {'name': 'status', 'type': 'select', 'value': 'in_betrieb'},
        {'name': 'note', 'value': 'untyped', 'type': 'text'},
        {'name': 'plain', 'type': 'text', 'value': 'p'},
        {'name': 'ghost', 'type': 'text', 'value': 'g'},
    ]
    assert stored['multi_data_sections'][0]['values'][0]['data'] == [
        {'name': 'status', 'type': 'select', 'value': 'row'},
    ]


def test_an_object_of_a_missing_type_is_left_alone(objects, database_manager, database_name) -> None:
    """No declaration to stamp from"""
    _run(database_manager, database_name)

    assert _stored(objects, ORPHAN_ID)['fields'] == [{'name': 'status', 'type': 'text', 'value': 'orphan'}]


def test_a_second_run_changes_nothing(objects, database_manager, database_name) -> None:
    """Re-run safe: the first run stamped every entry"""
    _run(database_manager, database_name)
    first = _stored(objects, OBJECT_ID)

    _run(database_manager, database_name)

    assert _stored(objects, OBJECT_ID) == first
