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
What `POST /auth/login` answers in hosted cloud mode - and what any route answers for the connector's own error

The portal check and the tenant helpers are replaced one failure at a time; the route, its decorators and the app's
error handlers are real. Only the caller's credentials and account answer 4xx: an unreadable tenant user is a 500
(it was the 401 *"Invalid user or password"*), a portal answer without a `subscriptions` key the 401 an empty one
gets (it was a 500). On an ordinary route the connector's `DatabaseConnectionError` now gets past the route's error
tail to the app's handler: 503 when a lost connection is behind it, 500 *"A database operation failed!"* otherwise
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest
from pymongo.errors import ConnectionFailure

from cmdb.errors.database import DatabaseConnectionError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.interface.rest_api.responses.error_handlers import DATABASE_OPERATION_FAILED_MSG, DATABASE_UNAVAILABLE_MSG
from cmdb.interface.rest_api.routes.auth_constants import CloudLoginMessage
from cmdb.manager.types_manager import TypesManager

from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
AUTH_HELPER: str = 'cmdb.interface.rest_api.routes.auth_helper'
CREDENTIALS: dict[str, str] = {'user_name': 'login-answers@x.io', 'password': 'pw'}
TYPE_URL: str = '/types/1'


def _login(rest_api, database_name: str, portal_answer: Any = 'one-subscription', retrieve: Any = None) -> Any:
    """POSTs the cloud login with the portal check and the tenant helpers replaced"""
    if portal_answer == 'one-subscription':
        portal_answer = {'email': CREDENTIALS['user_name'], 'subscriptions': [{'id': 1, 'database': database_name}]}

    with patch(f'{AUTH_HELPER}.check_user_in_service_portal', return_value=portal_answer), \
         patch(f'{AUTH_HELPER}.check_db_exists', return_value=True), \
         patch(f'{AUTH_HELPER}.set_admin_user'), \
         patch(f'{AUTH_HELPER}.retrieve_user', side_effect=retrieve):
        return rest_api.post(LOGIN_URL, json=CREDENTIALS)


def _answer(response: Any) -> tuple[int, str | None]:
    """The status and the message"""
    return response.status_code, response.get_json().get('message') if response.is_json else None


class TestTheCloudLogin:
    """Hosted cloud mode."""

    @pytest.fixture(autouse=True)
    def _hosted(self, rest_api, monkeypatch, database_manager) -> None:
        """Hosted cloud mode for every test"""
        enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

    def test_an_unreadable_tenant_user_is_a_500(self, rest_api, database_name: str) -> None:
        """The server's fault, not the caller's password"""
        assert _answer(_login(rest_api, database_name, retrieve=UsersManagerGetError('broken'))) == (
            HTTPStatus.INTERNAL_SERVER_ERROR, CloudLoginMessage.USER_UNREADABLE.value)

    def test_an_answer_without_a_subscriptions_key_is_a_401(self, rest_api, database_name: str) -> None:
        """Like an empty list - the missing key was a KeyError and a 500"""
        assert _answer(_login(rest_api, database_name, portal_answer={'email': CREDENTIALS['user_name']})) == (
            HTTPStatus.UNAUTHORIZED, CloudLoginMessage.NO_SUBSCRIPTION.value)

    def test_several_subscriptions_without_a_choice_answer_the_choices(self, rest_api, database_name: str) -> None:
        """Unchanged: id, name and short id of each"""
        answer: dict[str, Any] = {'email': CREDENTIALS['user_name'], 'subscriptions': [
            {'id': 1, 'name': 'one', 'database': database_name}, {'id': 2, 'name': 'two', 'database': 'other'},
        ]}

        response = _login(rest_api, database_name, portal_answer=answer)

        assert response.status_code == HTTPStatus.OK
        assert [choice['id'] for choice in response.get_json()] == [1, 2]


@pytest.mark.parametrize('lost, status, message', [
    (True, HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
    (False, HTTPStatus.INTERNAL_SERVER_ERROR, DATABASE_OPERATION_FAILED_MSG),
], ids=['lost-connection', 'other-failure'])
def test_an_ordinary_route_lets_the_connectors_error_reach_the_app(rest_api, lost: bool, status: HTTPStatus,
                                                                   message: str) -> None:
    """handle_route_errors no longer turns it into the route's own 500"""
    error = DatabaseConnectionError('down')

    if lost:
        error.__cause__ = ConnectionFailure('server gone')

    with patch.object(TypesManager, 'get_type', side_effect=error):
        assert _answer(rest_api.get(TYPE_URL)) == (status, message)
