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
Functional tests for the /config_file route feature-gating over HTTP

`GET /config_file/status/opencelium` only ever reports on the `[OpenCelium]` section and is consumed
by the Automations view alone, so it is gated with the OpenCelium routes it serves: with no license
active its own `requires_feature` guard blocks it with HTTP 403. When Automations is licensed, or in local
(cloud) mode, the guard lets the request through (asserted as "not 403").

The gate sits on the route, not on the `config_file` blueprint: the blueprint is the home of every config-file
status route, and one for another section must not inherit the Automations licence. That is pinned too.
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import GATED_FEATURE_ATTR
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

STATUS_URL: str = '/config_file/status/opencelium'
CONFIG_FILE_BLUEPRINT: str = 'config_file'


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_config_status_route_blocked_without_license(rest_api) -> None:
    """The OpenCelium config-status route is blocked with 403 when Automations is not licensed"""
    assert rest_api.get(STATUS_URL).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_config_status_route_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With Automations licensed the guard lets the request through (not 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.AUTOMATIONS,
    )

    assert rest_api.get(STATUS_URL).status_code != HTTPStatus.FORBIDDEN


def test_config_status_route_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(STATUS_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CORS preflight not gated                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_config_status_cors_preflight_not_blocked_without_license(rest_api) -> None:
    """
    A CORS preflight (OPTIONS) on the config-status route must NOT be gated even when unlicensed

    The browser sends an unauthenticated OPTIONS before the real cross-origin request and requires a
    2xx on it; aborting the preflight with 403 surfaces in the frontend as a CORS error instead of
    the intended 403 on the actual GET.
    """
    response = rest_api.options(
        STATUS_URL,
        headers={
            'Origin': 'http://localhost:4200',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.headers.get('Access-Control-Allow-Origin') is not None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the gate is the route's, not the blueprint's                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_config_file_blueprint_itself_is_not_gated(rest_api) -> None:
    """No before_request gate on the blueprint: a status route for another section is not locked by Automations"""
    hooks = rest_api.application.before_request_funcs.get(CONFIG_FILE_BLUEPRINT, [])

    assert CONFIG_FILE_BLUEPRINT in rest_api.application.blueprints
    assert not [hook for hook in hooks if hasattr(hook, GATED_FEATURE_ATTR)]


def test_the_status_route_answers_401_before_its_licence_403(rest_api) -> None:
    """Unlicensed and unauthenticated: the stranger gets the 401 and learns nothing about the licence"""
    assert rest_api.get(STATUS_URL, unauthorized=True).status_code == HTTPStatus.UNAUTHORIZED

