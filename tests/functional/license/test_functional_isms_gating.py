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
Functional tests for ISMS feature-gating over HTTP

The whole ISMS module is the licensed ISMS feature, so with no license active every route - reads
included, across all 15 ISMS blueprints - is blocked with HTTP 403 by a blueprint-level guard,
before the view runs. When the feature is licensed, or in local (cloud) mode, the guard lets the
request through (asserted as "no longer 403")
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# One representative read route per ISMS blueprint (trailing slash matches the collection '/' routes)
RISK_CLASSES_URL: str = '/isms/risk_classes/'
LIKELIHOODS_URL: str = '/isms/likelihoods/'
IMPACTS_URL: str = '/isms/impacts/'
IMPACT_CATEGORIES_URL: str = '/isms/impact_categories/'
PROTECTION_GOALS_URL: str = '/isms/protection_goals/'
THREATS_URL: str = '/isms/threats/'
VULNERABILITIES_URL: str = '/isms/vulnerabilities/'
RISKS_URL: str = '/isms/risks/'
CONTROL_MEASURES_URL: str = '/isms/control_measures/'
RISK_ASSESSMENTS_URL: str = '/isms/risk_assessments/'
CONTROL_MEASURE_ASSIGNMENTS_URL: str = '/isms/control_measure_assignments/'
CONFIG_STATUS_URL: str = '/isms/config/status'
REPORT_SOA_URL: str = '/isms/reports/soa'

GATED_READ_URLS: list[str] = [
    RISK_CLASSES_URL,
    LIKELIHOODS_URL,
    IMPACTS_URL,
    IMPACT_CATEGORIES_URL,
    PROTECTION_GOALS_URL,
    THREATS_URL,
    VULNERABILITIES_URL,
    RISKS_URL,
    CONTROL_MEASURES_URL,
    RISK_ASSESSMENTS_URL,
    CONTROL_MEASURE_ASSIGNMENTS_URL,
    CONFIG_STATUS_URL,
    REPORT_SOA_URL,
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
def test_isms_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every ISMS read route is blocked with 403 when ISMS is not licensed (reads lock too)"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


def test_create_risk_class_blocked_without_license(rest_api) -> None:
    """An ISMS write is blocked with 403 when ISMS is not licensed"""
    assert rest_api.post(RISK_CLASSES_URL, json={}).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_isms_routes_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ISMS licensed the guard lets the request through (no longer 403)"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.ISMS,
    )

    assert rest_api.get(RISK_CLASSES_URL).status_code != HTTPStatus.FORBIDDEN


def test_isms_routes_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(RISK_CLASSES_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CORS preflight not gated                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_isms_cors_preflight_not_blocked_without_license(rest_api) -> None:
    """
    A CORS preflight (OPTIONS) on an ISMS route must NOT be gated even when unlicensed

    The browser sends an unauthenticated OPTIONS before the real cross-origin request and requires a
    2xx on it. The blueprint guard previously aborted the preflight with 403, failing the preflight
    so the real request never left the browser - surfacing as a CORS error in the frontend rather
    than the intended 403 on the actual request. The preflight must come back OK with CORS headers.
    """
    response = rest_api.options(
        RISK_CLASSES_URL,
        headers={
            'Origin': 'http://localhost:4200',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code != HTTPStatus.FORBIDDEN
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get('Access-Control-Allow-Origin') is not None
