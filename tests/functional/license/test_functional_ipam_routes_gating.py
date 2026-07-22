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
Functional tests for the dedicated /ipam route feature-gating over HTTP

The dedicated /ipam surface (network tree, supernet/subnet overviews, subnet picker, assignable
lookups, validation) is part of the licensed IPAM feature, so with no license active every route is
blocked with HTTP 403 by a blueprint-level guard - across all 5 IPAM blueprints. IPAM data stays
readable through the generic /objects and /types routes (gated separately at write time); only these
dedicated surfaces are locked here. When IPAM is licensed, or in local (cloud) mode, the guard lets
the request through (asserted as "no longer 403")
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# One representative GET route per dedicated /ipam blueprint (trailing slash matches the '/' routes)
TREE_URL: str = '/ipam/tree/'
SUBNET_PICKER_URL: str = '/ipam/subnet/'
ASSIGNABLE_URL: str = '/ipam/assignable-objects/'
SUPERNET_OVERVIEW_URL: str = '/ipam/supernet/overview/1'
SUBNET_OVERVIEW_URL: str = '/ipam/subnet/overview/1'

# The validation blueprint is POST-only
VALIDATE_SUBNET_URL: str = '/ipam/validate/subnet'

GATED_GET_URLS: list[str] = [
    TREE_URL,
    SUBNET_PICKER_URL,
    ASSIGNABLE_URL,
    SUPERNET_OVERVIEW_URL,
    SUBNET_OVERVIEW_URL,
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
@pytest.mark.parametrize('url', GATED_GET_URLS)
def test_ipam_get_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every dedicated /ipam GET route is blocked with 403 when IPAM is not licensed"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


def test_ipam_validation_route_blocked_without_license(rest_api) -> None:
    """The POST validation route is blocked with 403 when IPAM is not licensed"""
    assert rest_api.post(VALIDATE_SUBNET_URL, json={}).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ipam_routes_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With IPAM licensed the guard lets the request through (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.IPAM,
    )

    assert rest_api.get(TREE_URL).status_code != HTTPStatus.FORBIDDEN


def test_ipam_routes_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(TREE_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CORS preflight not gated                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ipam_cors_preflight_not_blocked_without_license(rest_api) -> None:
    """
    A CORS preflight (OPTIONS) on a dedicated /ipam route must NOT be gated even when unlicensed

    The browser sends an unauthenticated OPTIONS before the real cross-origin request and requires a
    2xx on it. The blueprint guard previously aborted the preflight with 403, failing the preflight
    so the real request never left the browser - surfacing as a CORS error in the frontend rather
    than the intended 403 on the actual GET. The preflight must come back OK with CORS headers.
    """
    response = rest_api.options(
        TREE_URL,
        headers={
            'Origin': 'http://localhost:4200',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code != HTTPStatus.FORBIDDEN
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get('Access-Control-Allow-Origin') is not None
