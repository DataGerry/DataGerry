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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests for cmdb.database.updater.versions.updater_20261122 against a real MongoDB

Every Type carrying PERSON loses the required flag of ``first_name`` and ``last_name`` - also one that flagged only
one of them; its display name and its own fields keep their flags; a Type without the marker keeps a required
``first_name`` of its own; every other key stays; a second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261122 import Update20261122
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261122'
TYPES: str = 'framework.types'
DEFAULT_PERSON_ID: int = 1
CUSTOM_PERSON_ID: int = 2
ONE_FLAG_PERSON_ID: int = 3
PLAIN_TYPE_ID: int = 4
OWN_FIELD: str = 'badge_number'


def _field(name: str, required: bool | None = None) -> dict[str, Any]:
    """A text field, carrying the given required flag (none when None)"""
    field: dict[str, Any] = {'type': 'text', 'name': name, 'label': name}

    if required is not None:
        field['required'] = required

    return field


def _type(public_id: int, special_type: str | None, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A Type document as far as the migration reads it"""
    return {'public_id': public_id, 'name': f'type-{public_id}', 'special_type': special_type, 'fields': fields}


SEEDED: list[dict[str, Any]] = [
    _type(DEFAULT_PERSON_ID, 'PERSON', [
        _field('display_name', True), _field('first_name', True), _field('last_name', True), _field('phone_number'),
        _field('email'),
    ]),
    _type(CUSTOM_PERSON_ID, 'PERSON', [
        _field('display_name', True), _field('first_name', True), _field('last_name', False),
        _field(OWN_FIELD, True),
    ]),
    _type(ONE_FLAG_PERSON_ID, 'PERSON', [
        _field('display_name', True), _field('first_name'), _field('last_name', True),
    ]),
    _type(PLAIN_TYPE_ID, None, [_field('first_name', True), _field('last_name', True)]),
]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A database with the seeded Types, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][TYPES].insert_many([dict(a_type) for a_type in SEEDED])

    yield scratch

    client.drop_database(scratch)


def _types(database_manager: MongoDatabaseManager, scratch: str) -> dict[int, dict[str, Any]]:
    """Every Type without its _id"""
    return {
        a_type['public_id']: a_type
        for a_type in database_manager.connector.client[scratch][TYPES].find({}, {'_id': 0})
    }


def _flags(a_type: dict[str, Any]) -> dict[str, Any]:
    """Each field's required flag, None for a field without one"""
    return {field['name']: field.get('required') for field in a_type['fields']}


def test_the_person_names_lose_the_flag_and_nothing_else(database_manager: MongoDatabaseManager,
                                                         scratch: str) -> None:
    """Twice: the second run changes nothing"""
    for _ in range(2):
        Update20261122(database_manager, scratch).start_update()
        types = _types(database_manager, scratch)

        assert _flags(types[DEFAULT_PERSON_ID]) == {
            'display_name': True, 'first_name': None, 'last_name': None, 'phone_number': None, 'email': None,
        }
        assert _flags(types[CUSTOM_PERSON_ID]) == {
            'display_name': True, 'first_name': None, 'last_name': None, OWN_FIELD: True,
        }
        assert _flags(types[ONE_FLAG_PERSON_ID]) == {'display_name': True, 'first_name': None, 'last_name': None}


def test_a_type_without_the_marker_keeps_its_flags(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Field names alone do not make a person Type"""
    Update20261122(database_manager, scratch).start_update()

    assert _flags(_types(database_manager, scratch)[PLAIN_TYPE_ID]) == {'first_name': True, 'last_name': True}


def test_every_other_key_stays(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Only the two flags go"""
    Update20261122(database_manager, scratch).start_update()

    assert _types(database_manager, scratch)[CUSTOM_PERSON_ID] == {
        'public_id': CUSTOM_PERSON_ID, 'name': f'type-{CUSTOM_PERSON_ID}', 'special_type': 'PERSON',
        'fields': [
            _field('display_name', True), _field('first_name'), _field('last_name'), _field(OWN_FIELD, True),
        ],
    }
