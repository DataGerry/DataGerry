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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_connector_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with the managers (OcConnectorManager, DgServicePortalManager,
CachedUserManager) patched at the route module path - no external OpenCelium HTTP, no Mongo. The app
runs on-premise (cloud_mode/local_mode False), so the cloud title-mapping / Service-Portal branches
are skipped and the local code paths are exercised. The AUTOMATIONS 403 gate is covered by the
functional automations-gating suite; calling the unwrapped handlers bypasses blueprint dispatch.

These pin the handler glue: the manager call, the success payload, the reserved-name / master-password
business aborts and the per-error abort mapping.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.open_celium.oc_constants import OC_INTERNAL_CONNECTOR_NAME
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connector_routes import (
    create_oc_connector,
    check_oc_connector,
    check_oc_connector_master_pw,
    get_oc_connector,
    check_master_password,
    check_master_password_exists,
    get_all_oc_connectors,
    check_oc_connector_exists,
    update_oc_connector,
    delete_oc_connector,
    create_oc_internal_connector,
    update_internal_oc_connector,
    get_internal_oc_connector,
)
from cmdb.errors.open_celium.connector import (
    OcConnectorCreateError,
    OcConnectorGetError,
    OcConnectorUpdateError,
)
from cmdb.errors.open_celium import OcMasterPwNotSetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_connector_routes'

