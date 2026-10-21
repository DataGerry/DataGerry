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
Unit tests for the steps of `auth_helper.cloud_login`, each on its own

The portal check (`authenticate_cloud_login`), the subscriptions of the answer (`login_subscriptions`,
`list_subscription_choices`, `select_login_subscription`) and the tenant user (`prepare_cloud_login_user`). Only the
caller's credentials and account answer 4xx; a portal or server fault is a 500 with its own message, and a database
outage, the connector's error and a bug pass through for the app
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
from cmdb.errors.security import InvalidCloudUserError, NoAccessTokenError, RequestError, RequestTimeoutError
from cmdb.interface.rest_api.routes import auth_helper
from cmdb.interface.rest_api.routes.auth_constants import CloudLoginMessage
from cmdb.interface.route_utils import USER_DEACTIVATED_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.auth_helper'
DATABASE: str = 'tenant_db'
SUBSCRIPTION: dict[str, Any] = {'id': 1, 'name': 'one', 'short_id': 'o', 'database': DATABASE}
OTHER: dict[str, Any] = {'id': 2, 'name': 'two', 'short_id': 't', 'database': 'other_db'}
PORTAL_USER: dict[str, Any] = {'email': 'a@x.io', 'subscriptions': [SUBSCRIPTION]}


def _app(unavailable: frozenset[str] = frozenset()) -> Flask:
    """A bare app carrying what the steps read off it"""
    app = Flask(__name__)
    app.database_manager = MagicMock()
    app.unavailable_tenants = unavailable

    return app


def _refusal(call: Any) -> tuple[int, str]:
    """The status and message a step refuses with"""
    with pytest.raises(HTTPException) as refused:
        call()

    return refused.value.code, refused.value.description


class TestAuthenticateCloudLogin:
    """The portal check's own answers."""

    @pytest.mark.parametrize('error, status, message', [
        (InvalidCloudUserError('no'), HTTPStatus.FORBIDDEN, CloudLoginMessage.INVALID_CREDENTIALS),
        (NoAccessTokenError('no'), HTTPStatus.INTERNAL_SERVER_ERROR, CloudLoginMessage.PORTAL_NOT_CONFIGURED),
        (RequestTimeoutError('no'), HTTPStatus.INTERNAL_SERVER_ERROR, CloudLoginMessage.PORTAL_TIMEOUT),
        (RequestError('no'), HTTPStatus.INTERNAL_SERVER_ERROR, CloudLoginMessage.PORTAL_REQUEST_FAILED),
    ], ids=['refused', 'not-configured', 'timeout', 'request'])
    def test_each_portal_failure_has_its_answer(self, error: Exception, status: HTTPStatus,
                                                message: CloudLoginMessage) -> None:
        """Refused credentials are the caller's; the rest is the portal's fault"""
        with _app().test_request_context(), patch(f'{PATH}.check_user_in_service_portal', side_effect=error):
            assert _refusal(lambda: auth_helper.authenticate_cloud_login('a', 'b')) == (status, message.value)

    def test_no_answer_is_a_401(self) -> None:
        """Nothing to log in as"""
        with _app().test_request_context(), patch(f'{PATH}.check_user_in_service_portal', return_value=None):
            assert _refusal(lambda: auth_helper.authenticate_cloud_login('a', 'b')) == (
                HTTPStatus.UNAUTHORIZED, CloudLoginMessage.NO_PORTAL_ANSWER.value)

    @pytest.mark.parametrize('error', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'),
                                       DatabaseConnectionError('down'), RuntimeError('bug')],
                             ids=['network', 'lock', 'connector', 'bug'])
    def test_anything_else_passes_through(self, error: Exception) -> None:
        """The app's handlers answer it"""
        with _app().test_request_context(), patch(f'{PATH}.check_user_in_service_portal', side_effect=error):
            with pytest.raises(type(error)):
                auth_helper.authenticate_cloud_login('a', 'b')

    def test_answers_the_portal_user(self) -> None:
        """The control"""
        with _app().test_request_context(), patch(f'{PATH}.check_user_in_service_portal', return_value=PORTAL_USER):
            assert auth_helper.authenticate_cloud_login('a', 'b') is PORTAL_USER


