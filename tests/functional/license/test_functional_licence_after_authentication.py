# DataGerry - OpenSource Enterprise CMDB
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
Functional coverage that a licence gate answers only a caller who authenticated

The order is authenticate, then licence: a caller without valid credentials gets the 401 on every
gated surface, so a stranger cannot read off which features the installation is licensed for. An
authenticated caller on an unlicensed installation still gets the 403 naming the feature - the
frontend's premium gating relies on it. The same holds for the REST API lock on HTTP Basic: a wrong
password is a 401, the right one on an unlicensed installation the REST API 403.

Because the blueprint gate is enforced by `insert_request_user`, a gated route without it would lose
its gate silently. The census walks the real app's URL map and fails on any such route
"""
import base64
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.route_utils import insert_request_user
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import (
    FEATURE_NOT_LICENSED_MESSAGE,
    GATED_FEATURE_ATTR,
    LICENSE_FEATURE_LABELS,
)
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# One route per gated surface, each answering a plain GET once the caller may use it
GATED_ROUTES: dict[str, LicenseFeature] = {
    '/isms/threats/': LicenseFeature.ISMS,
    '/persons/': LicenseFeature.ISMS,
    '/ipam/subnet/': LicenseFeature.IPAM,
    '/racks/1/mounts/': LicenseFeature.IPAM,
    '/ports/object/1': LicenseFeature.IPAM,
    '/config_file/status/opencelium': LicenseFeature.AUTOMATIONS,
}

UNGATED_ROUTE: str = '/types/?limit=1'

ADMIN_CREDENTIALS: bytes = b'admin:admin'
WRONG_CREDENTIALS: bytes = b'admin:not-the-password'

# The features the app gates whole blueprints behind
BLUEPRINT_GATED_FEATURES: set[LicenseFeature] = {LicenseFeature.ISMS, LicenseFeature.IPAM,
                                                 LicenseFeature.AUTOMATIONS}

# The code object every insert_request_user wrapper shares - how the census recognises one
AUTHENTICATING_WRAPPER_CODE = insert_request_user(lambda: None).__code__


def _basic(credentials: bytes) -> dict[str, str]:
    """environ_overrides replacing the client's Bearer token with HTTP Basic credentials."""
    return {'HTTP_AUTHORIZATION': f'Basic {base64.b64encode(credentials).decode("utf-8")}'}


def _licence_refusal(feature: LicenseFeature) -> str:
    """The 403 message naming a feature."""
    return FEATURE_NOT_LICENSED_MESSAGE.format(feature=LICENSE_FEATURE_LABELS[feature])


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(name='licensed')
def fixture_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses every feature."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the blueprint gates                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('url', GATED_ROUTES)
def test_a_stranger_gets_the_401_not_the_licence_state(rest_api, url: str) -> None:
    """No token on an unlicensed installation: the 401, exactly as a licensed one answers"""
    response = rest_api.get(url, unauthorized=True)

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize('url', GATED_ROUTES)
def test_wrong_basic_credentials_get_the_401_not_the_licence_state(rest_api, url: str) -> None:
    """A wrong password never reaches a licence check - neither the channel's nor the feature's"""
    response = rest_api.get(url, environ_overrides=_basic(WRONG_CREDENTIALS))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(('url', 'feature'), GATED_ROUTES.items())
def test_an_authenticated_caller_gets_the_licence_refusal(rest_api, url: str, feature: LicenseFeature) -> None:
    """Logged in on an unlicensed installation: the 403 naming the feature"""
    response = rest_api.get(url)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == _licence_refusal(feature)


@pytest.mark.parametrize('url', GATED_ROUTES)
def test_a_licensed_caller_gets_through(rest_api, licensed, url: str) -> None:
    """Licensed and authenticated: neither refusal"""
    response = rest_api.get(url)

    assert response.status_code not in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)


