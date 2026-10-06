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
What the API levels do on-premise: nothing - the licensed REST API reaches every level

On-premise no `ApiLevel` is checked. The REST API - HTTP Basic credentials, licensed as the `REST_API` feature -
reaches a `LOCKED` route exactly as an `ADMIN` or a `SUPER_ADMIN` one, as far as the user's rights allow; without
the feature licensed every Basic request is refused, whatever the route's level. The frontend's token is not the
REST API and needs no such licence. The routes are probed with reads (and one write that names a missing user),
so a refusal can only come from the gates
"""
import base64
from http import HTTPStatus

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_NAME: str = 'admin'
ADMIN_PASSWORD: str = 'admin'
MISSING_USER_ID: int = 987654

# One route per level, each probed with a request that cannot change anything
LOCKED_ROUTE: tuple[str, str] = ('get', '/ci_explorer/profile')
ADMIN_ROUTE: tuple[str, str] = ('get', '/types/')
SUPER_ADMIN_ROUTE: tuple[str, str] = ('delete', f'/users/{MISSING_USER_ID}')
LEVEL_ROUTES: list[tuple[str, str]] = [LOCKED_ROUTE, ADMIN_ROUTE, SUPER_ADMIN_ROUTE]
LEVEL_IDS: list[str] = ['LOCKED', 'ADMIN', 'SUPER_ADMIN']

# What each probe answers once it has passed the gates: the read is served, the delete finds no user
PASSED: dict[str, set[int]] = {'get': {HTTPStatus.OK}, 'delete': {HTTPStatus.NOT_FOUND}}


def _basic_environ() -> dict[str, str]:
    """The seeded admin's HTTP Basic credentials, replacing the test client's token"""
    credentials = base64.b64encode(f'{ADMIN_NAME}:{ADMIN_PASSWORD}'.encode()).decode()

    return {'HTTP_AUTHORIZATION': f'Basic {credentials}'}


def _license(monkeypatch: pytest.MonkeyPatch, rest_api_licensed: bool) -> None:
    """Every feature licensed, the REST API as given"""
    monkeypatch.setattr(LicenseService, 'has_feature',
                        lambda _self, feature: rest_api_licensed or feature != LicenseFeature.REST_API)


def _call(rest_api, route: tuple[str, str], **kwargs):
    """Issues the probe with the route's verb"""
    method, url = route

    return getattr(rest_api, method)(url, **kwargs)


@pytest.mark.parametrize('route', LEVEL_ROUTES, ids=LEVEL_IDS)
def test_the_licensed_rest_api_reaches_every_level(rest_api, monkeypatch: pytest.MonkeyPatch, route) -> None:
    """LOCKED is 'never the cloud API key' - on-premise there is no cloud API key to refuse"""
    _license(monkeypatch, rest_api_licensed=True)

    assert _call(rest_api, route, environ_overrides=_basic_environ()).status_code in PASSED[route[0]]


@pytest.mark.parametrize('route', LEVEL_ROUTES, ids=LEVEL_IDS)
def test_the_unlicensed_rest_api_is_refused_at_every_level(
        rest_api, monkeypatch: pytest.MonkeyPatch, route) -> None:
    """The licence, not the level, decides whether HTTP Basic is accepted"""
    _license(monkeypatch, rest_api_licensed=False)

    assert _call(rest_api, route, environ_overrides=_basic_environ()).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('route', LEVEL_ROUTES, ids=LEVEL_IDS)
def test_the_frontends_token_needs_no_rest_api_licence(rest_api, monkeypatch: pytest.MonkeyPatch, route) -> None:
    """The token is not the REST API"""
    _license(monkeypatch, rest_api_licensed=False)

    assert _call(rest_api, route).status_code in PASSED[route[0]]
