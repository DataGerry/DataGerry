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
A second REST app built in the same process as the session app is the same app, licence gates included

The blueprints are module-level singletons the session app has already registered and gated. A fresh
`create_rest_api` on the same database must build without Flask refusing a hook, carry the same URL map and
the same gates, and enforce them: an unlicensed ISMS route is a 403 on the second app, a licensed one is not
"""
from http import HTTPStatus
from typing import Iterator

import pytest

from cmdb.interface.rest_api.init_rest_api import create_rest_api
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import GATED_FEATURE_ATTR
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.flask_test_client import RestAPITestClient
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_ROUTE: str = '/isms/risk_classes/'


@pytest.fixture(name='second_api')
def fixture_second_api(database_manager, full_access_user) -> Iterator[RestAPITestClient]:
    """A test client on a freshly built second app, authenticated like the session client."""
    api = create_rest_api(database_manager)
    api.test_client_class = RestAPITestClient

    with api.test_client(database_manager=database_manager, default_auth_user=full_access_user) as client:
        yield client


def _gates(app) -> dict[str, list[LicenseFeature]]:
    """Every gated blueprint of an app, with the features its gate hooks record."""
    return {
        name: [getattr(hook, GATED_FEATURE_ATTR) for hook in hooks if hasattr(hook, GATED_FEATURE_ATTR)]
        for name, hooks in app.before_request_funcs.items()
        if name and any(hasattr(hook, GATED_FEATURE_ATTR) for hook in hooks)
    }


def test_the_second_app_has_the_session_apps_url_map(rest_api, second_api) -> None:
    """Same rules, same endpoints"""
    def _rules(app) -> list[tuple[str, str]]:
        return sorted((rule.rule, rule.endpoint) for rule in app.url_map.iter_rules())

    assert _rules(second_api.application) == _rules(rest_api.application)


def test_the_second_app_carries_the_same_gates_once_each(rest_api, second_api) -> None:
    """The gates Flask replays onto the second app are the session app's - one hook per blueprint"""
    assert _gates(second_api.application) == _gates(rest_api.application)
    assert all(len(features) == 1 for features in _gates(second_api.application).values())


def test_the_second_app_refuses_an_unlicensed_gated_route(second_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Its gates are enforced: ISMS unlicensed is a 403"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

    assert second_api.get(ISMS_ROUTE).status_code == HTTPStatus.FORBIDDEN


def test_the_second_app_serves_a_licensed_gated_route(second_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ISMS licensed the same route is let through"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)

    assert second_api.get(ISMS_ROUTE).status_code == HTTPStatus.OK
