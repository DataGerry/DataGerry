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
Unit tests for cmdb.interface.rest_api.routes.open_celium_routes.oc_license_routes

Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context with OcLicenseManager patched at the route module path - no external OpenCelium
HTTP, no Mongo. Unlike the other OpenCelium blueprints, this one is intentionally NOT license-gated
(it concerns OpenCelium's own licensing, not the DataGerry AUTOMATIONS feature).

These pin the success paths (manager calls, the assembled license-info payload, page/size query
parsing) and the error path (OcLicenseGetError -> 500 — the routes now catch OcLicenseGetError, not
OcTemplateGetError).
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_license_routes import (
    get_oc_license_activation,
    get_oc_license_info,
)
from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_license_routes'

DEFAULT_PAGE: int = 0
DEFAULT_SIZE: int = 5

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


@pytest.fixture(name='license_manager')
def fixture_license_manager() -> MagicMock:
    """The OcLicenseManager instance the handlers operate on."""
    return MagicMock()


@pytest.fixture(name='patched_manager')
def fixture_patched_manager(license_manager: MagicMock) -> Any:
    """Patches OcLicenseManager at the route module path."""
    with patch(f'{ROUTE_PATH}.OcLicenseManager', return_value=license_manager):
        yield


# ------------------------------------------------- get_oc_license_activation ---------------------------------------- #

class TestGetOcLicenseActivation:
    """``get_oc_license_activation`` returns the manager's activation payload."""

    def test_returns_activation(self, flask_app, license_manager, patched_manager) -> None:
        """The activation payload is returned with 200."""
        del patched_manager
        license_manager.get_license_activation.return_value = 'activation-blob'

        with flask_app.test_request_context():
            response = _unwrap(get_oc_license_activation)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_license_activation.assert_called_once_with()

    def test_get_error_returns_500(self, flask_app, license_manager, patched_manager) -> None:
        """An OcLicenseGetError maps to 500 (the route now catches the license error, not the template one)."""
        del patched_manager
        license_manager.get_license_activation.side_effect = OcLicenseGetError('boom')

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_license_activation)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------- get_oc_license_info ------------------------------------------- #

class TestGetOcLicenseInfo:
    """``get_oc_license_info`` assembles {license, usage} and honours the page/size query params."""

    def test_returns_info_with_default_paging(self, flask_app, license_manager, patched_manager) -> None:
        """With no query params, usage is fetched with the default page/size."""
        del patched_manager
        license_manager.get_active_license.return_value = {'type': 'BUSINESS'}
        license_manager.get_license_usage.return_value = {'items': []}

        with flask_app.test_request_context('/licenses/info'):
            response = _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_active_license.assert_called_once_with()
        license_manager.get_license_usage.assert_called_once_with(DEFAULT_PAGE, DEFAULT_SIZE)

    def test_honours_page_and_size_query(self, flask_app, license_manager, patched_manager) -> None:
        """Explicit page/size query params are forwarded to get_license_usage."""
        del patched_manager
        license_manager.get_active_license.return_value = {}
        license_manager.get_license_usage.return_value = {'items': []}

        with flask_app.test_request_context('/licenses/info?page=2&size=10'):
            response = _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_license_usage.assert_called_once_with(2, 10)

    def test_get_error_returns_500(self, flask_app, license_manager, patched_manager) -> None:
        """An OcLicenseGetError maps to 500."""
        del patched_manager
        license_manager.get_active_license.side_effect = OcLicenseGetError('boom')

        with flask_app.test_request_context('/licenses/info'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