CONNECTOR_ID: int = 7
MASTER_PW: str = 'secret-pw'
MASTER_PW_HEADER: str = 'X-Master-Password'

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
    """The OcConnectorManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_managers')
def fixture_patched_managers(oc_manager: MagicMock) -> Any:
    """Patches the three managers the connector handlers construct at the route module path."""
    with patch(f'{ROUTE_PATH}.OcConnectorManager', return_value=oc_manager), \
         patch(f'{ROUTE_PATH}.DgServicePortalManager', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.CachedUserManager', return_value=MagicMock()):
        yield


# --------------------------------------------------- create_oc_connector -------------------------------------------- #

class TestCreateOcConnector:
    """``create_oc_connector`` rejects the reserved internal name, otherwise forwards to the manager."""

    def test_creates_and_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A normal title is created and the created connector is returned."""
        del patched_managers
        oc_manager.create_connector.return_value = {'connectorId': CONNECTOR_ID, 'title': 'my-connector'}

        with flask_app.test_request_context(json={'title': 'my-connector'}):
            response = _unwrap(create_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.create_connector.assert_called_once()

    def test_reserved_internal_name_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The reserved internal connector name is refused with 400 before creating anything."""
        del patched_managers

        with flask_app.test_request_context(json={'title': OC_INTERNAL_CONNECTOR_NAME}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        oc_manager.create_connector.assert_not_called()

    def test_create_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorCreateError maps to 400 (now consistent with the other create routes)."""
        del patched_managers
        oc_manager.create_connector.side_effect = OcConnectorCreateError('boom')

        with flask_app.test_request_context(json={'title': 'my-connector'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ---------------------------------------------------- check_oc_connector -------------------------------------------- #

class TestCheckOcConnector:
    """``check_oc_connector`` returns the manager's credential-check result."""

    def test_returns_check_result(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The boolean from check_connector is returned with 200."""
        del patched_managers
        oc_manager.check_connector.return_value = True

        with flask_app.test_request_context(json={'invoker': 'x'}):
            response = _unwrap(check_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.check_connector.assert_called_once_with({'invoker': 'x'})


# ------------------------------------------------ check_oc_connector_master_pw -------------------------------------- #

class TestCheckOcConnectorMasterPw:
    """``check_oc_connector_master_pw`` validates the master password (local mode)."""

    def test_invalid_password_returns_403(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An invalid master password aborts with 403."""
        del patched_managers
        oc_manager.check_master_pw.return_value = False

        with flask_app.test_request_context(json={'password': MASTER_PW}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_oc_connector_master_pw)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_valid_password_without_connector_id_returns_true(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A valid password and no connectorId returns True (password-only check)."""
        del patched_managers
        oc_manager.check_master_pw.return_value = True

        with flask_app.test_request_context(json={'password': MASTER_PW}):
            response = _unwrap(check_oc_connector_master_pw)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK

    def test_valid_password_with_connector_id_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A valid password with a connectorId returns the retrieved connector."""
        del patched_managers
        oc_manager.check_master_pw.return_value = True
        oc_manager.get_connector.return_value = {'connectorId': CONNECTOR_ID}

        with flask_app.test_request_context(json={'password': MASTER_PW, 'connectorId': CONNECTOR_ID}):
            response = _unwrap(check_oc_connector_master_pw)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connector.assert_called_once_with(CONNECTOR_ID, MASTER_PW)

    def test_master_pw_not_set_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcMasterPwNotSetError maps to 400."""
        del patched_managers
        oc_manager.check_master_pw.side_effect = OcMasterPwNotSetError('boom')

        with flask_app.test_request_context(json={'password': MASTER_PW}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_oc_connector_master_pw)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError while retrieving the connector maps to 500."""
        del patched_managers
        oc_manager.check_master_pw.return_value = True
        oc_manager.get_connector.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context(json={'password': MASTER_PW, 'connectorId': CONNECTOR_ID}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_oc_connector_master_pw)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------------- get_oc_connector --------------------------------------------- #

class TestGetOcConnector:
    """``get_oc_connector`` retrieves a connector, optionally validating a header master password."""

    def test_without_master_password_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """With no master-password header the connector is fetched by id alone."""
        del patched_managers
        oc_manager.get_connector.return_value = {'connectorId': CONNECTOR_ID}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connector.assert_called_once_with(CONNECTOR_ID)

    def test_with_valid_master_password_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A valid header master password is checked and the connector fetched with it."""
        del patched_managers
        oc_manager.check_master_pw.return_value = True
        oc_manager.get_connector.return_value = {'connectorId': CONNECTOR_ID}

        with flask_app.test_request_context(headers={MASTER_PW_HEADER: MASTER_PW}):
            response = _unwrap(get_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connector.assert_called_once_with(CONNECTOR_ID, MASTER_PW)

    def test_invalid_master_password_returns_403(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An invalid header master password aborts with 403."""
        del patched_managers
        oc_manager.check_master_pw.return_value = False

        with flask_app.test_request_context(headers={MASTER_PW_HEADER: MASTER_PW}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError maps to 500."""
        del patched_managers
        oc_manager.get_connector.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- check_master_password ------------------------------------------ #

class TestCheckMasterPassword:
    """``check_master_password`` requires the header and forwards to the manager."""

    def test_missing_header_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A missing master-password header aborts with 400."""
        del patched_managers, oc_manager

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_master_password)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_returns_manager_result(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The manager's raw check result is returned with 200."""
        del patched_managers
        oc_manager.check_master_pw.return_value = True

        with flask_app.test_request_context(headers={MASTER_PW_HEADER: MASTER_PW}):
            response = _unwrap(check_master_password)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.check_master_pw.assert_called_once_with(MASTER_PW, True)

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError maps to 500."""
        del patched_managers
        oc_manager.check_master_pw.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context(headers={MASTER_PW_HEADER: MASTER_PW}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_master_password)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ check_master_password_exists -------------------------------------- #

class TestCheckMasterPasswordExists:
    """``check_master_password_exists`` forwards to the manager."""

    def test_returns_manager_result(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The existence result is returned with 200."""
        del patched_managers
        oc_manager.check_master_pw_exists.return_value = {'exists': True}

        with flask_app.test_request_context():
            response = _unwrap(check_master_password_exists)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.check_master_pw_exists.assert_called_once_with()

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError maps to 500."""
        del patched_managers
        oc_manager.check_master_pw_exists.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(check_master_password_exists)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# --------------------------------------------------- get_all_oc_connectors ------------------------------------------ #

class TestGetAllOcConnectors:
    """``get_all_oc_connectors`` returns all connectors (local mode)."""

    def test_returns_all_connectors(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The local get_all_connectors result is returned with 200."""
        del patched_managers
        oc_manager.get_all_connectors.return_value = [{'connectorId': CONNECTOR_ID}]

        with flask_app.test_request_context():
            response = _unwrap(get_all_oc_connectors)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_all_connectors.assert_called_once_with()

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError maps to 500."""
        del patched_managers
        oc_manager.get_all_connectors.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_all_oc_connectors)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------- check_oc_connector_exists ---------------------------------------- #

class TestCheckOcConnectorExists:
    """``check_oc_connector_exists`` returns the manager's existence flag."""

    def test_returns_exists_flag(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The boolean from connector_exists is returned with 200."""
        del patched_managers
        oc_manager.connector_exists.return_value = True

        with flask_app.test_request_context():
            response = _unwrap(check_oc_connector_exists)(request_user=REQUEST_USER, title='my-connector')

        assert response.status_code == HTTPStatus.OK
        oc_manager.connector_exists.assert_called_once_with('my-connector')


# --------------------------------------------------- update_oc_connector -------------------------------------------- #

class TestUpdateOcConnector:
    """``update_oc_connector`` forwards the payload to the manager (local mode)."""

    def test_updates_and_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The updated connector is returned with 200."""
        del patched_managers
        oc_manager.update_connector.return_value = {'connectorId': CONNECTOR_ID, 'title': 'renamed'}

        with flask_app.test_request_context(json={'title': 'renamed'}):
            response = _unwrap(update_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.update_connector.assert_called_once_with({'title': 'renamed'}, CONNECTOR_ID)

    def test_update_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorUpdateError maps to 400."""
        del patched_managers
        oc_manager.update_connector.side_effect = OcConnectorUpdateError('boom')

        with flask_app.test_request_context(json={'title': 'renamed'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# --------------------------------------------------- delete_oc_connector -------------------------------------------- #

class TestDeleteOcConnector:
    """``delete_oc_connector`` returns the manager's delete result (local mode)."""

    def test_returns_delete_result(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The boolean from delete_connector is returned with 200."""
        del patched_managers
        oc_manager.delete_connector.return_value = True

        with flask_app.test_request_context():
            response = _unwrap(delete_oc_connector)(request_user=REQUEST_USER, connector_id=CONNECTOR_ID)

        assert response.status_code == HTTPStatus.OK
        oc_manager.delete_connector.assert_called_once_with(CONNECTOR_ID)


# ------------------------------------------------ create_oc_internal_connector -------------------------------------- #

class TestCreateOcInternalConnector:
    """``create_oc_internal_connector`` creates the reserved internal connector."""

    def test_creates_and_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The internal connector is created with the reserved title and returned."""
        del patched_managers
        oc_manager.create_connector.return_value = {'connectorId': CONNECTOR_ID, 'title': OC_INTERNAL_CONNECTOR_NAME}

        with flask_app.test_request_context(json={}):
            response = _unwrap(create_oc_internal_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        assert oc_manager.create_connector.call_args.args[0]['title'] == OC_INTERNAL_CONNECTOR_NAME

    def test_create_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorCreateError maps to 400 (the internal-create contract)."""
        del patched_managers
        oc_manager.create_connector.side_effect = OcConnectorCreateError('boom')

        with flask_app.test_request_context(json={}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(create_oc_internal_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------ update_internal_oc_connector -------------------------------------- #

class TestUpdateInternalOcConnector:
    """``update_internal_oc_connector`` locates the internal connector by name, then updates it."""

    def test_updates_and_returns_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """The located internal connector is updated and returned."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = {'connectorId': CONNECTOR_ID}
        oc_manager.update_connector.return_value = {'connectorId': CONNECTOR_ID, 'title': OC_INTERNAL_CONNECTOR_NAME}

        with flask_app.test_request_context(json={}):
            response = _unwrap(update_internal_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.update_connector.assert_called_once_with({'title': OC_INTERNAL_CONNECTOR_NAME}, CONNECTOR_ID)

    def test_missing_internal_connector_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """When no internal connector exists the route aborts with 400."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = None

        with flask_app.test_request_context(json={}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_internal_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        oc_manager.update_connector.assert_not_called()

    def test_update_error_returns_400(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorUpdateError maps to 400."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = {'connectorId': CONNECTOR_ID}
        oc_manager.update_connector.side_effect = OcConnectorUpdateError('boom')

        with flask_app.test_request_context(json={}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_internal_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ------------------------------------------------- get_internal_oc_connector ---------------------------------------- #

class TestGetInternalOcConnector:
    """``get_internal_oc_connector`` resolves the internal connector, optionally checking a password."""

    def test_missing_internal_connector_returns_empty(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """When no internal connector exists an empty payload is returned with 200."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = None

        with flask_app.test_request_context(json={}):
            response = _unwrap(get_internal_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK

    def test_without_password_returns_located_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """With no password the connector located by name is returned without a credentialed fetch."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = {'connectorId': CONNECTOR_ID}

        with flask_app.test_request_context(json={}):
            response = _unwrap(get_internal_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connector.assert_not_called()

    def test_with_valid_password_returns_credentialed_connector(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """A valid password is checked and the connector fetched with it."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = {'connectorId': CONNECTOR_ID}
        oc_manager.check_master_pw.return_value = True
        oc_manager.get_connector.return_value = {'connectorId': CONNECTOR_ID, 'secret': True}

        with flask_app.test_request_context(json={'password': MASTER_PW}):
            response = _unwrap(get_internal_oc_connector)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        oc_manager.get_connector.assert_called_once_with(CONNECTOR_ID, MASTER_PW)

    def test_with_invalid_password_returns_403(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An invalid password aborts with 403."""
        del patched_managers
        oc_manager.get_connector_by_name.return_value = {'connectorId': CONNECTOR_ID}
        oc_manager.check_master_pw.return_value = False

        with flask_app.test_request_context(json={'password': MASTER_PW}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_internal_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_get_error_returns_500(
        self, flask_app: BaseCmdbApp, oc_manager: MagicMock, patched_managers: Any,
    ) -> None:
        """An OcConnectorGetError maps to 500."""
        del patched_managers
        oc_manager.get_connector_by_name.side_effect = OcConnectorGetError('boom')

        with flask_app.test_request_context(json={}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_internal_oc_connector)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
