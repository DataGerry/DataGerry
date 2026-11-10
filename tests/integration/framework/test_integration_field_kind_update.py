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
Integration tests: the field-type statement against stored objects of a real MongoDB

``build_field_kind_update`` is one pipeline update; what it does to a document can only be shown by running it. Pinned:
an entry of a field whose type changed (another stored type, or none) is reset to the field's default (or None) with
the new type - flat and in every MDS row; an entry of an unchanged field is stamped and keeps its value; an entry of an
undeclared field, an object of another type and a non-array are left alone; a name starting with '$' is a value; a
second run modifies nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.objects_propagation_helper import build_field_kind_update
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 96401
OTHER_TYPE_ID: int = 96402
OBJECT_ID: int = 96411
UNTYPED_ID: int = 96412
OTHER_OBJECT_ID: int = 96413
GARBAGE_ID: int = 96414
ALL_IDS: list[int] = [OBJECT_ID, UNTYPED_ID, OTHER_OBJECT_ID, GARBAGE_ID]

SECTION_ID: str = 'ports'
DEFAULT_STATUS: str = 'up'
DECLARED: list[dict[str, Any]] = [
    {'name': 'status', 'type': 'select', 'value': DEFAULT_STATUS},   # text -> select, with a default
    {'name': 'when', 'type': 'date'},                                # text -> date, no default
    {'name': 'note', 'type': 'text'},                                # unchanged
    {'name': '$odd', 'type': 'number'},                              # a name that looks like a path
    {'name': 'row-ip', 'type': 'ref'},                               # an MDS field: text -> ref
]
RESET: list[str] = ['status', 'when', '$odd', 'row-ip']


def _entry(name: str, value: Any, kind: str | None = 'text') -> dict[str, Any]:
    """A stored field entry; `kind` None leaves the type out."""
    entry: dict[str, Any] = {'name': name, 'value': value}

    if kind is not None:
        entry['type'] = kind

    return entry


def _object(public_id: int, type_id: int, fields: Any, sections: Any = None) -> dict[str, Any]:
    """A stored object."""
    document: dict[str, Any] = {'public_id': public_id, 'type_id': type_id, 'fields': fields}

    if sections is not None:
        document['multi_data_sections'] = sections

    return document


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Four stored objects in the shapes the docstring names, removed again afterwards"""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_IDS}})
    collection.insert_many([
        _object(OBJECT_ID, TYPE_ID, [
            _entry('status', 'in_betrieb'), _entry('when', 'soon'), _entry('note', 'kept'),
            _entry('$odd', 'x'), _entry('row-ip', '10.0.0.1'), _entry('ghost', 'undeclared'),
        ], [{'section_id': SECTION_ID, 'values': [
            {'multi_data_id': 1, 'data': [_entry('row-ip', '10.0.0.1'), _entry('note', 'row-note', None)]},
            {'multi_data_id': 2, 'data': [_entry('row-ip', '10.0.0.2', 'ref')]},
        ]}]),
        _object(UNTYPED_ID, TYPE_ID, [_entry('status', 'held', None), _entry('note', 'kept', 'date')]),
        _object(OTHER_OBJECT_ID, OTHER_TYPE_ID, [_entry('status', 'other')]),
        _object(GARBAGE_ID, TYPE_ID, 'not-a-list', [{'section_id': SECTION_ID, 'values': None}]),
    ])
    yield collection
    collection.delete_many({'public_id': {'$in': ALL_IDS}})


def _run(database_manager: MongoDatabaseManager) -> int:
    """The statement, through the manager - answers how many documents it modified."""
    return ObjectsManager(database_manager).apply_raw_updates([build_field_kind_update(TYPE_ID, DECLARED, RESET)])


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """One object as stored."""
    return objects.find_one({'public_id': public_id}, {'_id': 0})


def _by_name(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Entries by name."""
    return {entry['name']: entry for entry in entries}


def test_a_changed_field_is_reset_to_its_default_or_none(objects, database_manager) -> None:
    """status gets its default, when and the $-named field None - each with the declared type"""
    _run(database_manager)

    fields = _by_name(_stored(objects, OBJECT_ID)['fields'])
    assert fields['status'] == {'name': 'status', 'value': DEFAULT_STATUS, 'type': 'select'}
    assert fields['when'] == {'name': 'when', 'value': None, 'type': 'date'}
    assert fields['$odd'] == {'name': '$odd', 'value': None, 'type': 'number'}


def test_an_unchanged_field_and_an_undeclared_one_keep_their_entries(objects, database_manager) -> None:
    """note keeps its value; ghost (not declared) is left exactly as it was"""
    _run(database_manager)

    fields = _by_name(_stored(objects, OBJECT_ID)['fields'])
    assert fields['note'] == {'name': 'note', 'value': 'kept', 'type': 'text'}
    assert fields['ghost'] == {'name': 'ghost', 'value': 'undeclared', 'type': 'text'}


def test_every_mds_row_is_reset_too(objects, database_manager) -> None:
    """A stale row entry is reset; a row already carrying the declared type keeps its value"""
    _run(database_manager)

    rows = _stored(objects, OBJECT_ID)['multi_data_sections'][0]['values']
    assert _by_name(rows[0]['data'])['row-ip'] == {'name': 'row-ip', 'value': None, 'type': 'ref'}
    assert _by_name(rows[0]['data'])['note'] == {'name': 'note', 'value': 'row-note', 'type': 'text'}
    assert rows[1]['data'] == [{'name': 'row-ip', 'value': '10.0.0.2', 'type': 'ref'}]
    assert rows[1]['multi_data_id'] == 2


def test_an_untyped_entry_of_a_changed_field_is_reset_too(objects, database_manager) -> None:
    """No stored type says nothing about the value: the field changed, so it is cleared like the others"""
    _run(database_manager)

    assert _by_name(_stored(objects, UNTYPED_ID)['fields'])['status'] == {
        'name': 'status', 'value': DEFAULT_STATUS, 'type': 'select',
    }


def test_an_entry_of_an_unchanged_field_is_stamped_and_keeps_its_value(objects, database_manager) -> None:
    """A wrong type, or none, on a field not in reset_names: corrected without losing the value"""
    _run(database_manager)

    assert _by_name(_stored(objects, UNTYPED_ID)['fields'])['note'] == {'name': 'note', 'value': 'kept', 'type': 'text'}
    row = _by_name(_stored(objects, OBJECT_ID)['multi_data_sections'][0]['values'][0]['data'])
    assert row['note'] == {'name': 'note', 'value': 'row-note', 'type': 'text'}


def test_another_type_and_non_arrays_are_left_alone(objects, database_manager) -> None:
    """Scoped by type_id; a garbage 'fields' and a null 'values' survive as they were"""
    _run(database_manager)

    assert _stored(objects, OTHER_OBJECT_ID)['fields'] == [{'name': 'status', 'value': 'other', 'type': 'text'}]
    garbage = _stored(objects, GARBAGE_ID)
    assert garbage['fields'] == 'not-a-list'
    assert garbage['multi_data_sections'] == [{'section_id': SECTION_ID, 'values': None}]


def test_a_second_run_modifies_nothing(objects, database_manager) -> None:
    """State-based: everything is stamped after the first run, so the reset no longer matches"""
    assert _run(database_manager) > 0
    first = _stored(objects, OBJECT_ID)

    assert _run(database_manager) == 0
    assert _stored(objects, OBJECT_ID) == first
