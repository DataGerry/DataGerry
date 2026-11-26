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
Integration tests for cmdb.database.updater.versions.updater_20261127 against a real MongoDB

The groups holding ``base.framework.type.edit`` or a wildcard covering it are given ``base.access.view`` and recorded in
the access rights migration report; every other group is untouched; a second run changes nothing; a run stopped after
the report finishes the grant; a database where no group qualifies gets no report; the version is bumped
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261127 import Update20261127
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261127'
GROUPS: str = 'management.groups'
REPORTS: str = 'access.migrationReport'
REPORT_ID: str = 'access_rights_migration'
VERSION: int = 20261127
ACCESS_VIEW: str = 'base.access.view'

# public_id -> stored rights, and whether the run gives the group the view right
STORED: dict[int, list[str]] = {
    1: ['base.*'],
    2: ['base.framework.type.view'],
    11: ['base.framework.type.edit', 'base.framework.object.view'],
    12: ['base.framework.type.*'],
    13: ['base.framework.*'],
    14: ['base.framework.type.edit', 'base.access.*'],
    15: ['base.framework.type.add'],
}
GIVEN: list[int] = [11, 12, 13]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[str, Any]]:
    """An empty database, dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)

    yield name, client[name]

    client.drop_database(name)


def _seed(database: Any) -> None:
    """The groups"""
    database[GROUPS].insert_many([{'public_id': group_id, 'name': f'g{group_id}', 'label': f'G{group_id}',
                                   'rights': list(rights)} for group_id, rights in STORED.items()])


def _run(database_manager: MongoDatabaseManager, name: str) -> None:
    """One run"""
    Update20261127(database_manager, name).start_update()


def _rights(database: Any) -> dict[int, list[str]]:
    """Every group's stored rights"""
    return {group['public_id']: group['rights'] for group in database[GROUPS].find({}, {'_id': 0})}


def _version(database: Any) -> Any:
    """The stamped updater version"""
    return database['settings.conf'].find_one({'_id': 'updater'})


def test_the_former_type_acl_editors_get_the_view_right_only(database_manager: MongoDatabaseManager,
                                                             scratch: tuple[str, Any]) -> None:
    """Appended once; every other group exactly as stored"""
    name, database = scratch
    _seed(database)

    _run(database_manager, name)

    assert _rights(database) == {group_id: [*rights, ACCESS_VIEW] if group_id in GIVEN else rights
                                 for group_id, rights in STORED.items()}


def test_the_report_names_each_group_and_the_right(database_manager: MongoDatabaseManager,
                                                   scratch: tuple[str, Any]) -> None:
    """Ascending, completed"""
    name, database = scratch
    _seed(database)

    _run(database_manager, name)
    report: dict[str, Any] = database[REPORTS].find_one({'_id': REPORT_ID})

    assert report['groups'] == [{'group_id': group_id, 'granted': [ACCESS_VIEW]} for group_id in GIVEN]
    assert report['started_at'] and report['completed_at']


def test_a_second_run_changes_nothing(database_manager: MongoDatabaseManager, scratch: tuple[str, Any]) -> None:
    """The given groups no longer qualify; the report keeps its entries"""
    name, database = scratch
    _seed(database)
    _run(database_manager, name)
    rights, report = _rights(database), database[REPORTS].find_one({'_id': REPORT_ID})

    _run(database_manager, name)

    assert _rights(database) == rights
    assert database[REPORTS].find_one({'_id': REPORT_ID}) == report


def test_a_run_stopped_after_the_report_finishes_the_grant(database_manager: MongoDatabaseManager,
                                                           scratch: tuple[str, Any]) -> None:
    """The report written, the rights not: the next run grants them and records no entry twice"""
    name, database = scratch
    _seed(database)
    Update20261127(database_manager, name).record(GIVEN)

    _run(database_manager, name)

    assert [group_id for group_id, rights in _rights(database).items() if ACCESS_VIEW in rights] == GIVEN
    assert len(database[REPORTS].find_one({'_id': REPORT_ID})['groups']) == len(GIVEN)


def test_no_qualifying_group_writes_only_the_stamp(database_manager: MongoDatabaseManager,
                                                   scratch: tuple[str, Any]) -> None:
    """A fresh database: no report, no group touched"""
    name, database = scratch
    database[GROUPS].insert_many([{'public_id': 1, 'name': 'admin', 'label': 'A', 'rights': ['base.*']},
                                  {'public_id': 2, 'name': 'user', 'label': 'U',
                                   'rights': ['base.framework.type.view']}])

    _run(database_manager, name)

    assert database[REPORTS].count_documents({}) == 0
    assert _rights(database) == {1: ['base.*'], 2: ['base.framework.type.view']}
    assert _version(database)['version'] == VERSION
