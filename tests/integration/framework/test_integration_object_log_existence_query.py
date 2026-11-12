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
Integration tests for the object-log existence split run through `LogsManager.iterate`

The unit suite pins the shapes; here MongoDB runs them. Each test seeds its own logs and objects in a
dedicated id band and asserts on those ids only, so logs other tests leave in the collection do not matter.
Every split test runs on both paths - the filter on the deleted object ids, and the per-log join it falls
back to past ``MAX_DELETED_OBJECT_IDS`` (forced here by lowering the cap to 0) - and expects the same rows:

- a log whose object exists lands on the "exists" side only, a log whose object is gone on the
  "notexists" side only; a log without an ``object_id`` counts as "gone", on both paths
- delete-action logs and logs of another log type land on neither side
- the rows bind to CmdbObjectLog without the joined field
- the total is counted through the same criteria, so a paged read reports the whole side
- the deleted-object read is answered off the ``object_id_log_time_public_id`` index (a DISTINCT_SCAN)
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.logs_manager import LogsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs import logs_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import OBJECT_LOOKUP_FIELD
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import (
    build_deleted_object_ids_pipeline,
    build_object_log_existence_query,
    read_deleted_object_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

EXISTING_OBJECT_ID: int = 77001
DELETED_OBJECT_ID: int = 77002

LOG_ID_EXISTING: int = 77101
LOG_ID_DELETED: int = 77102
LOG_ID_DELETE_ACTION: int = 77103
LOG_ID_OTHER_TYPE: int = 77104
LOG_ID_EXISTING_SECOND: int = 77105
LOG_ID_NO_OBJECT_ID: int = 77106

ALL_LOG_IDS: list[int] = [
    LOG_ID_EXISTING, LOG_ID_DELETED, LOG_ID_DELETE_ACTION, LOG_ID_OTHER_TYPE, LOG_ID_EXISTING_SECOND,
    LOG_ID_NO_OBJECT_ID,
]
OWN_LOG_IDS: set[int] = set(ALL_LOG_IDS)

OTHER_LOG_TYPE: str = CmdbMetaLog.__name__
PAGE_SIZE: int = 1

LOG_VERSION: str = '1.0.0'
USER_ID: int = 1
USER_NAME: str = 'admin'

FILTER_PATH: str = 'filter'
JOIN_PATH: str = 'join'
# A cap of 0 makes any deleted id "too many", which sends the split down the per-log join
JOIN_FORCING_CAP: int = 0
OBJECT_ID_INDEX_NAME: str = 'object_id_log_time_public_id'
DISTINCT_SCAN_STAGE: str = 'DISTINCT_SCAN'


def _log_doc(public_id: int,
             object_id: int | None,
             action: LogAction = LogAction.EDIT,
             log_type: str = OBJECT_LOG_TYPE) -> dict[str, Any]:
    """Builds a stored object-log document for direct insertion; a None object_id leaves the key out."""
    document: dict[str, Any] = {
        'public_id': public_id,
        'log_type': log_type,
        'action': action.value,
        'action_name': action.name,
        'version': LOG_VERSION,
        'user_id': USER_ID,
        'user_name': USER_NAME,
        'changes': [],
        'comment': None,
        'render_state': None,
    }

    if object_id is not None:
        document['object_id'] = object_id

    return document


@pytest.fixture(name='logs_manager')
def fixture_logs_manager(database_manager: MongoDatabaseManager) -> LogsManager:
    """Provides a LogsManager wired to the test database."""
    return LogsManager(database_manager)


@pytest.fixture(name='split_path', params=[FILTER_PATH, JOIN_PATH])
def fixture_split_path(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Runs a test on the filter path and again on the join fallback."""
    if request.param == JOIN_PATH:
        monkeypatch.setattr(logs_helper, 'MAX_DELETED_OBJECT_IDS', JOIN_FORCING_CAP)

    return request.param


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one existing object and the six logs, and removes both after each test."""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    objects.insert_one({'public_id': EXISTING_OBJECT_ID})
    logs.insert_many([
        _log_doc(LOG_ID_EXISTING, EXISTING_OBJECT_ID),
        _log_doc(LOG_ID_EXISTING_SECOND, EXISTING_OBJECT_ID, action=LogAction.CREATE),
        _log_doc(LOG_ID_DELETED, DELETED_OBJECT_ID),
        _log_doc(LOG_ID_DELETE_ACTION, DELETED_OBJECT_ID, action=LogAction.DELETE),
        _log_doc(LOG_ID_OTHER_TYPE, EXISTING_OBJECT_ID, log_type=OTHER_LOG_TYPE),
        _log_doc(LOG_ID_NO_OBJECT_ID, None),
    ])
    yield
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    objects.delete_many({'public_id': EXISTING_OBJECT_ID})


def _criteria(logs_manager: LogsManager, object_exists: bool) -> dict[str, Any] | list[dict[str, Any]]:
    """The criteria of one side, as a route builds them."""
    return build_object_log_existence_query(logs_manager, object_exists)


def _own_ids(logs_manager: LogsManager, object_exists: bool) -> set[int]:
    """The seeded log ids an unpaged read of one side returns."""
    params = BuilderParameters(criteria=_criteria(logs_manager, object_exists), limit=0)
    return {log.public_id for log in logs_manager.iterate(params).results} & OWN_LOG_IDS


class TestThePath:
    """Which criteria each forced path produces - the guard that the parametrisation tests both."""

    def test_the_filter_path_builds_a_filter(self, logs_manager: LogsManager) -> None:
        """The deleted ids fit, so the page is a plain filter."""
        assert isinstance(_criteria(logs_manager, True), dict)

    def test_the_join_path_builds_a_pipeline(self, logs_manager: LogsManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Past the cap the split joins every log instead."""
        monkeypatch.setattr(logs_helper, 'MAX_DELETED_OBJECT_IDS', JOIN_FORCING_CAP)

        assert isinstance(_criteria(logs_manager, True), list)


class TestTheSplit:
    """Every seeded object log lands on exactly the side its object's existence says, on both paths."""

    def test_logs_of_an_existing_object_are_on_the_exists_side(
        self, logs_manager: LogsManager, split_path: str,
    ) -> None:
        """Both logs of the existing object, and nothing of the deleted one."""
        assert _own_ids(logs_manager, True) == {LOG_ID_EXISTING, LOG_ID_EXISTING_SECOND}, split_path

    def test_logs_of_a_deleted_object_are_on_the_notexists_side(
        self, logs_manager: LogsManager, split_path: str,
    ) -> None:
        """The edit log of the deleted object and the log naming no object - the delete log is excluded."""
        assert _own_ids(logs_manager, False) == {LOG_ID_DELETED, LOG_ID_NO_OBJECT_ID}, split_path

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_delete_logs_and_other_log_types_are_on_neither_side(
        self, logs_manager: LogsManager, object_exists: bool, split_path: str,
    ) -> None:
        """The entry condition filters them out on both paths."""
        ids = _own_ids(logs_manager, object_exists)

        assert LOG_ID_DELETE_ACTION not in ids, split_path
        assert LOG_ID_OTHER_TYPE not in ids, split_path

    def test_a_second_read_answers_the_same_split(self, logs_manager: LogsManager, split_path: str) -> None:
        """The split only reads; asking twice changes nothing."""
        first = (_own_ids(logs_manager, True), _own_ids(logs_manager, False))
        second = (_own_ids(logs_manager, True), _own_ids(logs_manager, False))

        assert first == second, split_path


class TestTheRows:
    """What a read of one side hands back."""

    def test_rows_bind_to_object_logs(self, logs_manager: LogsManager, split_path: str) -> None:
        """The joined field is not a log field and does not reach the model."""
        params = BuilderParameters(criteria=_criteria(logs_manager, True), limit=0)
        own = [log for log in logs_manager.iterate(params).results if log.public_id in OWN_LOG_IDS]

        assert own, split_path
        assert all(isinstance(log, CmdbObjectLog) for log in own)
        assert all(OBJECT_LOOKUP_FIELD not in CmdbObjectLog.to_json(log) for log in own)

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_a_paged_read_reports_the_whole_side(
        self, logs_manager: LogsManager, object_exists: bool, split_path: str,
    ) -> None:
        """The total is counted through the same criteria, so a page of one still reports every row."""
        query = _criteria(logs_manager, object_exists)
        unpaged = logs_manager.iterate(BuilderParameters(criteria=query, limit=0))
        paged = logs_manager.iterate(BuilderParameters(criteria=query, limit=PAGE_SIZE))

        assert len(paged.results) == PAGE_SIZE, split_path
        assert paged.total == unpaged.total == len(unpaged.results)


class TestTheDeletedObjectRead:
    """`read_deleted_object_ids` against MongoDB."""

    def test_names_the_deleted_object_and_not_the_existing_one(self, logs_manager: LogsManager) -> None:
        """Only an id no object carries is listed."""
        deleted = read_deleted_object_ids(logs_manager)

        assert DELETED_OBJECT_ID in deleted
        assert EXISTING_OBJECT_ID not in deleted

    def test_a_log_without_an_object_id_is_listed_as_none(self, logs_manager: LogsManager) -> None:
        """No object carries a null public_id, so the `$in` / `$nin` filter treats the log as "gone"."""
        assert None in read_deleted_object_ids(logs_manager)

    def test_lists_each_id_once(self, logs_manager: LogsManager) -> None:
        """Grouped by object id: two logs of one object name it once."""
        deleted = read_deleted_object_ids(logs_manager)

        assert len(deleted) == len(set(deleted))

    def test_is_read_off_the_object_id_index(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The unfiltered `$group` is a DISTINCT_SCAN on the object_id index: one key per object, no log loaded."""
        # The test session does not reconcile model indexes; a started installation has these
        database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).create_indexes(
            CmdbMetaLog.get_index_keys(),
        )

        explain: dict[str, Any] = database_manager.connector.get_database(database_name).command(
            'explain',
            {'aggregate': CmdbMetaLog.COLLECTION, 'pipeline': build_deleted_object_ids_pipeline(), 'cursor': {}},
            verbosity='queryPlanner',
        )

        assert DISTINCT_SCAN_STAGE in str(explain)
        assert OBJECT_ID_INDEX_NAME in str(explain)
