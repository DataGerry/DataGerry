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
Unit tests for `auth_helper.cloud_login` and a deactivated account

The ServicePortal decides whether the credentials are right; the tenant's stored `active` flag still
decides whether that tenant's account may be used. What is pinned: a user the tenant stored as
deactivated is a 401 with the deactivation message and no token is generated, an active user is
issued one, and credentials the portal refused are the portal's refusal - the account's state is
never reached.

A tenant whose database failed its startup update is a 503 on both subscription paths (the only one, and
the one the user selected), before the database is created, written or read
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.route_utils import USER_DEACTIVATED_MESSAGE
from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
from cmdb.interface.rest_api.routes import auth_helper
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.auth_helper'
TENANT_DATABASE: str = 'tenant_db'
PORTAL_USER: dict[str, Any] = {
    'email': 'cloud@x.io', 'user_name': 'cloud', 'password': 'pw',
    'subscriptions': [{'id': 1, 'name': 'sub', 'database': TENANT_DATABASE, 'api_level': 1,
                       'config_item_limit': 10}],
}
PORTAL_REFUSAL: str = 'Invalid user data. Failed to login!'
OTHER_TENANT_DATABASE: str = 'other_tenant_db'
MULTI_SUBSCRIPTION_USER: dict[str, Any] = {
    **PORTAL_USER,
    'subscriptions': [
        {'id': 1, 'name': 'sub', 'database': TENANT_DATABASE, 'api_level': 1, 'config_item_limit': 10},
        {'id': 2, 'name': 'other', 'database': OTHER_TENANT_DATABASE, 'api_level': 1, 'config_item_limit': 10},
    ],
}


def _login(portal_answer: dict[str, Any] | None,
           stored_user: Any,
           unavailable_tenants: frozenset[str] = frozenset(),
           subscription: dict[str, Any] | None = None) -> tuple[HTTPException | None, MagicMock, MagicMock]:
    """Runs cloud_login against a stubbed portal and tenant store; returns the refusal, token and retrieve mocks."""
    app = Flask(__name__)
    app.database_manager = MagicMock()
    app.unavailable_tenants = unavailable_tenants

    with app.test_request_context(), \
         patch(f'{PATH}.check_user_in_service_portal', return_value=portal_answer), \
         patch(f'{PATH}.check_db_exists', return_value=True), \
         patch(f'{PATH}.set_admin_user'), \
         patch(f'{PATH}.retrieve_user', return_value=stored_user) as retrieve, \
         patch(f'{PATH}.generate_token_with_params', return_value=('t', 1, 2)) as token, \
         patch(f'{PATH}.LoginResponse'):
        try:
            auth_helper.cloud_login(PORTAL_USER['email'], PORTAL_USER['password'], subscription)
        except HTTPException as refused:
            return refused, token, retrieve

    return None, token, retrieve


def test_a_deactivated_tenant_user_gets_no_token() -> None:
    """The portal accepted the credentials, the tenant refuses the account: 401, no token generated"""
    refused, token, _ = _login(PORTAL_USER, SimpleNamespace(active=False, password='x'))

    assert refused is not None
    assert refused.code == HTTPStatus.UNAUTHORIZED
    assert refused.description == USER_DEACTIVATED_MESSAGE
    token.assert_not_called()


def test_an_active_tenant_user_is_issued_a_token() -> None:
    """The check lets an active account through untouched"""
    refused, token, retrieve = _login(PORTAL_USER, SimpleNamespace(active=True, password='x'))

    assert refused is None
    retrieve.assert_called_once_with(PORTAL_USER, TENANT_DATABASE)
    token.assert_called_once()


def test_a_portal_refusal_never_reaches_the_account() -> None:
    """Wrong credentials are the portal's answer; the tenant's account is never read"""
    refused, token, retrieve = _login(None, SimpleNamespace(active=False, password='x'))

    assert refused.code == HTTPStatus.UNAUTHORIZED
    assert refused.description == PORTAL_REFUSAL
    retrieve.assert_not_called()
    token.assert_not_called()


def test_the_only_subscription_of_an_unavailable_tenant_is_a_503() -> None:
    """A single-subscription login to a tenant that failed its startup update reads and writes nothing"""
    with patch(f'{PATH}.init_db_routine') as init_db, patch(f'{PATH}.check_db_exists') as db_exists:
        refused, token, retrieve = _login(
            PORTAL_USER, SimpleNamespace(active=True, password='x'), frozenset({TENANT_DATABASE}),
        )

    assert refused.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert refused.description == TENANT_UNAVAILABLE_RESPONSE_MESSAGE
    db_exists.assert_not_called()
    init_db.assert_not_called()
    retrieve.assert_not_called()
    token.assert_not_called()


def test_a_selected_subscription_of_an_unavailable_tenant_is_a_503() -> None:
    """The subscription the user chose is checked too"""
    refused, token, retrieve = _login(
        MULTI_SUBSCRIPTION_USER, SimpleNamespace(active=True, password='x'),
        frozenset({OTHER_TENANT_DATABASE}), {'id': 2},
    )

    assert refused.code == HTTPStatus.SERVICE_UNAVAILABLE
    retrieve.assert_not_called()
    token.assert_not_called()


def test_a_subscription_beside_an_unavailable_tenant_logs_in() -> None:
    """Choosing a healthy tenant works while another of the user's tenants is fenced off"""
    refused, token, retrieve = _login(
        MULTI_SUBSCRIPTION_USER, SimpleNamespace(active=True, password='x'),
        frozenset({OTHER_TENANT_DATABASE}), {'id': 1},
    )

    assert refused is None
    retrieve.assert_called_once_with(MULTI_SUBSCRIPTION_USER, TENANT_DATABASE)
    token.assert_called_once()
