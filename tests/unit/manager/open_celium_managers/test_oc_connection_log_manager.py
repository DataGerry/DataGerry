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
Unit tests for cmdb.manager.open_celium_managers.oc_connection_log_manager.OcConnectionLogManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each test stubs the connector verb with a fake response and asserts
the endpoint, the parsed 2xx body, and the OC error on a non-2xx response (delete raises rather than
returning False). No HTTP, no Mongo.
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_connection_log_manager import (
    OcConnectionLogManager,
    EXECUTION_URL,
    EXECUTION_LOG_LIST_URL,
    EXECUTION_LOG_URL,
)
from cmdb.errors.open_celium.connection_log import OcConnectionLogGetError, OcConnectionLogDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

TARGET_ID: int = 42
LOOP_INDEX: int = 3
CONNECTION_ID: int = 1
SCHEDULER_ID: int = 2
LOG_STATUS: str = 's'

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='log_manager')
def fixture_log_manager() -> OcConnectionLogManager:
    """An OcConnectionLogManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcConnectionLogManager(MagicMock(), 'db_test')


# ----------------------------------------------- get_details_method_or_operator ------------------------------------ #

class TestGetDetailsMethodOrOperator:
    """``get_details_method_or_operator`` GETs the element details endpoint."""

    def test_gets_and_returns_body(self, log_manager: OcConnectionLogManager) -> None:
        """A 2xx body is parsed and returned from the details endpoint."""
        log_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'detail': True})

        result = log_manager.get_details_method_or_operator(TARGET_ID)

        assert result == {'detail': True}
        log_manager.oc_connector.oc_get.assert_called_once_with(f"{EXECUTION_LOG_URL}/{TARGET_ID}/details")

    def test_non_2xx_raises_get_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx response raises OcConnectionLogGetError."""
        log_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogGetError):
            log_manager.get_details_method_or_operator(TARGET_ID)


# -------------------------------------------------- get_operator_children ------------------------------------------- #

class TestGetOperatorChildren:
    """``get_operator_children`` GETs the children endpoint with the loopIndex query."""

    def test_gets_with_loop_index_and_returns_body(self, log_manager: OcConnectionLogManager) -> None:
        """The loopIndex is appended to the children endpoint and the body returned."""
        log_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'children': []})

        result = log_manager.get_operator_children(TARGET_ID, LOOP_INDEX)

        assert result == {'children': []}
        log_manager.oc_connector.oc_get.assert_called_once_with(
            f"{EXECUTION_LOG_URL}/{TARGET_ID}/children?loopIndex={LOOP_INDEX}"
        )

    def test_non_2xx_raises_get_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx response raises OcConnectionLogGetError."""
        log_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogGetError):
            log_manager.get_operator_children(TARGET_ID, LOOP_INDEX)


# ----------------------------------------------------- get_flowcharts ----------------------------------------------- #

class TestGetFlowcharts:
    """``get_flowcharts`` GETs the execution children endpoint."""

    def test_gets_and_returns_body(self, log_manager: OcConnectionLogManager) -> None:
        """A 2xx body is parsed and returned from the children endpoint."""
        log_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'connectorName': 'c'}])

        result = log_manager.get_flowcharts(TARGET_ID)

        assert result == [{'connectorName': 'c'}]
        log_manager.oc_connector.oc_get.assert_called_once_with(f"{EXECUTION_LOG_URL}/{TARGET_ID}/children")

    def test_non_2xx_raises_get_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx response raises OcConnectionLogGetError."""
        log_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogGetError):
            log_manager.get_flowcharts(TARGET_ID)


# -------------------------------------------------- get_first_level_logs -------------------------------------------- #

class TestGetFirstLevelLogs:
    """``get_first_level_logs`` GETs the flowchart children endpoint."""

    def test_gets_and_returns_body(self, log_manager: OcConnectionLogManager) -> None:
        """A 2xx body is parsed and returned from the children endpoint."""
        log_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'logs': []})

        result = log_manager.get_first_level_logs(TARGET_ID)

        assert result == {'logs': []}
        log_manager.oc_connector.oc_get.assert_called_once_with(f"{EXECUTION_LOG_URL}/{TARGET_ID}/children")

    def test_non_2xx_raises_get_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx response raises OcConnectionLogGetError."""
        log_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogGetError):
            log_manager.get_first_level_logs(TARGET_ID)


# ----------------------------------------------------- get_log_list ------------------------------------------------- #

class TestGetLogList:
    """``get_log_list`` GETs the log-files endpoint with the connection/scheduler/status query."""

    def test_gets_with_query_and_returns_body(self, log_manager: OcConnectionLogManager) -> None:
        """The query params are appended and the body returned."""
        log_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'list': []})

        result = log_manager.get_log_list(CONNECTION_ID, SCHEDULER_ID, LOG_STATUS)

        assert result == {'list': []}
        log_manager.oc_connector.oc_get.assert_called_once_with(
            f"{EXECUTION_LOG_LIST_URL}?connectionId={CONNECTION_ID}&schedulerId={SCHEDULER_ID}&status={LOG_STATUS}"
        )

    def test_non_2xx_raises_get_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx response raises OcConnectionLogGetError."""
        log_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogGetError):
            log_manager.get_log_list(CONNECTION_ID, SCHEDULER_ID, LOG_STATUS)


# ------------------------------------------------------ delete_logs ------------------------------------------------- #

class TestDeleteLogs:
    """``delete_logs`` returns True on success and RAISES (not False) on failure."""

    def test_2xx_returns_true(self, log_manager: OcConnectionLogManager) -> None:
        """A 2xx delete returns True."""
        log_manager.oc_connector.oc_delete.return_value = _response(OK_STATUS)

        assert log_manager.delete_logs(TARGET_ID) is True
        log_manager.oc_connector.oc_delete.assert_called_once_with(f"{EXECUTION_URL}/{TARGET_ID}")

    def test_non_2xx_raises_delete_error(self, log_manager: OcConnectionLogManager) -> None:
        """A non-2xx delete raises OcConnectionLogDeleteError (it does not return False)."""
        log_manager.oc_connector.oc_delete.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionLogDeleteError):
            log_manager.delete_logs(TARGET_ID)
