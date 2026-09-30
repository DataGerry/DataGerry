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
Unit tests for the CmdbLog route helpers

Pure tests: no Mongo and no Flask app.

* ``build_object_logs_response``: the logs manager, BuilderParameters, GetMultiResponse and
  CmdbObjectLog.to_json are patched, so only the helper's own wiring is exercised - that it builds
  the BuilderParameters from the query + pagination, serializes every iterated row, forwards the
  total/url/HEAD flag to GetMultiResponse, and returns its ``make_response`` output.
* ``build_object_log_existence_query``: the pipeline shape. Whether MongoDB splits the logs the way
  the shape promises is the functional log-route tests' job.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LogKey,
    LogQueryOperator,
    MONGO_ID_KEY,
    OBJECT_LOOKUP_FIELD,
    OBJECT_LOOKUP_FIRST_MATCH,
    OBJECT_LOOKUP_MAX_MATCHES,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import (
    build_object_log_existence_query,
    build_object_logs_response,
    resolve_log_users,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper'

QUERY: dict[str, Any] = {'object_id': 42}
REQUEST_URL: str = 'http://localhost/rest/logs/object/42'
TOTAL_LOGS: int = 2


def _params() -> MagicMock:
    """A CollectionParameters stand-in with the four fields the helper reads."""
    params = MagicMock()
    params.limit = 10
    params.skip = 0
    params.sort = 'public_id'
    params.order = 1
    return params


def _request(method: str = 'GET') -> MagicMock:
    """A Flask request stand-in exposing url + method; include_users defaults off."""
    request = MagicMock()
    request.url = REQUEST_URL
    request.method = method
    request.args.get.return_value = 'false'
    return request


def _manager_returning(rows: list[Any]) -> MagicMock:
    """A LogsManager mock whose ``iterate`` yields the given rows and a fixed total."""
    manager = MagicMock()
    iteration_result = MagicMock()
    iteration_result.results = rows
    iteration_result.total = TOTAL_LOGS
    manager.iterate.return_value = iteration_result
    return manager


def test_builds_params_serializes_rows_and_wraps_response() -> None:
    """The helper threads query+pagination into BuilderParameters and serializes each iterated row."""
    rows = [object(), object()]
    manager = _manager_returning(rows)
    params = _params()
    request = _request('GET')

    with patch(f'{HELPER_PATH}.BuilderParameters') as builder_cls, \
         patch(f'{HELPER_PATH}.CmdbObjectLog.to_json', side_effect=lambda row: {'row': id(row)}) as to_json_mock, \
         patch(f'{HELPER_PATH}.GetMultiResponse') as response_cls:
        result = build_object_logs_response(manager, QUERY, params, request, MagicMock())

    builder_cls.assert_called_once_with(QUERY, params.limit, params.skip, params.sort, params.order)
    manager.iterate.assert_called_once_with(builder_cls.return_value)
    assert to_json_mock.call_count == len(rows)

    serialized = [{'row': id(rows[0])}, {'row': id(rows[1])}]
    response_cls.assert_called_once_with(serialized, TOTAL_LOGS, params, REQUEST_URL, True)
    assert result is response_cls.return_value.make_response.return_value


@pytest.mark.parametrize('method,expected_body', [('GET', True), ('HEAD', False)])
def test_the_body_flag_reflects_the_request_method(method: str, expected_body: bool) -> None:
    """
    The GetMultiResponse body flag is True for everything BUT a HEAD request

    Asserted the other way round it would read: this helper derives the flag as
    `request.method == HTTP_HEAD_METHOD`, so a plain GET asked for a bodyless answer - harmless only
    which an inert flag would hide. The rule comes from
    `routes_helper.request_wants_body`.
    """
    manager = _manager_returning([])
    params = _params()
    request = _request(method)

    with patch(f'{HELPER_PATH}.BuilderParameters'), \
         patch(f'{HELPER_PATH}.CmdbObjectLog.to_json'), \
         patch(f'{HELPER_PATH}.GetMultiResponse') as response_cls:
        build_object_logs_response(manager, QUERY, params, request, MagicMock())

    _, _, _, _, body_flag = response_cls.call_args.args
    assert body_flag is expected_body


class TestResolveLogUsers:
    """resolve_log_users dedupes user_ids, keys by stringified public_id, and omits missing users."""

    def test_dedupes_ids_and_keys_by_public_id(self) -> None:
        """Distinct user_ids are queried once; the map is keyed by the stringified public_id."""
        manager = MagicMock()
        manager.get_minimal_users_by_ids.return_value = [
            {'public_id': 1, 'first_name': 'Ada', 'last_name': 'Lovelace', 'image': None, 'user_name': 'ada'},
            {'public_id': 2, 'first_name': '', 'last_name': '', 'image': None, 'user_name': 'grace'},
        ]
        logs = [{'user_id': 1}, {'user_id': 2}, {'user_id': 1}]

        result = resolve_log_users(manager, logs)

        assert set(manager.get_minimal_users_by_ids.call_args.args[0]) == {1, 2}
        assert set(result) == {'1', '2'}
        assert result['1']['user_name'] == 'ada'

    def test_omits_missing_users_and_skips_null_ids(self) -> None:
        """A user_id with no matching user is omitted; None/absent user_ids are not queried."""
        manager = MagicMock()
        manager.get_minimal_users_by_ids.return_value = [
            {'public_id': 1, 'first_name': 'Ada', 'last_name': 'Lovelace', 'image': None, 'user_name': 'ada'},
        ]
        logs = [{'user_id': 1}, {'user_id': 2}, {'user_id': None}, {}]

        result = resolve_log_users(manager, logs)

        assert set(manager.get_minimal_users_by_ids.call_args.args[0]) == {1, 2}
        assert set(result) == {'1'}

    def test_no_user_ids_returns_empty_without_query(self) -> None:
        """With no resolvable user_ids the manager is not queried and an empty map is returned."""
        manager = MagicMock()

        result = resolve_log_users(manager, [{'user_id': None}, {}])

        assert result == {}
        manager.get_minimal_users_by_ids.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        build_object_log_existence_query                                              #
# -------------------------------------------------------------------------------------------------------------------- #

class TestObjectLogExistenceQuery:
    """The pipeline behind ``/logs/object/exists`` (True) and ``/logs/object/notexists`` (False)."""

    @staticmethod
    def _lookup(pipeline: list[dict[str, Any]]) -> dict[str, Any]:
        """The body of the pipeline's one ``$lookup`` stage."""
        lookups = [stage['$lookup'] for stage in pipeline if '$lookup' in stage]
        assert len(lookups) == 1
        return lookups[0]

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_only_object_logs_that_are_not_deletes_enter(self, object_exists: bool) -> None:
        """A delete log has no object by construction; letting it in would fill /notexists with them."""
        first_stage = build_object_log_existence_query(object_exists)[0]

        assert first_stage == {'$match': {
            LogKey.LOG_TYPE.value: OBJECT_LOG_TYPE,
            LogKey.ACTION.value: {LogQueryOperator.NE.value: LogAction.DELETE.value},
        }}

    def test_the_join_matches_the_logs_object_by_public_id(self) -> None:
        """A log names its object by `object_id`; the object carries that value as `public_id`."""
        lookup = self._lookup(build_object_log_existence_query())

        assert lookup['from'] == CmdbObject.COLLECTION
        assert lookup['localField'] == LogKey.OBJECT_ID.value
        assert lookup['foreignField'] == LogKey.PUBLIC_ID.value
        assert lookup['as'] == OBJECT_LOOKUP_FIELD

    def test_the_join_loads_one_id_only_document(self) -> None:
        """Only existence matters - a full object per log would haul every page's objects into memory."""
        lookup = self._lookup(build_object_log_existence_query())

        assert lookup['pipeline'] == [
            {'$limit': OBJECT_LOOKUP_MAX_MATCHES},
            {'$project': {MONGO_ID_KEY: 1}},
        ]

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_the_split_reads_the_first_joined_element(self, object_exists: bool) -> None:
        """The last stage decides the side: element 0 of the joined array is there exactly when the object is."""
        last_stage = build_object_log_existence_query(object_exists)[-1]

        assert last_stage == {'$match': {OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: object_exists}}}

    def test_the_default_selects_existing_objects(self) -> None:
        """`/logs/object/exists` calls it without an argument."""
        assert build_object_log_existence_query() == build_object_log_existence_query(True)

    def test_the_stages_run_filter_join_split(self) -> None:
        """Filtering first keeps the per-log join off the delete logs; no `$unwind` is needed for the split."""
        operators = [next(iter(stage)) for stage in build_object_log_existence_query()]

        assert operators == ['$match', '$lookup', '$match']

    def test_the_first_joined_element_path_names_the_join_field(self) -> None:
        """The split path and the join target must name the same field, or every log lands on one side."""
        assert OBJECT_LOOKUP_FIRST_MATCH == f'{OBJECT_LOOKUP_FIELD}.0'
