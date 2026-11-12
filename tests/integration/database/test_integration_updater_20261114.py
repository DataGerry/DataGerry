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
Integration tests for cmdb.database.updater.versions.updater_20261114 against a real MongoDB

Builds the two predecessor indexes on the logs collection the way an existing install holds them, next to the declared
successors, runs the migration, and asserts:

  - both predecessors are gone; the successors and the unique public_id index stay
  - a second run changes nothing
  - a collection that never had the predecessors (a new install) is a no-op

The test session builds no declared index, so each test builds what it needs and drops what it built
"""
from typing import Any, Iterator

import pytest
from pymongo import IndexModel

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261114 import REPLACED_INDEXES, Update20261114
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
# -------------------------------------------------------------------------------------------------------------------- #

MONGO_ID_INDEX: str = '_id_'
PREDECESSORS: list[IndexModel] = [
    IndexModel([('object_id', 1), ('log_time', -1)], name='object_id_log_time'),
    IndexModel([('log_type', 1), ('action', 1)], name='log_type_action'),
]
DECLARED_NAMES: set[str] = {model.document['name'] for model in CmdbMetaLog.get_index_keys()}


@pytest.fixture(name='logs')
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The logs collection behind its declared indexes; every index built here is dropped again after"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    had_indexes: set[str] = set(logs.index_information())
    logs.create_indexes(CmdbMetaLog.get_index_keys())

    yield logs

    for index_name in set(logs.index_information()) - had_indexes - {MONGO_ID_INDEX}:
        logs.drop_index(index_name)


def _index_names(logs: Any) -> set[str]:
    """The index names the collection holds"""
    return set(logs.index_information())


def test_both_predecessors_are_dropped_and_the_declared_indexes_stay(logs: Any, database_manager: MongoDatabaseManager,
                                                                     database_name: str) -> None:
    """Only the two replaced names go"""
    logs.create_indexes(PREDECESSORS)
    assert set(REPLACED_INDEXES) <= _index_names(logs)

    Update20261114(database_manager, database_name).start_update()

    names: set[str] = _index_names(logs)
    assert not set(REPLACED_INDEXES) & names
    assert DECLARED_NAMES <= names


def test_a_second_run_changes_nothing(logs: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-run safe"""
    logs.create_indexes(PREDECESSORS)
    Update20261114(database_manager, database_name).start_update()
    first: dict[str, Any] = logs.index_information()

    Update20261114(database_manager, database_name).start_update()

    assert logs.index_information() == first


def test_a_new_install_without_the_predecessors_is_a_no_op(logs: Any, database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
    """Nothing to drop is no failure"""
    for name in REPLACED_INDEXES:
        if name in _index_names(logs):
            logs.drop_index(name)
    before: dict[str, Any] = logs.index_information()

    Update20261114(database_manager, database_name).start_update()

    assert logs.index_information() == before
