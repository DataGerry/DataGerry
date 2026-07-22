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
Functional tests for automations (OpenCelium) feature-gating over HTTP

The whole OpenCelium integration is the licensed Automations feature, so with no license active
every route - reads included - is blocked with HTTP 403 by a blueprint-level guard, before the view
runs (so no external OpenCelium call is attempted). OpenCelium's OWN license routes stay ungated.
When the feature is licensed, or in local (cloud) mode, the guard lets the request through to the
view - asserted as "no longer 403"; the view's own outcome (it would reach the external OpenCelium
backend) is not exercised
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# One representative route per gated OpenCelium blueprint (all under /open_celium)
CONNECTORS_URL: str = '/open_celium/connectors'
INVOKERS_URL: str = '/open_celium/invokers'
TEMPLATES_URL: str = '/open_celium/templates'
CONNECTION_URL: str = '/open_celium/connections/1'
SCHEDULERS_URL: str = '/open_celium/schedulers'
SCHEDULER_LOGS_URL: str = '/open_celium/schedulers/logs'
CONNECTION_LOGS_URL: str = '/open_celium/connections/logs/list'
CREATE_SCHEDULER_URL: str = '/open_celium/schedulers'

# OpenCelium's own license routes are NOT part of the Automations feature and stay ungated
OC_LICENSE_INFO_URL: str = '/open_celium/licenses/info'

# Every gated blueprint's representative READ route - reads lock too (whole feature)
GATED_READ_URLS: list[str] = [
    CONNECTORS_URL,
    INVOKERS_URL,
    TEMPLATES_URL,
    CONNECTION_URL,
    SCHEDULERS_URL,
    SCHEDULER_LOGS_URL,
    CONNECTION_LOGS_URL,
]


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('url', GATED_READ_URLS)
def test_oc_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every OpenCelium read route is blocked with 403 when automations is not licensed (reads lock too)"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


def test_create_scheduler_blocked_without_license(rest_api) -> None:
    """Creating a scheduler is blocked with 403 when automations is not licensed"""
    assert rest_api.post(CREATE_SCHEDULER_URL, json={}).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          OpenCelium license routes stay ungated                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_oc_own_license_route_not_gated(rest_api) -> None:
    """OpenCelium's own license route is NOT part of the automations lock and never returns the guard 403"""
    assert rest_api.get(OC_LICENSE_INFO_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_oc_routes_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With automations licensed the guard lets the request through (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.AUTOMATIONS,
    )

    assert rest_api.get(SCHEDULERS_URL).status_code != HTTPStatus.FORBIDDEN


def test_oc_routes_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(SCHEDULERS_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CORS preflight not gated                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_oc_cors_preflight_not_blocked_without_license(rest_api) -> None:
    """
    A CORS preflight (OPTIONS) on an OpenCelium route must NOT be gated even when unlicensed

    The browser sends an unauthenticated OPTIONS before the real cross-origin request and requires a
    2xx on it. The blueprint guard previously aborted the preflight with 403, failing the preflight
    so the real request never left the browser - surfacing as a CORS error in the frontend rather
    than the intended 403 on the actual request. The preflight must come back OK with CORS headers.
    """
    response = rest_api.options(
        SCHEDULERS_URL,
        headers={
            'Origin': 'http://localhost:4200',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code != HTTPStatus.FORBIDDEN
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get('Access-Control-Allow-Origin') is not None