class TestTheSubscriptions:
    """Which subscriptions an answer carries, and which one is logged into."""

    @pytest.mark.parametrize('answer, expected', [
        ({'subscriptions': [SUBSCRIPTION]}, [SUBSCRIPTION]), ({}, []), ({'subscriptions': None}, []),
        ({'subscriptions': 'flat'}, []),
    ], ids=['list', 'missing', 'null', 'not-a-list'])
    def test_login_subscriptions(self, answer: dict[str, Any], expected: list[Any]) -> None:
        """A missing key is no subscription - it was a KeyError and a 500"""
        assert auth_helper.login_subscriptions(answer) == expected

    def test_the_choices_carry_id_name_and_short_id(self) -> None:
        """Nothing else of a subscription"""
        assert auth_helper.list_subscription_choices([SUBSCRIPTION, {'id': 3}]) == [
            {'id': 1, 'name': 'one', 'short_id': 'o'}, {'id': 3, 'name': None, 'short_id': None},
        ]

    def test_the_only_subscription_is_taken_whatever_was_chosen(self) -> None:
        """As before"""
        assert auth_helper.select_login_subscription([SUBSCRIPTION], {'id': 99}) is SUBSCRIPTION

    def test_no_subscription_is_a_401(self) -> None:
        """Nothing to log into"""
        with _app().test_request_context():
            assert _refusal(lambda: auth_helper.select_login_subscription([], None)) == (
                HTTPStatus.UNAUTHORIZED, CloudLoginMessage.NO_SUBSCRIPTION.value)

    def test_the_chosen_subscription_is_found_by_its_id(self) -> None:
        """Among several"""
        assert auth_helper.select_login_subscription([SUBSCRIPTION, OTHER], {'id': 2}) is OTHER

    def test_a_chosen_subscription_that_is_not_the_users_is_a_400(self) -> None:
        """Unchanged"""
        with _app().test_request_context():
            assert _refusal(lambda: auth_helper.select_login_subscription([SUBSCRIPTION, OTHER], {'id': 9})) == (
                HTTPStatus.BAD_REQUEST, CloudLoginMessage.SUBSCRIPTION_NOT_FOUND.value)


class TestPrepareCloudLoginUser:
    """The tenant and its user."""

    @staticmethod
    def _prepare(subscription: dict[str, Any] = SUBSCRIPTION, exists: bool = True, admin: Any = None,
                 retrieve: Any = None, user: Any = SimpleNamespace(active=True),
                 unavailable: frozenset[str] = frozenset()) -> tuple[Any, MagicMock]:
        """Runs the step with the tenant helpers patched; the answer and the init_db_routine mock"""
        with _app(unavailable).test_request_context(), \
             patch(f'{PATH}.check_db_exists', return_value=exists), \
             patch(f'{PATH}.init_db_routine') as init, \
             patch(f'{PATH}.set_admin_user', side_effect=admin), \
             patch(f'{PATH}.retrieve_user', side_effect=retrieve, return_value=user):
            return auth_helper.prepare_cloud_login_user(PORTAL_USER, subscription), init

    def test_answers_the_tenant_user(self) -> None:
        """The control; an existing database is not initialised"""
        user, init = self._prepare()

        assert user.active is True
        init.assert_not_called()

    def test_a_new_tenant_database_is_initialised(self) -> None:
        """On first use"""
        _, init = self._prepare(exists=False)

        init.assert_called_once_with(DATABASE)

    def test_a_subscription_naming_no_database_is_a_401(self) -> None:
        """No tenant to log into"""
        assert _refusal(lambda: self._prepare(subscription={'id': 1})) == (
            HTTPStatus.UNAUTHORIZED, CloudLoginMessage.NO_SUBSCRIPTION.value)

    def test_an_unavailable_tenant_is_a_503(self) -> None:
        """Before anything is written"""
        assert _refusal(lambda: self._prepare(unavailable=frozenset({DATABASE})))[0] == HTTPStatus.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize('kwargs, message', [
        ({'admin': UsersManagerGetError('read')}, CloudLoginMessage.USER_UNREADABLE),
        ({'retrieve': UsersManagerGetError('read')}, CloudLoginMessage.USER_UNREADABLE),
        ({'admin': UsersManagerInsertError('write')}, CloudLoginMessage.USER_NOT_STORED),
    ], ids=['sync-read', 'user-read', 'sync-write'])
    def test_a_tenant_user_the_server_cannot_read_or_store_is_a_500(
            self, kwargs: dict[str, Any], message: CloudLoginMessage) -> None:
        """The server's fault - an unreadable user was the 401 "Invalid user or password" before"""
        assert _refusal(lambda: self._prepare(**kwargs)) == (HTTPStatus.INTERNAL_SERVER_ERROR, message.value)

    def test_an_unknown_user_is_a_401(self) -> None:
        """Unchanged"""
        assert _refusal(lambda: self._prepare(user=None)) == (
            HTTPStatus.UNAUTHORIZED, CloudLoginMessage.UNKNOWN_USER.value)

    def test_a_deactivated_user_is_a_401(self) -> None:
        """The tenant's flag decides"""
        assert _refusal(lambda: self._prepare(user=SimpleNamespace(active=False))) == (
            HTTPStatus.UNAUTHORIZED, USER_DEACTIVATED_MESSAGE)

    @pytest.mark.parametrize('error', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'),
                                       DatabaseConnectionError('down'), RuntimeError('bug')],
                             ids=['network', 'lock', 'connector', 'bug'])
    def test_anything_else_passes_through(self, error: Exception) -> None:
        """The app's handlers answer it"""
        with pytest.raises(type(error)):
            self._prepare(admin=error)
