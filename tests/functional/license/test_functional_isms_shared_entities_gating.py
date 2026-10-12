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
Functional tests for the ISMS-dependent shared-entity feature-gating over HTTP

Persons, Person Groups and Object Groups are shared entities the ISMS feature depends on
(risk-assessment responsible/interviewed persons and risk owner; the object group is the risk
scope). On-premise they are part of the licensed ISMS surface, so their HTTP routes are gated behind
the ISMS feature too by a blueprint-level guard - even though they keep their own top-level prefixes
(/object_groups, /persons, /person_groups) rather than living under /isms/. With no license active
every route (reads included) is blocked with HTTP 403, before the view runs. When ISMS is licensed,
or in local (cloud) mode, the guard lets the request through (asserted as "not 403")

Persons and person groups are CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes now: /persons and
/person_groups are read-only (the ISMS module still reads them there) and stay gated, while the objects
themselves and the /person_relations routes are a standard feature and are not gated at all
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# The collection '/' GET route per gated shared-entity blueprint
OBJECT_GROUPS_URL: str = '/object_groups/'
PERSONS_URL: str = '/persons/'
PERSON_GROUPS_URL: str = '/person_groups/'

GATED_READ_URLS: list[str] = [
    OBJECT_GROUPS_URL,
    PERSONS_URL,
    PERSON_GROUPS_URL,
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
def test_shared_entity_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every ISMS-dependent shared-entity read route is blocked with 403 when ISMS is not licensed"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


def test_shared_entity_write_routes_blocked_without_license(rest_api) -> None:
    """The ISMS-dependent shared-entity write route is blocked with 403 when ISMS is not licensed"""
    assert rest_api.post(OBJECT_GROUPS_URL, json={}).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', [PERSONS_URL, PERSON_GROUPS_URL])
def test_the_person_routes_take_no_write(rest_api, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Persons and groups are written through /objects; their legacy routes only answer GET"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)

    assert rest_api.post(url, json={}).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.parametrize('url', ['/person_relations/types', '/person_relations/candidates'])
def test_the_person_relation_routes_are_not_gated(rest_api, url: str) -> None:
    """Persons are a standard feature: no license is needed for the relation routes"""
    assert rest_api.get(url).status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('url', GATED_READ_URLS)
def test_shared_entity_routes_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """
    With ISMS licensed every shared-entity route is let through (not 403)

    Unlocking ONLY ISMS here also pins that each of the three blueprints is keyed to
    LicenseFeature.ISMS specifically - a blueprint wired to a different feature would stay 403.
    """
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.ISMS,
    )

    assert rest_api.get(url).status_code != HTTPStatus.FORBIDDEN


def test_shared_entity_routes_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    assert rest_api.get(OBJECT_GROUPS_URL).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          CORS preflight not gated                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('url', GATED_READ_URLS)
def test_shared_entity_cors_preflight_not_blocked_without_license(rest_api, url: str) -> None:
    """
    A CORS preflight (OPTIONS) on a gated shared-entity route must NOT be gated even when unlicensed

    The browser sends an unauthenticated OPTIONS before the real cross-origin request and requires a
    2xx on it. A guard that aborted the preflight with 403 would fail it, so the real request would
    never leave the browser - surfacing as a CORS error in the frontend rather than the intended
    403 on the actual request. The preflight must come back OK with CORS headers.
    """
    response = rest_api.options(
        url,
        headers={
            'Origin': 'http://localhost:4200',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code != HTTPStatus.FORBIDDEN
    assert response.status_code == HTTPStatus.OK
    assert response.headers.get('Access-Control-Allow-Origin') is not None
