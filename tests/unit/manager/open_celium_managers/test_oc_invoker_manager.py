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
Unit tests for cmdb.manager.open_celium_managers.oc_invoker_manager.OcInvokerManager

The manager wraps an OcApiConnector talking to OpenCelium over HTTP; the connector is patched out at
the OcBaseManager module path. Each test stubs oc_get with a fake response and asserts the endpoint,
the parsed 2xx body, the name-guard, the opsIncluded routing, and the OcInvokerGetError on a non-2xx
response. No HTTP, no Mongo.
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_invoker_manager import (
    OcInvokerManager,
    INVOKER_URL,
    ALL_INVOKERS_URL,
    INVOKER_EXISTS_URL,
)
from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

INVOKER_NAME: str = 'DataGerry'

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='invoker_manager')
def fixture_invoker_manager() -> OcInvokerManager:
    """An OcInvokerManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcInvokerManager(MagicMock(), 'db_test')


# -------------------------------------------------- get_invoker_by_name --------------------------------------------- #

class TestGetInvokerByName:
    """``get_invoker_by_name`` GETs /invoker/<name> and guards a missing name."""

    def test_missing_name_raises_without_http(self, invoker_manager: OcInvokerManager) -> None:
        """A falsy name raises OcInvokerGetError before any HTTP call."""
        with pytest.raises(OcInvokerGetError):
            invoker_manager.get_invoker_by_name('')

        invoker_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_and_returns_body(self, invoker_manager: OcInvokerManager) -> None:
        """A 2xx body is parsed and returned from /invoker/<name>."""
        invoker_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'name': INVOKER_NAME})

        result = invoker_manager.get_invoker_by_name(INVOKER_NAME)

        assert result == {'name': INVOKER_NAME}
        invoker_manager.oc_connector.oc_get.assert_called_once_with(f"{INVOKER_URL}/{INVOKER_NAME}")

    def test_non_2xx_raises_get_error(self, invoker_manager: OcInvokerManager) -> None:
        """A non-2xx response raises OcInvokerGetError."""
        invoker_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcInvokerGetError):
            invoker_manager.get_invoker_by_name(INVOKER_NAME)


# -------------------------------------------------- check_invoker_exists -------------------------------------------- #

class TestCheckInvokerExists:
    """``check_invoker_exists`` returns the 'result' flag from the exists endpoint."""

    def test_missing_name_raises_without_http(self, invoker_manager: OcInvokerManager) -> None:
        """A falsy name raises OcInvokerGetError before any HTTP call."""
        with pytest.raises(OcInvokerGetError):
            invoker_manager.check_invoker_exists('')

        invoker_manager.oc_connector.oc_get.assert_not_called()

    def test_returns_result_flag(self, invoker_manager: OcInvokerManager) -> None:
        """The 'result' value from the body is returned."""
        invoker_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'result': True})

        assert invoker_manager.check_invoker_exists(INVOKER_NAME) is True
        invoker_manager.oc_connector.oc_get.assert_called_once_with(f"{INVOKER_EXISTS_URL}/{INVOKER_NAME}")

    def test_missing_result_key_returns_none(self, invoker_manager: OcInvokerManager) -> None:
        """A 2xx body without a 'result' key returns None instead of raising KeyError (uses .get)."""
        invoker_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {})

        assert invoker_manager.check_invoker_exists(INVOKER_NAME) is None

    def test_non_2xx_raises_get_error(self, invoker_manager: OcInvokerManager) -> None:
        """A non-2xx response raises OcInvokerGetError."""
        invoker_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcInvokerGetError):
            invoker_manager.check_invoker_exists(INVOKER_NAME)


# --------------------------------------------------- get_all_invokers ----------------------------------------------- #

class TestGetAllInvokers:
    """``get_all_invokers`` GETs /invoker/all and toggles the opsIncluded query."""

    def test_default_includes_operations(self, invoker_manager: OcInvokerManager) -> None:
        """By default the plain all-invokers endpoint is queried (operations included)."""
        invoker_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [{'name': INVOKER_NAME}])

        result = invoker_manager.get_all_invokers()

        assert result == [{'name': INVOKER_NAME}]
        invoker_manager.oc_connector.oc_get.assert_called_once_with(ALL_INVOKERS_URL)

    def test_without_operations_appends_query(self, invoker_manager: OcInvokerManager) -> None:
        """With with_operations=False the opsIncluded=false query is appended."""
        invoker_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, [])

        invoker_manager.get_all_invokers(with_operations=False)

        invoker_manager.oc_connector.oc_get.assert_called_once_with(f"{ALL_INVOKERS_URL}?opsIncluded=false")

    def test_non_2xx_raises_get_error(self, invoker_manager: OcInvokerManager) -> None:
        """A non-2xx response raises OcInvokerGetError."""
        invoker_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcInvokerGetError):
            invoker_manager.get_all_invokers()
