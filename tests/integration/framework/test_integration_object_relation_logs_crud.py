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
Integration tests for the CmdbObjectRelationLog CRUD surface of ObjectRelationLogsManager

Pins the manager-layer behavior against a real MongoDB instance:

- insert / get / delete round-trip through the bound collection
- iterate honours BuilderParameters and returns model-bound results
- build_object_relation_log persists a log document with the expected action / author / changes
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_relation_logs_manager import ObjectRelationLogsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 1
AUTHOR_NAME: str = 'admin'

PARENT_OBJECT_ID: int = 510
CHILD_OBJECT_ID: int = 520
OBJECT_RELATION_ID: int = 530

LOG_ID_FOR_INSERT: int = 66101
LOG_ID_FOR_GET: int = 66102
LOG_ID_FOR_DELETE: int = 66103
LOG_ID_FOR_ITERATE_A: int = 66104
LOG_ID_FOR_ITERATE_B: int = 66105
MISSING_LOG_ID: int = 66900

ALL_LOG_IDS: list[int] = [
    LOG_ID_FOR_INSERT, LOG_ID_FOR_GET, LOG_ID_FOR_DELETE,
    LOG_ID_FOR_ITERATE_A, LOG_ID_FOR_ITERATE_B,
]


def _log_data(public_id: int) -> dict[str, Any]:
    """Builds a CmdbObjectRelationLog payload acceptable to insert_object_relation_log."""
    return {
        'public_id': public_id,
        'object_relation_id': OBJECT_RELATION_ID,
        'object_relation_parent_id': PARENT_OBJECT_ID,
        'object_relation_child_id': CHILD_OBJECT_ID,
        'action': LogInteraction.CREATE,
        'author_id': AUTHOR_ID,
        'author_name': AUTHOR_NAME,
        'changes': {},
    }


def _object_relation(field_values: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds the minimal CmdbObjectRelation dict the log builder reads."""
    return {
        'public_id': OBJECT_RELATION_ID,
        'relation_parent_id': PARENT_OBJECT_ID,
        'relation_child_id': CHILD_OBJECT_ID,
        'field_values': field_values,
    }


def _mock_user() -> MagicMock:
    """A MagicMock CmdbUser exposing get_public_id / get_display_name."""
    user = MagicMock()
    user.get_public_id.return_value = AUTHOR_ID
    user.get_display_name.return_value = AUTHOR_NAME
    return user


def _delete_by_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes a set of CmdbObjectRelationLog docs directly via the collection."""
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed docs after the module's tests have run."""
    yield
    _delete_by_ids(database_manager, database_name, ALL_LOG_IDS)
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'object_relation_id': OBJECT_RELATION_ID})


@pytest.fixture(name='object_relation_logs_manager')
def fixture_object_relation_logs_manager(database_manager: MongoDatabaseManager) -> ObjectRelationLogsManager:
    """Provides an ObjectRelationLogsManager wired to the test database."""
    return ObjectRelationLogsManager(database_manager)


# ------------------------------------------------------- INSERT ----------------------------------------------------- #

class TestInsertObjectRelationLog:
    """``insert_object_relation_log`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self, object_relation_logs_manager, database_manager, database_name,
    ) -> None:
        """Insert returns the public_id and a follow-up find sees the persisted row."""
        try:
            returned_id = object_relation_logs_manager.insert_object_relation_log(_log_data(LOG_ID_FOR_INSERT))

            assert returned_id == LOG_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
                .find_one({'public_id': LOG_ID_FOR_INSERT})
            assert stored is not None
            assert stored['object_relation_id'] == OBJECT_RELATION_ID
        finally:
            _delete_by_ids(database_manager, database_name, [LOG_ID_FOR_INSERT])


# --------------------------------------------------------- GET ------------------------------------------------------ #

class TestGetObjectRelationLog:
    """``get_object_relation_log`` returns the doc as a dict or None for a missing id."""

    @pytest.fixture(autouse=True)
    def _seed_one(self, object_relation_logs_manager, database_manager, database_name):
        object_relation_logs_manager.insert_object_relation_log(_log_data(LOG_ID_FOR_GET))
        yield
        _delete_by_ids(database_manager, database_name, [LOG_ID_FOR_GET])

    def test_returns_dict_for_existing_id(self, object_relation_logs_manager: ObjectRelationLogsManager) -> None:
        """An existing id returns the raw document as a dict."""
        result = object_relation_logs_manager.get_object_relation_log(LOG_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == LOG_ID_FOR_GET

    def test_returns_none_for_missing_id(self, object_relation_logs_manager: ObjectRelationLogsManager) -> None:
        """A missing id returns None rather than raising (GenericManager.get_item contract)."""
        assert object_relation_logs_manager.get_object_relation_log(MISSING_LOG_ID) is None


# ------------------------------------------------------- DELETE ----------------------------------------------------- #

class TestDeleteObjectRelationLog:
    """``delete_object_relation_log`` removes the doc; a follow-up get returns None."""

    def test_removes_doc(self, object_relation_logs_manager, database_manager, database_name) -> None:
        """Deleting an existing log makes it unretrievable."""
        object_relation_logs_manager.insert_object_relation_log(_log_data(LOG_ID_FOR_DELETE))

        object_relation_logs_manager.delete_object_relation_log(LOG_ID_FOR_DELETE)

        assert object_relation_logs_manager.get_object_relation_log(LOG_ID_FOR_DELETE) is None
        _delete_by_ids(database_manager, database_name, [LOG_ID_FOR_DELETE])


# ------------------------------------------------------- ITERATE ---------------------------------------------------- #

class TestIterateObjectRelationLogs:
    """``iterate`` returns model-bound results and the matching total."""

    def test_returns_inserted_rows_as_instances(
        self, object_relation_logs_manager, database_manager, database_name,
    ) -> None:
        """Two inserted rows show up as ``CmdbObjectRelationLog`` instances in the IterationResult."""
        seeded = [LOG_ID_FOR_ITERATE_A, LOG_ID_FOR_ITERATE_B]
        try:
            for public_id in seeded:
                object_relation_logs_manager.insert_object_relation_log(_log_data(public_id))

            params = BuilderParameters(criteria={'public_id': {'$in': seeded}}, sort='public_id', order=1)
            iteration_result = object_relation_logs_manager.iterate(params)

            assert iteration_result.total == len(seeded)
            assert [log.public_id for log in iteration_result.results] == seeded
            assert all(isinstance(log, CmdbObjectRelationLog) for log in iteration_result.results)
        finally:
            _delete_by_ids(database_manager, database_name, seeded)


# ------------------------------------------------ BUILD_OBJECT_RELATION_LOG ----------------------------------------- #

class TestBuildObjectRelationLog:
    """``build_object_relation_log`` persists a log document end-to-end."""

    def test_create_log_is_persisted_with_flat_changes(
        self, object_relation_logs_manager, database_manager, database_name,
    ) -> None:
        """A CREATE build persists a log carrying the author and a flat field-value snapshot."""
        try:
            object_relation_logs_manager.build_object_relation_log(
                LogInteraction.CREATE,
                _mock_user(),
                None,
                _object_relation([{'name': 'a', 'value': 1}]),
            )

            stored = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
                .find_one({'object_relation_id': OBJECT_RELATION_ID})
            assert stored is not None
            assert stored['action'] == LogInteraction.CREATE
            assert stored['author_id'] == AUTHOR_ID
            assert stored['changes'] == {'a': 1}
        finally:
            database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
                .delete_many({'object_relation_id': OBJECT_RELATION_ID})
