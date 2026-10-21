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
What the cloud API-key channel (HTTP Basic + `x-api-key`) answers - through the real REST app in hosted-cloud mode

The Service Portal check and the tenant-user helpers are replaced, one failure at a time; everything else is the
real route. Only the caller's credentials and account answer 401 / 403; a portal fault and a server fault are 500s, a
database outage the app's 503 / 423 - none is the 400 *"Failed to verify API access!"* every one of them answered
"""
import base64
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerInsertError
from cmdb.errors.security import InvalidCloudUserError, NoAccessTokenError, RequestError, RequestTimeoutError
from cmdb.interface import route_utils as ru

from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

PROBE_URL: str = '/types/'
ROUTE_UTILS: str = 'cmdb.interface.route_utils'
API_KEY_ENVIRON: dict[str, str] = {
    'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(b'automation@x.io:secret').decode('ascii'),
    'HTTP_X_API_KEY': 'key',
}
LEVEL_FAILED_MESSAGE: str = 'Failed to verify API access!'


@pytest.fixture(autouse=True)
def _hosted(rest_api, monkeypatch, database_manager) -> None:
    """Hosted cloud mode for every test"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)


def _send(rest_api, database_name: str, check: Any = None, check_answer: Any = 'account', admin: Any = None,
          user: Any = 'tenant-user') -> Any:
    """Sends the API-key request with the portal check, the user sync and the user read replaced"""
    account: dict[str, Any] = {'email': 'automation@x.io', 'api_level': 3,
                               'subscriptions': [{'database': database_name, 'api_level': 3}]}
    tenant_user: Any = ru.CmdbUser(public_id=1, user_name='admin', active=True, group_id=1, database=database_name)

    with patch(f'{ROUTE_UTILS}.check_user_in_service_portal', side_effect=check,
               return_value=account if check_answer == 'account' else check_answer), \
         patch(f'{ROUTE_UTILS}.set_admin_user', side_effect=admin), \
         patch(f'{ROUTE_UTILS}.retrieve_user', return_value=tenant_user if user == 'tenant-user' else user):
        return rest_api.get(PROBE_URL, environ_overrides=API_KEY_ENVIRON)


def _answer(response: Any) -> tuple[int, str | None]:
    """The status and the message"""
    return response.status_code, response.get_json().get('message') if response.is_json else None


def test_a_valid_api_key_request_is_served(rest_api, database_name: str) -> None:
    """The control"""
    assert _send(rest_api, database_name).status_code == HTTPStatus.OK


@pytest.mark.parametrize('kwargs', [{'check': InvalidCloudUserError('refused')}, {'check_answer': None}],
                         ids=['refused', 'no-answer'])
def test_refused_credentials_are_a_401(rest_api, database_name: str, kwargs: dict[str, Any]) -> None:
    """The caller's fault, with its message"""
    assert _answer(_send(rest_api, database_name, **kwargs)) == (
        HTTPStatus.UNAUTHORIZED, ru.INVALID_API_CREDENTIALS_MESSAGE)


@pytest.mark.parametrize('error, message', [
    (NoAccessTokenError('none'), ru.PORTAL_NOT_CONFIGURED_MESSAGE),
    (RequestTimeoutError('slow'), ru.PORTAL_TIMEOUT_MESSAGE),
    (RequestError('down'), ru.PORTAL_REQUEST_FAILED_MESSAGE),
], ids=['not-configured', 'timeout', 'request'])
def test_a_portal_fault_is_a_500(rest_api, database_name: str, error: Exception, message: str) -> None:
    """Not the caller's fault"""
    assert _answer(_send(rest_api, database_name, check=error)) == (HTTPStatus.INTERNAL_SERVER_ERROR, message)


@pytest.mark.parametrize('outage, status', [
    (DocumentNetworkError('lost'), HTTPStatus.SERVICE_UNAVAILABLE),
    (DocumentLockTimeoutError('locked'), HTTPStatus.LOCKED),
], ids=['network', 'lock'])
def test_an_outage_is_the_app_handlers(rest_api, database_name: str, outage: Exception, status: HTTPStatus) -> None:
    """Both in the portal check's cache read and in the user sync, which no longer hides it"""
    assert _send(rest_api, database_name, check=outage).status_code == status
    assert _send(rest_api, database_name, admin=outage).status_code == status


def test_an_account_without_a_subscription_is_a_401(rest_api, database_name: str) -> None:
    """cloud_login's answer for the same account"""
    assert _answer(_send(rest_api, database_name, check_answer={'api_level': 3, 'subscriptions': []})) == (
        HTTPStatus.UNAUTHORIZED, ru.NO_SUBSCRIPTION_MESSAGE)


def test_a_tenant_user_the_server_cannot_store_is_a_500(rest_api, database_name: str) -> None:
    """The server's fault"""
    assert _answer(_send(rest_api, database_name, admin=UsersManagerInsertError('write'))) == (
        HTTPStatus.INTERNAL_SERVER_ERROR, ru.API_USER_NOT_STORED_MESSAGE)


def test_an_unknown_tenant_user_stays_a_403(rest_api, database_name: str) -> None:
    """Unchanged"""
    assert _answer(_send(rest_api, database_name, user=None)) == (HTTPStatus.FORBIDDEN, ru.API_USER_NOT_FOUND_MESSAGE)


def test_a_bug_is_a_500(rest_api, monkeypatch, database_name: str) -> None:
    """As production answers it - not the old 400"""
    monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)

    response = _send(rest_api, database_name, check=TypeError('bug'))

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert _answer(response)[1] != LEVEL_FAILED_MESSAGE
