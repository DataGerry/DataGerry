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
Functional coverage of a tenant that failed its startup update, over the three hosted-cloud channels

A tenant database that failed its validation or update at startup is recorded in the app's
`unavailable_tenants`; every request bound to it is answered 503 in the error envelope - the cloud login,
Basic + `x-api-key` and a Bearer token alike - while a request bound to any other tenant is served. The
portal is stubbed at both of its call sites, as in the deactivated-account module
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER
from cmdb.interface.rest_api.routes import auth_helper
from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'

USER_ID: int = 93998
EMAIL: str = 'cloud-unavailable-tenant@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'subscription-key'
OTHER_TENANT: str = 'tenant_failed_its_update'

API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'


def _portal_user(database: str) -> dict[str, Any]:
    """The ServicePortal's answer for the account: one subscription on the test database."""
    return {
        'email': EMAIL, 'user_name': 'cloud-unavailable', 'password': PASSWORD, 'api_level': 3,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database, 'api_level': 3,
                           'config_item_limit': 100}],
    }


@pytest.fixture(name='cloud_tenant')
def fixture_cloud_tenant(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                         database_name: str):
    """A hosted-cloud app, a stored tenant user in the test database and a portal that accepts it."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'cloud-unavailable', 'email': EMAIL, 'active': True,
        'group_id': 1, 'database': database_name, 'api_level': 3,
        'registration_time': datetime.now(timezone.utc),
    })

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal = _portal_user(database_name)
    monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)
    monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _database: True)

    yield database_name

    users.delete_many({'public_id': USER_ID})


def _fence_off(rest_api, monkeypatch: pytest.MonkeyPatch, *tenants: str) -> None:
    """Marks tenants as failed at startup, as create_rest_api records them."""
    monkeypatch.setattr(rest_api.application, 'unavailable_tenants', frozenset(tenants))


def _assert_unavailable(response) -> None:
    """A 503 in the error envelope, carrying the unavailable-tenant message."""
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.get_json()['message'] == TENANT_UNAVAILABLE_RESPONSE_MESSAGE


def _with_api_key(rest_api):
    """A protected request authenticated by Basic credentials and the subscription's API key."""
    basic: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode('utf-8')).decode('utf-8')

    return rest_api.get(PROTECTED_URL, environ_overrides={'HTTP_AUTHORIZATION': f'Basic {basic}',
                                                          API_KEY_ENVIRON: API_KEY})


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the fenced-off tenant                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_cloud_login_to_an_unavailable_tenant_is_a_503(rest_api, cloud_tenant,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """No token is issued for a tenant whose database failed its update"""
    _fence_off(rest_api, monkeypatch, cloud_tenant)

    response = rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD}, unauthorized=True)

    _assert_unavailable(response)
    assert 'token' not in response.get_json()


def test_an_api_key_request_to_an_unavailable_tenant_is_a_503(rest_api, cloud_tenant,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Basic + x-api-key is refused before the tenant's admin user is written"""
    _fence_off(rest_api, monkeypatch, cloud_tenant)

    _assert_unavailable(_with_api_key(rest_api))


def test_a_bearer_token_of_an_unavailable_tenant_is_a_503(rest_api, cloud_tenant,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """A token issued before the restart names the tenant - it is refused too"""
    _fence_off(rest_api, monkeypatch, cloud_tenant)

    response = rest_api.get(PROTECTED_URL, environ_overrides=cloud_auth_header(rest_api, USER_ID, cloud_tenant))

    _assert_unavailable(response)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        every other tenant                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.usefixtures('cloud_tenant')
def test_another_tenant_logs_in_beside_an_unavailable_one(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the failed tenant is fenced off: the login to a healthy one issues a token"""
    _fence_off(rest_api, monkeypatch, OTHER_TENANT)

    response = rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD}, unauthorized=True)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['token']


def test_another_tenant_is_served_by_api_key_and_token_beside_an_unavailable_one(
    rest_api, cloud_tenant, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both request channels of a healthy tenant are served"""
    _fence_off(rest_api, monkeypatch, OTHER_TENANT)

    bearer = rest_api.get(PROTECTED_URL, environ_overrides=cloud_auth_header(rest_api, USER_ID, cloud_tenant))

    assert _with_api_key(rest_api).status_code == HTTPStatus.OK
    assert bearer.status_code == HTTPStatus.OK
