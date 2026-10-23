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
Which IPAM routes the cloud API key reaches - through the real REST app in hosted-cloud mode

The IPAM records are objects, written through ``/objects`` at the ADMIN level. Beside them an API client writing
them needs the IPAM pickers, the pre-checks and the two unassign writes, so those are ADMIN too; the views, the CSV
exports and the sidebar tree stay LOCKED - never the cloud API key. Pinned through the real level check: an
ADMIN-level key passes it on every opened route (whatever the route then answers, it is not the level's 403), a key
below ADMIN is refused there, and a LOCKED route refuses even the highest key
"""
import base64
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.interface import route_utils as ru
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature

from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_UTILS: str = 'cmdb.interface.route_utils'
API_KEY_ENVIRON: dict[str, str] = {
    'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(b'automation@x.io:secret').decode('ascii'),
    'HTTP_X_API_KEY': 'key',
}
NO_LEVEL: int = 0
ADMIN_LEVEL: int = 1
HIGHEST_LEVEL: int = 3
MISSING_ID: int = 987654

# (method, url, json body) of every IPAM route opened to the ADMIN level
OPENED_ROUTES: list[tuple[str, str, Any]] = [
    ('GET', '/ipam/assignable-objects/', None),
    ('GET', '/ipam/subnet/', None),
    ('POST', f'/ipam/subnet/overview/{MISSING_ID}/unassign', {'object_ids': []}),
    ('POST', f'/ipam/supernet/overview/{MISSING_ID}/subnets/unassign', {'subnet_ids': []}),
    ('POST', '/ipam/validate/subnet', {}),
    ('POST', '/ipam/validate/supernet', {}),
    ('POST', '/ipam/validate/vlan', {}),
    ('POST', '/ipam/validate/interface', {}),
]

# (method, url) of IPAM routes that stay LOCKED - one per blueprint that keeps any
LOCKED_ROUTES: list[tuple[str, str]] = [
    ('GET', '/ipam/tree/'),
    ('GET', f'/ipam/subnet/overview/{MISSING_ID}'),
    ('GET', f'/ipam/supernet/overview/{MISSING_ID}'),
]


@pytest.fixture(autouse=True)
def _hosted(rest_api, monkeypatch, database_manager) -> None:
    """Hosted cloud mode, the IPAM feature licensed"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _send(rest_api, database_name: str, method: str, url: str, body: Any, api_level: int) -> Any:
    """Sends the API-key request for an account at `api_level`, the portal check and the user read replaced"""
    account: dict[str, Any] = {'email': 'automation@x.io', 'api_level': api_level,
                               'subscriptions': [{'database': database_name, 'api_level': api_level}]}
    tenant_user: Any = ru.CmdbUser(public_id=1, user_name='admin', active=True, group_id=1, database=database_name)

    with patch(f'{ROUTE_UTILS}.check_user_in_service_portal', return_value=account), \
         patch(f'{ROUTE_UTILS}.set_admin_user'), \
         patch(f'{ROUTE_UTILS}.retrieve_user', return_value=tenant_user):
        return rest_api.open(url, method=method, json=body, environ_overrides=API_KEY_ENVIRON)


def _refused_by_the_level(response: Any) -> bool:
    """The level check's own 403"""
    return (response.status_code == HTTPStatus.FORBIDDEN and response.is_json
            and response.get_json().get('message') == ru.API_LEVEL_DENIED_MESSAGE)


@pytest.mark.parametrize('method, url, body', OPENED_ROUTES, ids=[f'{m} {u}' for m, u, _ in OPENED_ROUTES])
def test_an_admin_level_key_passes_the_level_on_an_opened_route(rest_api, database_name: str, method: str,
                                                                url: str, body: Any) -> None:
    """Whatever the route answers next, the level let it through"""
    response = _send(rest_api, database_name, method, url, body, ADMIN_LEVEL)

    assert not _refused_by_the_level(response), response.get_data(as_text=True)
    assert response.status_code != HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.parametrize('method, url, body', OPENED_ROUTES, ids=[f'{m} {u}' for m, u, _ in OPENED_ROUTES])
def test_a_key_below_admin_is_refused_on_an_opened_route(rest_api, database_name: str, method: str, url: str,
                                                         body: Any) -> None:
    """ADMIN, not merely any key"""
    assert _refused_by_the_level(_send(rest_api, database_name, method, url, body, NO_LEVEL))


@pytest.mark.parametrize('method, url', LOCKED_ROUTES, ids=[f'{m} {u}' for m, u in LOCKED_ROUTES])
def test_a_view_stays_locked_for_every_key(rest_api, database_name: str, method: str, url: str) -> None:
    """The views, exports and tree are never the cloud API key's"""
    assert _refused_by_the_level(_send(rest_api, database_name, method, url, None, HIGHEST_LEVEL))
