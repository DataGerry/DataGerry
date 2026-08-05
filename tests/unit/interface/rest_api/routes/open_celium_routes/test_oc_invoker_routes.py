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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with OcInvokerManager patched at the route module path - no external OpenCelium
HTTP, no Mongo. The app runs on-premise (cloud_mode/local_mode False). The AUTOMATIONS 403 gate is
covered by the functional automations-gating suite.

These pin the handler glue: the manager call (incl. the opsIncluded flag), the success payload and
the per-error abort mapping.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes import (
    get_all_oc_invokers,
    get_oc_invoker_by_name,
    check_oc_invoker_exists,
)
from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_routes'

INVOKER_NAME: str = 'DataGerry'

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='db_test', email='user@test.com', public_id=1)


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (handle_oc_errors / insert_request_user / verify_api_access)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> BaseCmdbApp:
    """An on-premise BaseCmdbApp (cloud_mode/local_mode False) with a stub database_manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = False
    app.local_mode = False

    return app


@pytest.fixture(name='invoker_manager')
def fixture_invoker_manager() -> MagicMock:
    """The OcInvokerManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_manager')
def fixture_patched_manager(invoker_manager: MagicMock) -> Any:
    """Patches OcInvokerManager at the route module path."""
    with patch(f'{ROUTE_PATH}.OcInvokerManager', return_value=invoker_manager):
        yield


# --------------------------------------------------- get_all_oc_invokers -------------------------------------------- #

class TestGetAllOcInvokers:
    """``get_all_oc_invokers`` returns all invokers, forwarding the opsIncluded flag."""

    def test_returns_all_invokers_default_ops(self, flask_app, invoker_manager, patched_manager) -> None:
        """With no query param, operations are included by default (True)."""
        del patched_manager
        invoker_manager.get_all_invokers.return_value = [{'name': INVOKER_NAME}]

        with flask_app.test_request_context('/invokers'):
            response = _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(True)

    def test_ops_included_false_disables_operations(self, flask_app, invoker_manager, patched_manager) -> None:
        """``?opsIncluded=false`` is parsed as False (guards the previous type=bool footgun)."""
        del patched_manager
        invoker_manager.get_all_invokers.return_value = []

        with flask_app.test_request_context('/invokers?opsIncluded=false'):
            response = _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_all_invokers.assert_called_once_with(False)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.get_all_invokers.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context('/invokers'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_invokers)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------- get_oc_invoker_by_name ------------------------------------------- #

class TestGetOcInvokerByName:
    """``get_oc_invoker_by_name`` returns a single invoker by name."""

    def test_returns_invoker(self, flask_app, invoker_manager, patched_manager) -> None:
        """The manager's invoker is returned with 200."""
        del patched_manager
        invoker_manager.get_invoker_by_name.return_value = {'name': INVOKER_NAME}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_invoker_by_name)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.get_invoker_by_name.assert_called_once_with(INVOKER_NAME)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.get_invoker_by_name.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_invoker_by_name)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ check_oc_invoker_exists ------------------------------------------- #

class TestCheckOcInvokerExists:
    """``check_oc_invoker_exists`` returns the manager's existence flag."""

    def test_returns_exists_flag(self, flask_app, invoker_manager, patched_manager) -> None:
        """The boolean from check_invoker_exists is returned with 200."""
        del patched_manager
        invoker_manager.check_invoker_exists.return_value = True

        with flask_app.test_request_context():
            response = _unwrap(check_oc_invoker_exists)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        invoker_manager.check_invoker_exists.assert_called_once_with(INVOKER_NAME)

    def test_get_error_returns_500(self, flask_app, invoker_manager, patched_manager) -> None:
        """An OcInvokerGetError maps to 500."""
        del patched_manager
        invoker_manager.check_invoker_exists.side_effect = OcInvokerGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_oc_invoker_exists)(name=INVOKER_NAME, request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
