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
Integration tests for cmdb.database.updater.versions.updater_20261126 against a real MongoDB

A ``person_sync`` section with the group sync on and no default (absent or null) is switched off - the user sync and
everything else kept; one with a default, or the group sync off, is left alone; no section, nothing; a second run
changes nothing; the version is bumped
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261126 import Update20261126
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261126'
SETTINGS: str = 'settings.conf'
SECTION_ID: str = 'person_sync'
USERS: dict[str, Any] = {'active': True, 'default_type_id': 7, 'type_overrides': []}
VERSION: int = 20261126


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, Any]]:
    """An empty database, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)

    yield name, client[name]

    client.drop_database(name)


def _run(database_manager: MongoDatabaseManager, name: str) -> None:
    """One run"""
    Update20261126(database_manager, name).start_update()


def _section(database: Any) -> dict[str, Any] | None:
    """The stored person_sync section"""
    return database[SETTINGS].find_one({'_id': SECTION_ID})


@pytest.mark.parametrize('groups', [{'active': True}, {'active': True, 'default_type_id': None}],
                         ids=['absent', 'null'])
def test_on_without_a_default_is_switched_off(database_manager, scratch, groups: dict[str, Any]) -> None:
    """Twice: the second run changes nothing; the user sync kept; the version bumped"""
    name, database = scratch
    database[SETTINGS].insert_one({'_id': SECTION_ID, 'users': USERS, 'groups': groups})

    for _ in range(2):
        _run(database_manager, name)

        assert _section(database) == {'_id': SECTION_ID, 'users': USERS, 'groups': {**groups, 'active': False}}

    assert database[SETTINGS].find_one({'_id': 'updater'})['version'] == VERSION


@pytest.mark.parametrize('groups', [{'active': True, 'default_type_id': 8}, {'active': False}],
                         ids=['with-a-default', 'off'])
def test_anything_else_is_left_alone(database_manager, scratch, groups: dict[str, Any]) -> None:
    """Nothing to repair"""
    name, database = scratch
    document: dict[str, Any] = {'_id': SECTION_ID, 'users': USERS, 'groups': groups}
    database[SETTINGS].insert_one(dict(document))

    _run(database_manager, name)

    assert _section(database) == document


def test_no_section_nothing(database_manager, scratch) -> None:
    """A fresh database - only the version"""
    name, database = scratch

    _run(database_manager, name)

    assert _section(database) is None
    assert database[SETTINGS].find_one({'_id': 'updater'})['version'] == VERSION
