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
Integration tests for the CmdbObjectLog surface of LogsManager against a real MongoDB instance

The unit suite drives ``insert_log`` / ``iterate`` against a mocked manager with the database
collaborators stubbed; here the same methods run end-to-end through the bound ``framework.logs``
collection:

- insert_log assembles the static fields (public_id, action value/name, log_type, log_time), merges
  the caller kwargs and persists a retrievable document
- insert_log draws a fresh incrementing public_id for each entry
- iterate runs the real aggregation, binds the rows to CmdbObjectLog and reports the matching total,
  honouring the BuilderParameters criteria
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.logs_manager import LogsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
# -------------------------------------------------------------------------------------------------------------------- #

LOG_TYPE: str = CmdbObjectLog.__name__

# Distinctive object ids so the seeded logs are isolated from any other test's logs
OBJECT_ID_INSERT: int = 76001
OBJECT_ID_INCREMENT: int = 76002
OBJECT_ID_ITERATE: int = 76003
OBJECT_ID_OTHER: int = 76004

USER_ID: int = 1
USER_NAME: str = 'admin'
LOG_VERSION: str = '1.0.0'

ALL_OBJECT_IDS: list[int] = [OBJECT_ID_INSERT, OBJECT_ID_INCREMENT, OBJECT_ID_ITERATE, OBJECT_ID_OTHER]


def _insert_object_log(logs_manager: LogsManager, object_id: int, action: LogAction = LogAction.CREATE) -> int:
    """Inserts one CmdbObjectLog via ``insert_log`` and returns the assigned public_id."""
    return logs_manager.insert_log(
        action=action,
        log_type=LOG_TYPE,
        object_id=object_id,
        version=LOG_VERSION,
        user_id=USER_ID,
        user_name=USER_NAME,
    )


def _delete_by_object_ids(database_manager: MongoDatabaseManager, database_name: str, object_ids: list[int]) -> None:
    """Removes every seeded log by its object_id directly via the collection."""
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': object_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seeded logs after the module's tests have run."""
    yield
    _delete_by_object_ids(database_manager, database_name, ALL_OBJECT_IDS)


@pytest.fixture(name='logs_manager')
def fixture_logs_manager(database_manager: MongoDatabaseManager) -> LogsManager:
    """Provides a LogsManager wired to the test database."""
    return LogsManager(database_manager)


# ------------------------------------------------------- INSERT ----------------------------------------------------- #

class TestInsertLog:
    """``insert_log`` assembles the static fields, merges kwargs and persists the entry."""

    def test_persists_assembled_document(
        self, logs_manager, database_manager, database_name,
    ) -> None:
        """The stored doc carries the public_id, action value/name, log_type and merged kwargs."""
        try:
            public_id = _insert_object_log(logs_manager, OBJECT_ID_INSERT)

            stored = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)\
                .find_one({'public_id': public_id})
            assert stored is not None
            assert stored['object_id'] == OBJECT_ID_INSERT
            assert stored['log_type'] == LOG_TYPE
            assert stored['action'] == LogAction.CREATE.value
            assert stored['action_name'] == LogAction.CREATE.name
            assert stored['log_time'] is not None
        finally:
            _delete_by_object_ids(database_manager, database_name, [OBJECT_ID_INSERT])

    def test_assigns_incrementing_public_ids(
        self, logs_manager, database_manager, database_name,
    ) -> None:
        """Two successive inserts receive distinct, increasing public_ids."""
        try:
            first_id = _insert_object_log(logs_manager, OBJECT_ID_INCREMENT)
            second_id = _insert_object_log(logs_manager, OBJECT_ID_INCREMENT)

            assert second_id > first_id
        finally:
            _delete_by_object_ids(database_manager, database_name, [OBJECT_ID_INCREMENT])


# ------------------------------------------------------- ITERATE ---------------------------------------------------- #

class TestIterateLogs:
    """``iterate`` returns model-bound results and the matching total for the criteria."""

    def test_returns_only_matching_logs_as_instances(
        self, logs_manager, database_manager, database_name,
    ) -> None:
        """Two logs of the target object are returned as CmdbObjectLog; an unrelated log is excluded."""
        try:
            _insert_object_log(logs_manager, OBJECT_ID_ITERATE)
            _insert_object_log(logs_manager, OBJECT_ID_ITERATE, action=LogAction.EDIT)
            _insert_object_log(logs_manager, OBJECT_ID_OTHER)

            params = BuilderParameters(criteria={'object_id': OBJECT_ID_ITERATE}, sort='public_id', order=1)
            iteration_result = logs_manager.iterate(params)

            assert iteration_result.total == 2
            assert all(isinstance(log, CmdbObjectLog) for log in iteration_result.results)
            assert all(log.object_id == OBJECT_ID_ITERATE for log in iteration_result.results)
        finally:
            _delete_by_object_ids(database_manager, database_name, [OBJECT_ID_ITERATE, OBJECT_ID_OTHER])
