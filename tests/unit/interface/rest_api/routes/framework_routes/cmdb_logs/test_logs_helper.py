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
Unit tests for the CmdbLog route helper ``build_object_logs_response``

Pure tests: no Mongo and no Flask app. The logs manager, BuilderParameters, GetMultiResponse and
CmdbObjectLog.to_json are patched, so only the helper's own wiring is exercised - that it builds
the BuilderParameters from the query + pagination, serializes every iterated row, forwards the
total/url/HEAD flag to GetMultiResponse, and returns its ``make_response`` output.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import (
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
    response_cls.assert_called_once_with(serialized, TOTAL_LOGS, params, REQUEST_URL, False)
    assert result is response_cls.return_value.make_response.return_value


@pytest.mark.parametrize('method,expected_head', [('GET', False), ('HEAD', True)])
def test_head_flag_reflects_request_method(method: str, expected_head: bool) -> None:
    """The GetMultiResponse body flag is True only for a HEAD request."""
    manager = _manager_returning([])
    params = _params()
    request = _request(method)

    with patch(f'{HELPER_PATH}.BuilderParameters'), \
         patch(f'{HELPER_PATH}.CmdbObjectLog.to_json'), \
         patch(f'{HELPER_PATH}.GetMultiResponse') as response_cls:
        build_object_logs_response(manager, QUERY, params, request, MagicMock())

    _, _, _, _, body_flag = response_cls.call_args.args
    assert body_flag is expected_head


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
