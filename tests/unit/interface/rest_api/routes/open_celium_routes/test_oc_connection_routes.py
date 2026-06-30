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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_routes

Each handler is unwrapped past its decorator chain (handle_oc_errors / insert_request_user /
verify_api_access / protect) and driven inside a BaseCmdbApp test_request_context. The three
managers the handlers construct (OcConnectionManager, DgServicePortalManager, CachedUserManager) are
patched at the route module path, so no external OpenCelium HTTP call is made and no Mongo is
touched. The app runs on-premise (cloud_mode/local_mode False), so the cloud title-mapping and
Service-Portal branches are skipped - those belong to a cloud-mode suite.

The whole OpenCelium surface is gated behind LicenseFeature.AUTOMATIONS by a blueprint-level
before_request; that 403 path is covered by the functional automations-gating suite. Calling the
unwrapped handler directly bypasses the blueprint dispatch, so these tests pin the handler glue:
the manager call, the success payload, the duplicate-name 400 and the per-error abort mapping.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_routes import (
    create_oc_connection,
    test_oc_connection as run_test_oc_connection,  # aliased: a 'test_'-prefixed import is collected by pytest
    oc_send_to_remote_api,
    get_oc_connection,
    update_oc_connection,
)
from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
    OcConnectionUpdateError,
    OcConnectionTestError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_routes'

CONNECTION_ID: int = 5
CHANNEL_ID: int = 3
CONNECTION_TITLE: str = 'my-connection'

REQUEST_USER: SimpleNamespace = SimpleNamespace(database='db_test', email='user@test.com', public_id=1)


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (handle_oc_errors / insert_request_user / verify_api_access / protect)."""
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


@pytest.fixture(name='oc_manager')
def fixture_oc_manager() -> MagicMock:
    """The OcConnectionManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_managers')
def fixture_patched_managers(oc_manager: MagicMock) -> Any:
    """Patches the three managers the connection handlers construct at the route module path."""
    with patch(f'{ROUTE_PATH}.OcConnectionManager', return_value=oc_manager), \
         patch(f'{ROUTE_PATH}.DgServicePortalManager', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.CachedUserManager', return_value=MagicMock()):
        yield


# --------------------------------------------------- create_oc_connection ------------------------------------------- #

class TestCreateOcConnection:
    """``create_oc_connection`` rejects duplicates, otherwise forwards to the manager."""

    def test_creates_and_returns_connection(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A unique title is created in OpenCelium and the created connection is returned."""
        del patched_managers
        oc_manager.check_connection_name_exists.return_value = False
        oc_manager.create_connection.return_value = {'connectionId': str(CONNECTION_ID), 'title': CONNECTION_TITLE}

        with flask_app.test_request_context(json={'title': CONNECTION_TITLE}):
            response = _unwrap(create_oc_connection)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.create_connection.assert_called_once()

    def test_duplicate_title_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An already-existing connection title aborts with 400 before creating anything."""
        del patched_managers
        oc_manager.check_connection_name_exists.return_value = True

        with flask_app.test_request_context(json={'title': CONNECTION_TITLE}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_connection)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        oc_manager.create_connection.assert_not_called()

    def test_create_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectionCreateError from the manager is mapped to 400."""
        del patched_managers
        oc_manager.check_connection_name_exists.return_value = False
        oc_manager.create_connection.side_effect = OcConnectionCreateError('boom')

        with flask_app.test_request_context(json={'title': CONNECTION_TITLE}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_connection)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------- test_oc_connection -------------------------------------------- #

class TestTestOcConnection:
    """``test_oc_connection`` forwards the payload + channel to the manager."""

    def test_returns_test_result(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The manager's test result is returned with 200."""
        del patched_managers
        oc_manager.test_connection.return_value = {'success': True}

        with flask_app.test_request_context(json={'data': 1}):
            response = _unwrap(run_test_oc_connection)(request_user=REQUEST_USER, channel_id=CHANNEL_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.test_connection.assert_called_once_with({'data': 1}, CHANNEL_ID)

    def test_test_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectionTestError is mapped to 400."""
        del patched_managers
        oc_manager.test_connection.side_effect = OcConnectionTestError('boom')

        with flask_app.test_request_context(json={'data': 1}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(run_test_oc_connection)(request_user=REQUEST_USER, channel_id=CHANNEL_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------- oc_send_to_remote_api ------------------------------------------- #

class TestOcSendToRemoteApi:
    """``oc_send_to_remote_api`` forwards the payload to the manager."""

    def test_returns_remote_response(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The remote API response is returned with 200."""
        del patched_managers
        oc_manager.send_to_remote_api.return_value = {'echo': 'ok'}

        with flask_app.test_request_context(json={'payload': 1}):
            response = _unwrap(oc_send_to_remote_api)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.send_to_remote_api.assert_called_once_with({'payload': 1})

    def test_remote_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectionCreateError from the remote call (what the manager raises) is mapped to 400."""
        del patched_managers
        oc_manager.send_to_remote_api.side_effect = OcConnectionCreateError('boom')

        with flask_app.test_request_context(json={'payload': 1}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(oc_send_to_remote_api)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ----------------------------------------------------- get_oc_connection -------------------------------------------- #

class TestGetOcConnection:
    """``get_oc_connection`` returns the connection (no cloud validation on-premise)."""

    def test_returns_connection(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The manager's connection is returned with 200."""
        del patched_managers
        oc_manager.get_connection.return_value = {'connectionId': CONNECTION_ID, 'title': CONNECTION_TITLE}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_connection)(request_user=REQUEST_USER, connection_id=CONNECTION_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connection.assert_called_once_with(CONNECTION_ID)

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectionGetError is mapped to 500."""
        del patched_managers
        oc_manager.get_connection.side_effect = OcConnectionGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_connection)(request_user=REQUEST_USER, connection_id=CONNECTION_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------- update_oc_connection ------------------------------------------ #

class TestUpdateOcConnection:
    """``update_oc_connection`` forwards the payload to the manager (no cloud validation on-premise)."""

    def test_updates_and_returns_connection(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The updated connection is returned with 200."""
        del patched_managers
        oc_manager.update_connection.return_value = {'connectionId': CONNECTION_ID, 'title': 'renamed'}

        with flask_app.test_request_context(json={'title': 'renamed'}):
            response = _unwrap(update_oc_connection)(request_user=REQUEST_USER, connection_id=CONNECTION_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.update_connection.assert_called_once_with({'title': 'renamed'}, CONNECTION_ID)

    def test_update_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectionUpdateError is mapped to 400."""
        del patched_managers
        oc_manager.update_connection.side_effect = OcConnectionUpdateError('boom')

        with flask_app.test_request_context(json={'title': 'renamed'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_oc_connection)(request_user=REQUEST_USER, connection_id=CONNECTION_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