@pytest.mark.parametrize('url', GATED_ROUTES)
def test_the_preflight_is_never_gated(rest_api, url: str) -> None:
    """A CORS preflight carries no token; it is answered, not refused"""
    response = rest_api.options(url, unauthorized=True)

    assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the REST API lock (HTTP Basic)                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_wrong_basic_credentials_get_the_401(rest_api) -> None:
    """The REST API lock answers only after the credentials are checked"""
    response = rest_api.get(UNGATED_ROUTE, environ_overrides=_basic(WRONG_CREDENTIALS))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_right_basic_credentials_get_the_rest_api_refusal(rest_api) -> None:
    """Authenticated over Basic on an unlicensed installation: the REST API 403"""
    response = rest_api.get(UNGATED_ROUTE, environ_overrides=_basic(ADMIN_CREDENTIALS))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == _licence_refusal(LicenseFeature.REST_API)


def test_right_basic_credentials_on_a_licensed_installation_get_through(rest_api, licensed) -> None:
    """The external REST API works once licensed"""
    response = rest_api.get(UNGATED_ROUTE, environ_overrides=_basic(ADMIN_CREDENTIALS))

    assert response.status_code == HTTPStatus.OK


def test_the_ui_bearer_channel_is_not_locked(rest_api) -> None:
    """The frontend's Bearer token keeps working with the REST API unlicensed"""
    assert rest_api.get(UNGATED_ROUTE).status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                          census: every gated route authenticates                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _runs_insert_request_user(func: Callable[..., Any], seen: set[int] | None = None) -> bool:
    """
    Whether `insert_request_user` is anywhere in a view function's decorator stack

    Walks the closures, since not every decorator keeps a `__wrapped__` link
    """
    seen = set() if seen is None else seen

    if id(func) in seen:
        return False

    seen.add(id(func))

    if getattr(func, '__code__', None) is AUTHENTICATING_WRAPPER_CODE:
        return True

    for cell in getattr(func, '__closure__', None) or ():
        try:
            content = cell.cell_contents
        except ValueError:
            continue

        if callable(content) and _runs_insert_request_user(content, seen):
            return True

    return False


def _gated_blueprints(app) -> dict[str, LicenseFeature]:
    """The app's gated blueprint names, with the feature each one's gate records."""
    return {
        name: getattr(hook, GATED_FEATURE_ATTR)
        for name, hooks in app.before_request_funcs.items() if name
        for hook in hooks if hasattr(hook, GATED_FEATURE_ATTR)
    }


def _gated_endpoints(app) -> list[str]:
    """Every endpoint served by a gated blueprint."""
    gated: dict[str, LicenseFeature] = _gated_blueprints(app)

    return [rule.endpoint for rule in app.url_map.iter_rules() if rule.endpoint.rpartition('.')[0] in gated]


def test_the_census_sees_every_gated_feature(rest_api) -> None:
    """The census is not vacuous: it finds the gated blueprints of all three features, and their routes"""
    app = rest_api.application

    assert set(_gated_blueprints(app).values()) == BLUEPRINT_GATED_FEATURES
    assert _gated_endpoints(app)


def test_the_census_tells_an_authenticating_route_from_one_that_is_not() -> None:
    """The detector itself: found through a decorator that drops `__wrapped__`, absent on a bare view"""
    def _drops_wrapped(func: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        return _wrapper

    def _view() -> None:
        return None

    assert _runs_insert_request_user(_drops_wrapped(insert_request_user(_view)))
    assert not _runs_insert_request_user(_drops_wrapped(_view))


def test_every_route_on_a_gated_blueprint_runs_insert_request_user(rest_api) -> None:
    """insert_request_user is where the blueprint gate is enforced - without it a route is ungated"""
    app = rest_api.application

    ungated: list[str] = [
        endpoint for endpoint in _gated_endpoints(app)
        if not _runs_insert_request_user(app.view_functions[endpoint])
    ]

    assert not ungated
