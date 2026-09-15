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

**OpenCelium's licence, not DataGerry's** - DataGerry's own licensing lives under `/rest/license`.
Each handler is unwrapped past its decorator chain and driven inside a BaseCmdbApp
test_request_context - no external OpenCelium HTTP, no Mongo. Unlike every other OpenCelium
blueprint, this one is intentionally NOT gated behind the AUTOMATIONS licence: OpenCelium's own
licence has to stay readable when something is wrong with it.

**The patch target is `build_license_manager`, not `OcLicenseManager`.** The construction moved into
the helper, and patching the class here would leave the real factory running against a stub app -
the trap four earlier sweeps in this package walked into, each time SILENTLY losing coverage rather
than failing. `oc_license_helper`'s own tests assert what the factory does.
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_license_routes import (
    get_oc_license_activation,
    get_oc_license_info,
    oc_licenses_blueprint,
    LICENSE_RESPONSE_KEY,
    USAGE_RESPONSE_KEY,
)

from cmdb.open_celium.oc_constants import (
    OC_DEFAULT_USAGE_PAGE,
    OC_DEFAULT_USAGE_SIZE,
    OC_PAGE_PARAM,
    OC_SIZE_PARAM,
)

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.open_celium_routes.oc_license_routes'

ACTIVE_LICENSE: dict[str, Any] = {'type': 'BUSINESS'}
USAGE_REPORT: dict[str, Any] = {'items': [], 'total': 0}

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
    """
    Patches the manager FACTORY the routes call, not the manager class

    Repointing this at `OcLicenseManager` would silently stop testing the routes.
    """
    with patch(f'{ROUTE_PATH}.build_license_manager', return_value=license_manager):
        yield


# ------------------------------------------------- get_oc_license_activation ---------------------------------------- #

class TestGetOcLicenseActivation:
    """``get_oc_license_activation`` returns the manager's activation payload."""

    def test_returns_activation(self, flask_app, license_manager, patched_manager) -> None:
        """The activation payload is returned with 200."""
        del patched_manager
        license_manager.get_license_activation.return_value = {'activation': 'blob'}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_license_activation)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_license_activation.assert_called_once_with()

    def test_the_payload_is_answered_unwrapped(self, flask_app, license_manager, patched_manager) -> None:
        """
        Whatever OpenCelium answered reaches the caller as-is, with no DataGerry envelope

        The route is a proxy; there is no `results`/`total` around this.
        """
        del patched_manager
        license_manager.get_license_activation.return_value = {'activation': 'blob'}

        with flask_app.test_request_context():
            response = _unwrap(get_oc_license_activation)(request_user=REQUEST_USER)

        assert response.json == {'activation': 'blob'}

    def test_get_error_returns_500(self, flask_app, license_manager, patched_manager) -> None:
        """An OcLicenseGetError maps to 500 (the route catches the license error, not the template one)."""
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
        """With no query params, usage is fetched with the shared defaults."""
        del patched_manager
        license_manager.get_active_license.return_value = ACTIVE_LICENSE
        license_manager.get_license_usage.return_value = USAGE_REPORT

        with flask_app.test_request_context('/licenses/info'):
            response = _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_active_license.assert_called_once_with()
        license_manager.get_license_usage.assert_called_once_with(OC_DEFAULT_USAGE_PAGE, OC_DEFAULT_USAGE_SIZE)

    def test_the_body_carries_both_halves(self, flask_app, license_manager, patched_manager) -> None:
        """
        `{'license': ..., 'usage': ...}` - a frontend contract

        The Angular `LicenseInfoResponse` reads both keys off one answer, so the shape is pinned here
        rather than left to the two manager assertions.
        """
        del patched_manager
        license_manager.get_active_license.return_value = ACTIVE_LICENSE
        license_manager.get_license_usage.return_value = USAGE_REPORT

        with flask_app.test_request_context('/licenses/info'):
            response = _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert response.json == {
            LICENSE_RESPONSE_KEY: ACTIVE_LICENSE,
            USAGE_RESPONSE_KEY: USAGE_REPORT,
        }

    def test_honours_page_and_size_query(self, flask_app, license_manager, patched_manager) -> None:
        """Explicit page/size query params are forwarded to get_license_usage."""
        del patched_manager
        license_manager.get_active_license.return_value = {}
        license_manager.get_license_usage.return_value = USAGE_REPORT

        with flask_app.test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=2&{OC_SIZE_PARAM}=10'):
            response = _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert response.status_code == HTTPStatus.OK
        license_manager.get_license_usage.assert_called_once_with(2, 10)

    def test_an_unreadable_page_falls_back_to_the_default(
            self, flask_app, license_manager, patched_manager) -> None:
        """
        `?page=abc` reads as the default page rather than a 400

        Recorded as behaviour - discussion-backlog #226 - and asserted at the route as well as at the
        helper, because this is the surface a caller actually sees it through.
        """
        del patched_manager
        license_manager.get_active_license.return_value = {}
        license_manager.get_license_usage.return_value = USAGE_REPORT

        with flask_app.test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=abc'):
            _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        license_manager.get_license_usage.assert_called_once_with(OC_DEFAULT_USAGE_PAGE, OC_DEFAULT_USAGE_SIZE)

    def test_the_license_is_read_before_the_usage(self, flask_app, license_manager, patched_manager) -> None:
        """
        Two sequential OpenCelium round-trips per request, in this order

        Pinned because it is the cost the route pays for answering both halves at once:
        discussion-backlog #227.
        """
        del patched_manager
        calls: list[str] = []
        license_manager.get_active_license.side_effect = lambda: calls.append('license') or ACTIVE_LICENSE
        license_manager.get_license_usage.side_effect = lambda *_: calls.append('usage') or USAGE_REPORT

        with flask_app.test_request_context('/licenses/info'):
            _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert calls == ['license', 'usage']

    def test_a_usage_failure_fails_the_whole_route(self, flask_app, license_manager, patched_manager) -> None:
        """
        The licence half is not answered on its own when the usage read fails

        Both halves come from the same try block, so a failing usage read costs the caller the
        licence too - the other consequence of #227.
        """
        del patched_manager
        license_manager.get_active_license.return_value = ACTIVE_LICENSE
        license_manager.get_license_usage.side_effect = OcLicenseGetError('boom')

        with flask_app.test_request_context('/licenses/info'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_error_returns_500(self, flask_app, license_manager, patched_manager) -> None:
        """An OcLicenseGetError maps to 500."""
        del patched_manager
        license_manager.get_active_license.side_effect = OcLicenseGetError('boom')

        with flask_app.test_request_context('/licenses/info'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_oc_license_info)(request_user=REQUEST_USER)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ------------------------------------------------ the route registration -------------------------------------------- #

class TestRouteRegistration:
    """Both routes of the blueprint are registered."""

    def test_every_route_is_registered(self) -> None:
        """
        Asserted as a map, because this package has shipped an unregistered route before

        A missing '@' on the execution-log DELETE left it invisible until someone looked.
        """
        app = Flask(__name__)
        app.register_blueprint(oc_licenses_blueprint)

        registered = {(rule.rule, method) for rule in app.url_map.iter_rules() for method in rule.methods}

        assert {
            ('/licenses/activation/generate', 'GET'),
            ('/licenses/info', 'GET'),
        } <= registered

    def test_both_read_routes_answer_head_as_well(self) -> None:
        """Both are declared GET/HEAD, which is what the docstrings claim"""
        app = Flask(__name__)
        app.register_blueprint(oc_licenses_blueprint)

        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/licenses'):
                assert 'HEAD' in rule.methods
