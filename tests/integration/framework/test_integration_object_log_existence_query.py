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
Integration tests for `build_object_log_existence_query` run through `LogsManager.iterate`

The unit suite pins the pipeline's shape; here MongoDB runs it. Each test seeds its own logs and
objects in a dedicated id band and asserts on those ids only, so logs other tests leave in the
collection do not matter:

- a log whose object exists lands on the "exists" side only, a log whose object is gone on the
  "notexists" side only
- delete-action logs and logs of another log type land on neither side
- the rows bind to CmdbObjectLog without the joined field
- the total is counted through the same pipeline, so a paged read reports the whole side
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
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import OBJECT_LOOKUP_FIELD
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import build_object_log_existence_query
# -------------------------------------------------------------------------------------------------------------------- #

EXISTING_OBJECT_ID: int = 77001
DELETED_OBJECT_ID: int = 77002

LOG_ID_EXISTING: int = 77101
LOG_ID_DELETED: int = 77102
LOG_ID_DELETE_ACTION: int = 77103
LOG_ID_OTHER_TYPE: int = 77104
LOG_ID_EXISTING_SECOND: int = 77105

ALL_LOG_IDS: list[int] = [
    LOG_ID_EXISTING, LOG_ID_DELETED, LOG_ID_DELETE_ACTION, LOG_ID_OTHER_TYPE, LOG_ID_EXISTING_SECOND,
]
OWN_LOG_IDS: set[int] = set(ALL_LOG_IDS)

OTHER_LOG_TYPE: str = CmdbMetaLog.__name__
PAGE_SIZE: int = 1

LOG_VERSION: str = '1.0.0'
USER_ID: int = 1
USER_NAME: str = 'admin'


def _log_doc(public_id: int,
             object_id: int,
             action: LogAction = LogAction.EDIT,
             log_type: str = OBJECT_LOG_TYPE) -> dict[str, Any]:
    """Builds a stored object-log document for direct insertion."""
    return {
        'public_id': public_id,
        'log_type': log_type,
        'action': action.value,
        'action_name': action.name,
        'object_id': object_id,
        'version': LOG_VERSION,
        'user_id': USER_ID,
        'user_name': USER_NAME,
        'changes': [],
        'comment': None,
        'render_state': None,
    }


@pytest.fixture(name='logs_manager')
def fixture_logs_manager(database_manager: MongoDatabaseManager) -> LogsManager:
    """Provides a LogsManager wired to the test database."""
    return LogsManager(database_manager)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one existing object and the five logs, and removes both after each test."""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    objects.insert_one({'public_id': EXISTING_OBJECT_ID})
    logs.insert_many([
        _log_doc(LOG_ID_EXISTING, EXISTING_OBJECT_ID),
        _log_doc(LOG_ID_EXISTING_SECOND, EXISTING_OBJECT_ID, action=LogAction.CREATE),
        _log_doc(LOG_ID_DELETED, DELETED_OBJECT_ID),
        _log_doc(LOG_ID_DELETE_ACTION, DELETED_OBJECT_ID, action=LogAction.DELETE),
        _log_doc(LOG_ID_OTHER_TYPE, EXISTING_OBJECT_ID, log_type=OTHER_LOG_TYPE),
    ])
    yield
    logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
    objects.delete_many({'public_id': EXISTING_OBJECT_ID})


def _own_ids(logs_manager: LogsManager, object_exists: bool) -> set[int]:
    """The seeded log ids an unpaged read of one side returns."""
    params = BuilderParameters(criteria=build_object_log_existence_query(object_exists), limit=0)
    return {log.public_id for log in logs_manager.iterate(params).results} & OWN_LOG_IDS


class TestTheSplit:
    """Every seeded object log lands on exactly the side its object's existence says."""

    def test_logs_of_an_existing_object_are_on_the_exists_side(self, logs_manager: LogsManager) -> None:
        """Both logs of the existing object, and nothing of the deleted one."""
        assert _own_ids(logs_manager, True) == {LOG_ID_EXISTING, LOG_ID_EXISTING_SECOND}

    def test_logs_of_a_deleted_object_are_on_the_notexists_side(self, logs_manager: LogsManager) -> None:
        """Only the edit log of the deleted object - its delete log is excluded."""
        assert _own_ids(logs_manager, False) == {LOG_ID_DELETED}

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_delete_logs_and_other_log_types_are_on_neither_side(
        self, logs_manager: LogsManager, object_exists: bool,
    ) -> None:
        """The first stage filters them out before the join runs."""
        ids = _own_ids(logs_manager, object_exists)

        assert LOG_ID_DELETE_ACTION not in ids
        assert LOG_ID_OTHER_TYPE not in ids


class TestTheRows:
    """What a read of one side hands back."""

    def test_rows_bind_to_object_logs(self, logs_manager: LogsManager) -> None:
        """The joined field is not a log field and does not reach the model."""
        params = BuilderParameters(criteria=build_object_log_existence_query(True), limit=0)
        own = [log for log in logs_manager.iterate(params).results if log.public_id in OWN_LOG_IDS]

        assert own
        assert all(isinstance(log, CmdbObjectLog) for log in own)
        assert all(OBJECT_LOOKUP_FIELD not in CmdbObjectLog.to_json(log) for log in own)

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_a_paged_read_reports_the_whole_side(self, logs_manager: LogsManager, object_exists: bool) -> None:
        """The total is counted through the same pipeline, so a page of one still reports every row."""
        query = build_object_log_existence_query(object_exists)
        unpaged = logs_manager.iterate(BuilderParameters(criteria=query, limit=0))
        paged = logs_manager.iterate(BuilderParameters(criteria=query, limit=PAGE_SIZE))

        assert len(paged.results) == PAGE_SIZE
        assert paged.total == unpaged.total == len(unpaged.results)
