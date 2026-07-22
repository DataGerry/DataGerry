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
Unit tests for cmdb.interface.route_utils

The helpers here are pure transport-layer glue around Flask's ``current_app`` / ``request`` and the
domain managers. Every test drives a helper inside a BaseCmdbApp ``test_request_context`` with the
managers, TokenValidator/TokenGenerator, AuthModule, ``requests`` and ``os.getenv`` patched at the
module path - no Mongo, no service-portal HTTP. The ``cloud_mode`` / ``local_mode`` flags on the app
select the branch under test.

These pin: the rights checks (``user_has_right`` / ``validate_right_cloud_api`` / ``right_required``),
the error-mapping decorators (``handle_db_errors`` 503/423, ``handle_oc_errors`` 500s), the
request-user injection / API-access decorators, the Authorization-header parsing and Basic/Bearer
authentication, the service-portal check with its cache-sync helpers, and the small DB/user helpers.
"""
# pylint: disable=protected-access  # these tests intentionally exercise module-private helpers
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch, mock_open

import pytest
from werkzeug.exceptions import HTTPException

import cmdb.interface.route_utils as ru
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.errors.database import (
    SetDatabaseError,
    DatabaseNotFoundError,
    DocumentNetworkError,
    DocumentLockTimeoutError,
)
from cmdb.errors.security import (
    TokenValidationError,
    InvalidCloudUserError,
    NoAccessTokenError,
    MissingApiKeyError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
from cmdb.errors.open_celium import AuthError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.route_utils'

# Module-level aliases for the double-underscore module functions (avoids name-mangling inside classes)
_get_x_api_key: Callable[..., Any] = getattr(ru, '__get_x_api_key')
_get_request_api_user: Callable[..., Any] = getattr(ru, '__get_request_api_user')
_get_request_auth_method: Callable[..., Any] = getattr(ru, '__get_request_auth_method')
_check_api_level: Callable[..., Any] = getattr(ru, '__check_api_level')

# Base64 of "user@test.com:secret"
BASIC_CREDENTIALS: str = 'dXNlckB0ZXN0LmNvbTpzZWNyZXQ='
BASIC_HEADER: str = f'Basic {BASIC_CREDENTIALS}'
BEARER_HEADER: str = 'Bearer sometoken'

DECODED_TOKEN: dict[str, Any] = {
    'DATAGERRY': {'value': {'user': {'public_id': 42, 'database': 'cloud_db'}}}
}


def _portal_env(key: str) -> str:
    """Stand-in for os.getenv covering the service-portal env vars used by validate_subscription_user."""
    return 'token' if key == 'X-ACCESS-TOKEN' else 'http://sp'


def _app(cloud_mode: bool = False, local_mode: bool = False) -> BaseCmdbApp:
    """Builds a BaseCmdbApp with a stub database_manager and the given mode flags."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = cloud_mode
    app.local_mode = local_mode

    return app


# =================================================== user_has_right ================================================= #

class TestUserHasRight:
    """``user_has_right`` resolves rights either from a passed user or the Authorization token."""

    def test_delegates_to_cloud_api_when_request_user_given(self) -> None:
        """A provided request_user short-circuits to validate_right_cloud_api."""
        user = SimpleNamespace(database='db', group_id=1)
        with patch(f'{MODULE_PATH}.validate_right_cloud_api', return_value=True) as mocked:
            with _app().test_request_context():
                assert ru.user_has_right('base.right', user) is True
        mocked.assert_called_once_with('base.right', user)

    def test_missing_authorization_header_aborts_401(self) -> None:
        """No Authorization header aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'), patch(f'{MODULE_PATH}.GroupsManager'):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.user_has_right('base.right')
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_invalid_token_aborts_401(self) -> None:
        """A token that fails validation aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'), patch(f'{MODULE_PATH}.GroupsManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.user_has_right('base.right')
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_returns_true_when_group_has_right(self) -> None:
        """A group holding the right returns True."""
        users_manager = MagicMock()
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = True
        users_manager.get_user.return_value = SimpleNamespace(group_id=7)
        groups_manager.get_group.return_value = group

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.user_has_right('base.right') is True

    def test_falls_back_to_extended_right_and_cloud_branch(self) -> None:
        """When the direct right is missing, the extended right is checked (cloud_mode branch)."""
        users_manager = MagicMock()
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = True
        users_manager.get_user.return_value = SimpleNamespace(group_id=7)
        groups_manager.get_group.return_value = group

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.user_has_right('base.right') is True
        group.has_extended_right.assert_called_once_with('base.right')

    def test_returns_false_on_lookup_exception(self) -> None:
        """Any exception during user/group resolution returns False."""
        users_manager = MagicMock()
        users_manager.get_user.side_effect = RuntimeError('boom')

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.GroupsManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.user_has_right('base.right') is False


# ================================================== handle_db_errors ================================================ #

class TestHandleDbErrors:
    """``handle_db_errors`` maps DB errors to 503 / 423 and passes success through."""

    def test_passes_result_through(self) -> None:
        """A handler that returns normally is not touched."""
        wrapped = ru.handle_db_errors(lambda: 'ok')
        with _app().test_request_context():
            assert wrapped() == 'ok'

    def test_network_error_aborts_503(self) -> None:
        """DocumentNetworkError becomes 503 Service Unavailable."""
        def _handler() -> None:
            raise DocumentNetworkError('down')

        with _app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.handle_db_errors(_handler)()
        assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_lock_timeout_aborts_423(self) -> None:
        """DocumentLockTimeoutError becomes 423 Locked."""
        def _handler() -> None:
            raise DocumentLockTimeoutError('locked')

        with _app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.handle_db_errors(_handler)()
        assert exc_info.value.code == HTTPStatus.LOCKED


# ================================================== handle_oc_errors ================================================ #

class TestHandleOcErrors:
    """``handle_oc_errors`` maps OpenCelium/network errors to 500 and re-raises HTTPExceptions."""

    def test_passes_result_through(self) -> None:
        """A handler that returns normally is not touched."""
        wrapped = ru.handle_oc_errors()(lambda: 'ok')
        with _app().test_request_context():
            assert wrapped() == 'ok'

    def test_reraises_http_exception(self) -> None:
        """An HTTPException raised by the handler is re-raised unchanged."""
        def _handler() -> None:
            raise HTTPException(description='teapot')

        with _app().test_request_context():
            with pytest.raises(HTTPException):
                ru.handle_oc_errors()(_handler)()

    @pytest.mark.parametrize('error', [
        AuthError('a'),
        ru.ConnectTimeout('c'),
        ru.ConnectionError('r'),
        ru.Timeout('t'),
        ValueError('generic'),
    ])
    def test_maps_errors_to_500(self, error: Exception) -> None:
        """Every recognised OpenCelium/network error and a generic one abort with 500."""
        def _handler() -> None:
            raise error

        with _app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.handle_oc_errors('doing things')(_handler)()
        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR


# ================================================ insert_request_user =============================================== #

class TestInsertRequestUser:
    """``insert_request_user`` injects the resolved user as ``request_user``."""

    def test_cloud_api_key_passes_through(self) -> None:
        """In cloud mode an x-api-key request skips token validation entirely."""
        handler = MagicMock(return_value='done')
        with patch(f'{MODULE_PATH}.UsersManager'):
            with _app(cloud_mode=True).test_request_context(headers={'x-api-key': 'k'}):
                assert ru.insert_request_user(handler)() == 'done'
        handler.assert_called_once()

    def test_missing_header_aborts_401(self) -> None:
        """A request without an Authorization header aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_invalid_token_aborts_401(self) -> None:
        """A token that fails validation aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_generic_token_error_aborts_401(self) -> None:
        """Any non-token-specific error during decode aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = RuntimeError('boom')
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_injects_user_and_calls_handler(self) -> None:
        """A resolved user is injected as request_user (cloud_mode db branch)."""
        users_manager = MagicMock()
        user = SimpleNamespace(public_id=42)
        users_manager.get_user.return_value = user
        captured: dict[str, Any] = {}

        def _handler(**kwargs: Any) -> str:
            captured.update(kwargs)
            return 'ran'

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.insert_request_user(_handler)() == 'ran'
        assert captured['request_user'] is user

    def test_missing_user_aborts_401(self) -> None:
        """When the user cannot be found the request aborts with 401."""
        users_manager = MagicMock()
        users_manager.get_user.return_value = None

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_user_value_error_aborts_401(self) -> None:
        """A ValueError while resolving the user aborts with 401."""
        users_manager = MagicMock()
        users_manager.get_user.side_effect = ValueError('bad')

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = {'DATAGERRY': {'value': {'user': {'public_id': 1}}}}
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_user_lookup_exception_aborts_401(self) -> None:
        """An exception while resolving the user aborts with 401."""
        users_manager = MagicMock()
        users_manager.get_user.side_effect = RuntimeError('boom')

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = {'DATAGERRY': {'value': {'user': {'public_id': 1}}}}
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED


# ================================================= verify_api_access ================================================ #

class TestVerifyApiAccess:
    """``verify_api_access`` gates cloud API access by auth method and API level."""

    def test_non_cloud_passes_through(self) -> None:
        """Outside cloud mode the decorator is a no-op."""
        handler = MagicMock(return_value='ok')
        with _app(cloud_mode=False).test_request_context():
            assert ru.verify_api_access()(handler)() == 'ok'
        handler.assert_called_once()

    def test_basic_success_injects_user(self) -> None:
        """A valid Basic login resolves the admin user and injects request_user."""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        user_model = SimpleNamespace(public_id=1)
        captured: dict[str, Any] = {}

        def _handler(**kwargs: Any) -> str:
            captured.update(kwargs)
            return 'ran'

        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=user_model), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                assert ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(_handler)() == 'ran'
        assert captured['request_user'] is user_model

    def test_basic_user_not_found_aborts_403(self) -> None:
        """When retrieve_user returns nothing the request aborts with 403."""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=None):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_super_admin_skips_user_resolution(self) -> None:
        """A SUPER_ADMIN requirement does not resolve/inject a request_user."""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 2}], 'api_level': 2}
        handler = MagicMock(return_value='ok')
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user') as set_admin, \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                assert ru.verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)(handler)() == 'ok'
        set_admin.assert_not_called()

    def test_insufficient_api_level_aborts_403(self) -> None:
        """A user below the required API level aborts with 403."""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=False):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_reraises_http_exception(self) -> None:
        """An HTTPException from the auth flow is re-raised unchanged."""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', side_effect=HTTPException()):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException):
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()

    def test_jwt_method_skips_basic_flow(self) -> None:
        """A JWT (Bearer) auth method skips the Basic-login block and runs the handler."""
        handler = MagicMock(return_value='ok')
        with _app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(handler)() == 'ok'
        handler.assert_called_once()

    def test_generic_error_aborts_400(self) -> None:
        """A generic failure during verification aborts with 400."""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', side_effect=RuntimeError('boom')):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ============================================ request header primitives ============================================= #

class TestRequestHeaderPrimitives:
    """The small header-inspection helpers (x-api-key, api user, auth method)."""

    def test_get_x_api_key_present_and_absent(self) -> None:
        """The x-api-key header is returned when present, else None."""
        with _app().test_request_context(headers={'x-api-key': 'abc'}):
            assert _get_x_api_key() == 'abc'
        with _app().test_request_context():
            assert _get_x_api_key() is None

    def test_get_request_api_user_basic_returns_credentials(self) -> None:
        """A Basic Authorization header yields the decoded email/password dict."""
        with _app().test_request_context(headers={'Authorization': BASIC_HEADER}):
            result = _get_request_api_user()
        assert result == {'email': 'user@test.com', 'password': 'secret'}

    def test_get_request_api_user_bearer_returns_none(self) -> None:
        """A non-Basic header yields None."""
        with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert _get_request_api_user() is None

    def test_get_request_api_user_missing_header_returns_none(self) -> None:
        """A missing Authorization header is handled and yields None."""
        with _app().test_request_context():
            assert _get_request_api_user() is None

    def test_get_request_api_user_schemeless_treated_as_bearer(self) -> None:
        """A single-token header (no scheme) is treated as bearer and yields None."""
        with _app().test_request_context(headers={'Authorization': 'rawtoken'}):
            assert _get_request_api_user() is None

    def test_get_request_auth_method_basic(self) -> None:
        """A 'Basic ' header maps to AuthMethod.BASIC."""
        with _app().test_request_context(headers={'Authorization': BASIC_HEADER}):
            assert _get_request_auth_method() == AuthMethod.BASIC

    def test_get_request_auth_method_bearer(self) -> None:
        """A 'Bearer ' header maps to AuthMethod.JWT."""
        with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert _get_request_auth_method() == AuthMethod.JWT

    def test_get_request_auth_method_invalid_aborts_400(self) -> None:
        """An unrecognised auth scheme aborts with 400."""
        with _app().test_request_context(headers={'Authorization': 'Digest xyz'}):
            with pytest.raises(HTTPException) as exc_info:
                _get_request_auth_method()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_get_request_auth_method_missing_aborts_400(self) -> None:
        """A missing header aborts with 400."""
        with _app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _get_request_auth_method()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ================================================= __check_api_level ================================================ #

class TestCheckApiLevel:
    """``__check_api_level`` compares a user's API level against the requirement."""

    def test_non_cloud_returns_true(self) -> None:
        """Outside cloud mode the check always passes."""
        with _app(cloud_mode=False).test_request_context():
            assert _check_api_level({}, ApiLevel.ADMIN) is True

    def test_no_user_returns_false(self) -> None:
        """A missing user instance fails the check."""
        with _app(cloud_mode=True).test_request_context():
            assert _check_api_level(None, ApiLevel.ADMIN) is False

    def test_locked_level_returns_false(self) -> None:
        """A LOCKED requirement always fails."""
        with _app(cloud_mode=True).test_request_context():
            assert _check_api_level({'api_level': 3}, ApiLevel.LOCKED) is False

    def test_super_admin_compares_top_level(self) -> None:
        """SUPER_ADMIN compares the top-level api_level field."""
        with _app(cloud_mode=True).test_request_context():
            assert _check_api_level({'api_level': 2}, ApiLevel.SUPER_ADMIN) is True
            assert _check_api_level({'api_level': 1}, ApiLevel.SUPER_ADMIN) is False

    def test_admin_compares_subscription_level(self) -> None:
        """A non-super requirement compares the first subscription's api_level."""
        with _app(cloud_mode=True).test_request_context():
            assert _check_api_level({'subscriptions': [{'api_level': 1}]}, ApiLevel.ADMIN) is True

    def test_malformed_user_returns_false(self) -> None:
        """A user dict missing the expected keys fails safely."""
        with _app(cloud_mode=True).test_request_context():
            assert _check_api_level({'subscriptions': []}, ApiLevel.ADMIN) is False


# ================================================== right_required ================================================== #

class TestRightRequired:
    """``right_required`` gates a route on a group right (requires insert_request_user)."""

    def test_missing_request_user_aborts_400(self) -> None:
        """Without a request_user kwarg the decorator aborts with 400."""
        with patch(f'{MODULE_PATH}.GroupsManager'):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.right_required('base.right')(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_has_right_calls_handler(self) -> None:
        """A group with the right runs the wrapped handler (cloud_mode branch)."""
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = True
        groups_manager.get_group.return_value = group
        handler = MagicMock(return_value='ran')
        user = SimpleNamespace(database='db', group_id=1)

        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app(cloud_mode=True).test_request_context():
                assert ru.right_required('base.right')(handler)(request_user=user) == 'ran'

    def test_extended_right_calls_handler(self) -> None:
        """A group with only the extended right still runs the handler."""
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = True
        groups_manager.get_group.return_value = group
        handler = MagicMock(return_value='ran')
        user = SimpleNamespace(database='db', group_id=1)

        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                assert ru.right_required('base.right')(handler)(request_user=user) == 'ran'

    def test_no_right_aborts_403(self) -> None:
        """A group lacking the right (and extended) aborts with 403."""
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = False
        groups_manager.get_group.return_value = group
        user = SimpleNamespace(database='db', group_id=1)

        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.right_required('base.right')(lambda **_: None)(request_user=user)
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_group_lookup_error_aborts_404(self) -> None:
        """A GroupsManagerGetError aborts with 404."""
        groups_manager = MagicMock()
        groups_manager.get_group.side_effect = GroupsManagerGetError('nope')
        user = SimpleNamespace(database='db', group_id=1)

        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.right_required('base.right')(lambda **_: None)(request_user=user)
        assert exc_info.value.code == HTTPStatus.NOT_FOUND

    def test_generic_error_aborts_403(self) -> None:
        """A generic error during the check aborts with 403."""
        groups_manager = MagicMock()
        groups_manager.get_group.side_effect = RuntimeError('boom')
        user = SimpleNamespace(database='db', group_id=1)

        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.right_required('base.right')(lambda **_: None)(request_user=user)
        assert exc_info.value.code == HTTPStatus.FORBIDDEN


# ============================================ parse_authorization_header ============================================ #

class TestParseAuthorizationHeader:
    """``parse_authorization_header`` dispatches Basic/Bearer to the auth helpers."""

    def test_empty_header_returns_none(self) -> None:
        """An empty header yields None."""
        assert ru.parse_authorization_header('') is None

    def test_basic_delegates_to_authenticate_basic(self) -> None:
        """A Basic header delegates to _authenticate_basic with the credentials."""
        with patch(f'{MODULE_PATH}._authenticate_basic', return_value='jwt') as mocked:
            assert ru.parse_authorization_header(BASIC_HEADER) == 'jwt'
        mocked.assert_called_once_with(BASIC_CREDENTIALS)

    def test_bearer_delegates_to_validate_bearer(self) -> None:
        """A Bearer header delegates to _validate_bearer with the token."""
        with patch(f'{MODULE_PATH}._validate_bearer', return_value='sometoken') as mocked:
            assert ru.parse_authorization_header(BEARER_HEADER) == 'sometoken'
        mocked.assert_called_once_with('sometoken')

    def test_valueless_header_falls_back_to_bearer(self) -> None:
        """A single-token header (no scheme) is treated as a bearer token."""
        with patch(f'{MODULE_PATH}._validate_bearer', return_value='rawtoken') as mocked:
            assert ru.parse_authorization_header('rawtoken') == 'rawtoken'
        mocked.assert_called_once_with('rawtoken')

    def test_unknown_scheme_returns_none(self) -> None:
        """An unsupported scheme yields None."""
        assert ru.parse_authorization_header('Digest abc') is None


# ================================================ _authenticate_basic =============================================== #

class TestAuthenticateBasic:
    """``_authenticate_basic`` exchanges Basic credentials for a fresh JWT."""

    def _patches(self, login_result: Any = None, token: str = 'jwt') -> Any:
        """Patches the managers and auth/token machinery used by _authenticate_basic."""
        auth_module = MagicMock()
        auth_module.login.return_value = login_result
        auth_module_cls = MagicMock(return_value=auth_module)
        # __DEFAULT_SETTINGS__ is read off the class - MagicMock does not auto-create dunder attrs
        auth_module_cls.__DEFAULT_SETTINGS__ = {}
        token_gen = MagicMock()
        token_gen.generate_token.return_value = token
        return patch.multiple(
            MODULE_PATH,
            UsersManager=MagicMock(),
            SecurityManager=MagicMock(),
            SettingsManager=MagicMock(),
            AuthModule=auth_module_cls,
            TokenGenerator=MagicMock(return_value=token_gen),
        )

    def test_non_cloud_success_returns_token(self) -> None:
        """Outside cloud mode a successful login returns a freshly generated token."""
        user = MagicMock()
        user.get_public_id.return_value = 5
        with self._patches(login_result=user, token='jwt-token'):
            with _app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) == 'jwt-token'

    def test_cloud_portal_rejects_returns_none(self) -> None:
        """In cloud mode, a portal that rejects the user yields None."""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=None):
            with _app(cloud_mode=True).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_cloud_local_mode_uses_subscription_db(self) -> None:
        """In cloud+local mode the target db is taken from the first subscription."""
        user = MagicMock()
        user.get_public_id.return_value = 5
        user.database = 'sub_db'
        portal_user = {'subscriptions': [{'database': 'sub_db'}], 'database': 'ignored'}
        with self._patches(login_result=user), \
             patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=portal_user):
            with _app(cloud_mode=True, local_mode=True).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) == 'jwt'

    def test_cloud_non_local_uses_user_database(self) -> None:
        """In cloud (non-local) mode the target db comes from the portal user's 'database'."""
        user = MagicMock()
        user.get_public_id.return_value = 5
        user.database = 'the_db'
        portal_user = {'database': 'the_db'}
        with self._patches(login_result=user), \
             patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=portal_user):
            with _app(cloud_mode=True, local_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) == 'jwt'

    def test_login_exception_returns_none(self) -> None:
        """An exception raised by AuthModule.login yields None."""
        auth_module = MagicMock()
        auth_module.login.side_effect = RuntimeError('bad creds')
        auth_module_cls = MagicMock(return_value=auth_module)
        auth_module_cls.__DEFAULT_SETTINGS__ = {}
        with patch.multiple(
            MODULE_PATH,
            UsersManager=MagicMock(),
            SecurityManager=MagicMock(),
            SettingsManager=MagicMock(),
            AuthModule=auth_module_cls,
        ):
            with _app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_no_user_returns_none(self) -> None:
        """A login that returns no user yields None."""
        with self._patches(login_result=None):
            with _app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_set_database_error_returns_none(self) -> None:
        """A SetDatabaseError is caught and yields None."""
        with patch(f'{MODULE_PATH}.UsersManager', side_effect=SetDatabaseError('bad db')):
            with _app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_generic_error_returns_none(self) -> None:
        """A generic error (e.g. malformed base64) yields None."""
        with _app(cloud_mode=False).test_request_context():
            assert ru._authenticate_basic('not-valid-base64!!') is None


# ================================================== _validate_bearer ================================================ #

class TestValidateBearer:
    """``_validate_bearer`` returns the token unchanged when it validates."""

    def test_valid_token_returned(self) -> None:
        """A token that decodes and validates is returned unchanged."""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context():
                assert ru._validate_bearer('sometoken') == 'sometoken'

    def test_invalid_token_returns_none(self) -> None:
        """A token that fails validation yields None."""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.validate_token.side_effect = TokenValidationError('bad')
            with _app().test_request_context():
                assert ru._validate_bearer('sometoken') is None


# =============================================== validate_right_cloud_api =========================================== #

class TestValidateRightCloudApi:
    """``validate_right_cloud_api`` resolves a right from the request user's group."""

    def _user(self) -> SimpleNamespace:
        """A minimal cloud request user."""
        return SimpleNamespace(database='db', group_id=1)

    def test_direct_right_true(self) -> None:
        """A group holding the right returns True."""
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = True
        groups_manager.get_group.return_value = group
        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                assert ru.validate_right_cloud_api('base.right', self._user()) is True

    def test_extended_right_true(self) -> None:
        """A group with only the extended right returns True."""
        groups_manager = MagicMock()
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = True
        groups_manager.get_group.return_value = group
        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                assert ru.validate_right_cloud_api('base.right', self._user()) is True

    def test_exception_returns_false(self) -> None:
        """An exception during resolution returns False."""
        groups_manager = MagicMock()
        groups_manager.get_group.side_effect = RuntimeError('boom')
        with patch(f'{MODULE_PATH}.GroupsManager', return_value=groups_manager):
            with _app().test_request_context():
                assert ru.validate_right_cloud_api('base.right', self._user()) is False


# ============================================ check_user_in_service_portal ========================================== #

class TestCheckUserInServicePortal:
    """``check_user_in_service_portal`` validates users locally or via the portal + cache."""

    def test_local_mode_delegates_to_local_loader(self) -> None:
        """In local mode the local test-user loader is used."""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value={'email': 'x'}) as loader:
            with _app(local_mode=True).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p') == {'email': 'x'}
        loader.assert_called_once_with('x', 'p')

    def test_api_key_required_without_key_returns_none(self) -> None:
        """When an API key is required but absent, None is returned early."""
        with patch(f'{MODULE_PATH}.CachedUserManager'), patch(f'{MODULE_PATH}.SecurityManager'):
            with _app(local_mode=False).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p', None, api_key_required=True) is None

    def test_cache_hit_returns_cached_user(self) -> None:
        """A validated cached user is returned without hitting the portal."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = True
        cached_mgr.get_validated_user_data.return_value = {'email': 'x', 'cached': True}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user') as portal:
            with _app(local_mode=False).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p') == {'email': 'x', 'cached': True}
        portal.assert_not_called()

    def test_cache_hit_invalid_falls_through_to_portal(self) -> None:
        """A cached-but-invalid user falls through to portal validation."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = True
        cached_mgr.get_validated_user_data.return_value = None
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': []}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user) as portal, \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user'):
            with _app(local_mode=False).test_request_context():
                ru.check_user_in_service_portal('x', 'p')
        portal.assert_called_once()

    def test_empty_portal_result_skips_sync(self) -> None:
        """When the portal returns no user, no cache sync happens and the falsy value is returned."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=None), \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user') as sync_fe:
            with _app(local_mode=False).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p') is None
        sync_fe.assert_not_called()

    def test_cache_miss_validates_and_syncs_frontend(self) -> None:
        """A cache miss validates against the portal and syncs the frontend cache."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': []}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user), \
             patch(f'{MODULE_PATH}._sync_frontend_cached_user') as sync_fe:
            with _app(local_mode=False).test_request_context():
                result = ru.check_user_in_service_portal('x', 'p')
        assert result['password'] == 'hmac'
        sync_fe.assert_called_once()

    def test_cache_miss_with_api_key_syncs_api(self) -> None:
        """A cache miss on an API login syncs the API cache instead."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hmac'
        portal_user = {'email': 'x', 'password': 'p', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager', return_value=security_mgr), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=portal_user), \
             patch(f'{MODULE_PATH}._sync_api_cached_user') as sync_api:
            with _app(local_mode=False).test_request_context():
                ru.check_user_in_service_portal('x', 'p', 'the-key', api_key_required=True)
        sync_api.assert_called_once()

    def test_known_error_is_reraised(self) -> None:
        """A recognised portal error propagates unchanged."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', side_effect=InvalidCloudUserError('no')):
            with _app(local_mode=False).test_request_context():
                with pytest.raises(InvalidCloudUserError):
                    ru.check_user_in_service_portal('x', 'p')

    def test_unexpected_error_wrapped_in_exception(self) -> None:
        """An unexpected error is wrapped and raised as a generic Exception."""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', side_effect=RuntimeError('boom')):
            with _app(local_mode=False).test_request_context():
                with pytest.raises(Exception):
                    ru.check_user_in_service_portal('x', 'p')


# ================================================ _load_local_test_user ============================================= #

class TestLoadLocalTestUser:
    """``_load_local_test_user`` matches credentials against the local JSON fixture."""

    def test_matching_user_returned(self) -> None:
        """A known email with the right password returns the user."""
        users = {'x@test.com': {'password': 'secret', 'user_name': 'x'}}
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value=users):
            assert ru._load_local_test_user('x@test.com', 'secret') == users['x@test.com']

    def test_wrong_password_returns_none(self) -> None:
        """A known email with the wrong password returns None."""
        users = {'x@test.com': {'password': 'secret'}}
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value=users):
            assert ru._load_local_test_user('x@test.com', 'wrong') is None

    def test_unknown_user_returns_none(self) -> None:
        """An unknown email returns None."""
        with patch('builtins.open', mock_open()), patch(f'{MODULE_PATH}.json.load', return_value={}):
            assert ru._load_local_test_user('nobody@test.com', 'x') is None

    def test_file_error_returns_none(self) -> None:
        """A failure reading the fixture returns None."""
        with patch('builtins.open', side_effect=OSError('missing')):
            assert ru._load_local_test_user('x@test.com', 'x') is None


# ================================================ _sync_api_cached_user ============================================= #

class TestSyncApiCachedUser:
    """``_sync_api_cached_user`` maintains the cache for an external-API login."""

    @staticmethod
    def _security_mgr() -> MagicMock:
        """A SecurityManager stub whose generate_hmac maps any password to a fixed digest."""
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hashed-pw'
        return security_mgr

    def test_existing_valid_user_stamps_api_key(self) -> None:
        """A cached user whose password is the current HMAC just gets the api_key stamped."""
        cached_mgr = MagicMock()
        # Stored password already equals generate_hmac(...) -> entry is current
        cached_mgr.get_cached_user.return_value = {'password': 'hashed-pw', 'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        ru._sync_api_cached_user(
            cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=True
        )
        cached_mgr.update_cached_user_api_key.assert_called_once_with('x', 'db', 'the-key')
        cached_mgr.delete_cached_user.assert_not_called()
        cached_mgr.insert_cached_user.assert_not_called()

    def test_existing_stale_password_user_is_healed(self) -> None:
        """Self-heal: a cached entry with a stale (e.g. legacy plaintext) password is dropped and rebuilt.

        The old bug stored the password in plaintext, so the cache never validated and every request hit
        the portal. Such an entry must now be deleted and recreated with a correctly hashed password.
        """
        cached_mgr = MagicMock()
        # Stored plaintext password != generate_hmac(...) -> entry is stale
        cached_mgr.get_cached_user.return_value = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            ru._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=True
            )
        cached_mgr.delete_cached_user.assert_called_once_with('x')
        cached_mgr.update_cached_user_api_key.assert_not_called()
        cached = cached_mgr.insert_cached_user.call_args.args[0]
        assert cached['password'] == 'hashed-pw'
        assert cached['subscriptions'][0]['api_key'] == 'the-key'

    def test_uncached_user_without_db_does_nothing(self) -> None:
        """An uncached user whose database does not exist is not created."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=False):
            ru._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_not_called()

    def test_uncached_user_with_db_inserts_full_data(self) -> None:
        """An uncached user with an existing db is cached from the full subscription list."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'plain', 'subscriptions': [{'database': 'db'}, {'database': 'other'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            ru._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_called_once_with(full)
        assert full['subscriptions'][0]['api_key'] == 'the-key'

    def test_uncached_user_password_is_hashed_before_caching(self) -> None:
        """Regression: the cached password is the HMAC, not the plaintext the portal returns.

        The plaintext bug meant the cache never validated (the check hashes the login password), so
        every API request fell back to the service portal despite the user being 'cached'.
        """
        cached_mgr = MagicMock()
        security_mgr = self._security_mgr()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'Init1234!', 'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            ru._sync_api_cached_user(
                cached_mgr, security_mgr, 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        security_mgr.generate_hmac.assert_called_once_with('Init1234!')
        cached = cached_mgr.insert_cached_user.call_args.args[0]
        assert cached['password'] == 'hashed-pw'

    def test_uncached_user_empty_full_refetch_does_not_insert(self) -> None:
        """When the full-subscription re-fetch returns nothing, no cache entry is created."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=None):
            ru._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_not_called()

    def test_uncached_user_with_db_no_matching_subscription(self) -> None:
        """A full list with no subscription matching the target db still caches (no api_key stamped)."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': [{'database': 'db'}]}
        full = {'password': 'plain', 'subscriptions': [{'database': 'other'}]}
        with patch(f'{MODULE_PATH}.check_db_exists', return_value=True), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value=full):
            ru._sync_api_cached_user(
                cached_mgr, self._security_mgr(), 'x', 'p', 'the-key', user_data, user_exists_in_cache=False
            )
        cached_mgr.insert_cached_user.assert_called_once_with(full)
        assert 'api_key' not in full['subscriptions'][0]


# ============================================ _cached_password_is_current =========================================== #

class TestCachedPasswordIsCurrent:
    """``_cached_password_is_current`` compares the stored password to the HMAC of the login password."""

    @staticmethod
    def _security_mgr() -> MagicMock:
        """A SecurityManager stub whose generate_hmac maps any password to a fixed digest."""
        security_mgr = MagicMock()
        security_mgr.generate_hmac.return_value = 'hashed-pw'
        return security_mgr

    def test_matching_hash_is_current(self) -> None:
        """A stored password equal to the HMAC of the login password is current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'password': 'hashed-pw'}
        assert ru._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is True

    def test_plaintext_password_is_not_current(self) -> None:
        """A stored plaintext password (legacy entry) is not current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'password': 'Init1234!'}
        assert ru._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is False

    def test_absent_cached_user_is_not_current(self) -> None:
        """A missing cached entry is not current."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = None
        assert ru._cached_password_is_current(cached_mgr, self._security_mgr(), 'x', 'p') is False


# =============================================== _sync_frontend_cached_user ========================================= #

class TestSyncFrontendCachedUser:
    """``_sync_frontend_cached_user`` maintains the cache for a frontend login."""

    def test_new_user_inserted(self) -> None:
        """An uncached user is inserted as-is."""
        cached_mgr = MagicMock()
        user_data = {'subscriptions': []}
        ru._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=False)
        cached_mgr.insert_cached_user.assert_called_once_with(user_data)

    def test_missing_cached_user_returns_early(self) -> None:
        """A user flagged cached but absent from the store is not updated."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = None
        ru._sync_frontend_cached_user(cached_mgr, 'x', {'subscriptions': []}, user_exists_in_cache=True)
        cached_mgr.update_cached_user.assert_not_called()

    def test_existing_user_restores_api_key(self) -> None:
        """A refreshed cached user keeps its previously stored api_key per database."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'subscriptions': [{'database': 'db', 'api_key': 'old-key'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        ru._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=True)
        assert user_data['subscriptions'][0]['api_key'] == 'old-key'
        cached_mgr.update_cached_user.assert_called_once_with('x', user_data)

    def test_existing_user_without_prior_api_key(self) -> None:
        """A refreshed user whose db had no cached api_key is updated with no key stamped."""
        cached_mgr = MagicMock()
        cached_mgr.get_cached_user.return_value = {'subscriptions': [{'database': 'db'}]}
        user_data = {'subscriptions': [{'database': 'db'}]}
        ru._sync_frontend_cached_user(cached_mgr, 'x', user_data, user_exists_in_cache=True)
        assert 'api_key' not in user_data['subscriptions'][0]
        cached_mgr.update_cached_user.assert_called_once_with('x', user_data)


# ============================================= small database/user helpers ========================================== #

class TestSmallHelpers:
    """The thin DB/user helpers around the managers."""

    def test_check_db_exists_delegates(self) -> None:
        """check_db_exists forwards to the database manager."""
        app = _app()
        app.database_manager.check_database_exists.return_value = True
        with app.test_request_context():
            assert ru.check_db_exists('db') is True
        app.database_manager.check_database_exists.assert_called_once_with('db')

    def test_init_db_routine_validates_and_sets_version(self) -> None:
        """init_db_routine validates collections and sets the newest update version."""
        validator = MagicMock()
        updater = MagicMock()
        updater.get_highest_update_version.return_value = 99
        with patch(f'{MODULE_PATH}.CollectionValidator', return_value=validator), \
             patch(f'{MODULE_PATH}.DatabaseUpdater', return_value=updater):
            with _app().test_request_context():
                ru.init_db_routine('db')
        validator.validate_collections.assert_called_once()
        updater.set_update_version.assert_called_once_with(99)

    def test_retrieve_user_returns_user(self) -> None:
        """retrieve_user returns the user found by email."""
        users_manager = MagicMock()
        user = SimpleNamespace(public_id=1)
        users_manager.get_user_by.return_value = user
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with _app().test_request_context():
                assert ru.retrieve_user({'email': 'x'}, 'db') is user

    def test_retrieve_user_get_error_returns_none(self) -> None:
        """retrieve_user returns None when the lookup errors."""
        users_manager = MagicMock()
        users_manager.get_user_by.side_effect = UsersManagerGetError('nope')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with _app().test_request_context():
                assert ru.retrieve_user({'email': 'x'}, 'db') is None

    def test_delete_database_drops_it(self) -> None:
        """delete_database drops the database through the users manager."""
        users_manager = MagicMock()
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with _app().test_request_context():
                ru.delete_database('db')
        users_manager.dbm.drop_database.assert_called_once_with('db')

    def test_delete_database_error_raises_not_found(self) -> None:
        """A failure while dropping raises DatabaseNotFoundError."""
        users_manager = MagicMock()
        users_manager.dbm.drop_database.side_effect = RuntimeError('boom')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with _app().test_request_context():
                with pytest.raises(DatabaseNotFoundError):
                    ru.delete_database('db')


# =================================================== set_admin_user ================================================= #

class TestSetAdminUser:
    """``set_admin_user`` creates or updates the admin user for a subscription's database."""

    SUBSCRIPTION: dict[str, Any] = {'database': 'db', 'api_level': 1, 'config_item_limit': 10}
    USER_DATA: dict[str, Any] = {'email': 'a@test.com', 'user_name': 'admin', 'password': 'pw'}

    def test_creates_when_absent(self) -> None:
        """A missing admin user is created."""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)
        users_manager.insert_user.assert_called_once()

    def test_updates_when_present(self) -> None:
        """An existing admin user is updated with the subscription's fields."""
        users_manager = MagicMock()
        existing = MagicMock()
        existing.get_public_id.return_value = 1
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)
        users_manager.update_user.assert_called_once()
        assert existing.database == 'db'

    def test_get_error_treated_as_absent_and_creates(self) -> None:
        """A UsersManagerGetError while reading the existing user is swallowed; the user is created."""
        users_manager = MagicMock()
        users_manager.get_user_by.side_effect = UsersManagerGetError('nope')
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)
        users_manager.insert_user.assert_called_once()

    def test_insert_get_error_reraised(self) -> None:
        """A UsersManagerGetError raised while writing propagates as UsersManagerGetError."""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        users_manager.insert_user.side_effect = UsersManagerGetError('boom')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                with pytest.raises(UsersManagerGetError):
                    ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

    def test_insert_failure_raises_insert_error(self) -> None:
        """A failure while inserting raises UsersManagerInsertError."""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.side_effect = RuntimeError('boom')
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                with pytest.raises(UsersManagerInsertError):
                    ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)


# =============================================== validate_subscription_user ========================================= #

class TestValidateSubscriptionUser:
    """``validate_subscription_user`` posts credentials to the DataGerry service portal."""

    def test_missing_api_key_raises(self) -> None:
        """A required-but-absent API key raises MissingApiKeyError."""
        with _app().test_request_context():
            with pytest.raises(MissingApiKeyError):
                ru.validate_subscription_user('x', 'p', None, api_key_required=True)

    def test_missing_access_token_raises(self) -> None:
        """A missing X-ACCESS-TOKEN env var raises NoAccessTokenError."""
        with patch(f'{MODULE_PATH}.os.getenv', return_value=None):
            with _app().test_request_context():
                with pytest.raises(NoAccessTokenError):
                    ru.validate_subscription_user('x', 'p')

    def test_success_returns_json(self) -> None:
        """A 200 response returns the parsed JSON body."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'email': 'x'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with _app().test_request_context():
                assert ru.validate_subscription_user('x', 'p') == {'email': 'x'}

    def test_api_key_uses_subscription_endpoint(self) -> None:
        """When an API key is supplied the subscription endpoint is targeted."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'email': 'x'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response) as post:
            with _app().test_request_context():
                ru.validate_subscription_user('x', 'p', 'the-key')
        assert post.call_args.args[0] == 'http://sp/datagerry/auth/subscription'

    def test_non_200_raises_invalid_cloud_user(self) -> None:
        """A non-200 response raises InvalidCloudUserError with the portal message."""
        response = MagicMock()
        response.status_code = 401
        response.json.return_value = {'message': 'nope'}
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with _app().test_request_context():
                with pytest.raises(InvalidCloudUserError):
                    ru.validate_subscription_user('x', 'p')

    def test_non_200_non_json_falls_back_to_text(self) -> None:
        """A non-JSON error body falls back to the raw text."""
        response = MagicMock()
        response.status_code = 500
        response.json.side_effect = ValueError('not json')
        response.text = 'server error'
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', return_value=response):
            with _app().test_request_context():
                with pytest.raises(InvalidCloudUserError):
                    ru.validate_subscription_user('x', 'p')

    def test_timeout_raises_request_timeout(self) -> None:
        """A request timeout raises RequestTimeoutError."""
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=ru.requests.exceptions.Timeout('slow')):
            with _app().test_request_context():
                with pytest.raises(RequestTimeoutError):
                    ru.validate_subscription_user('x', 'p')

    def test_request_exception_raises_request_error(self) -> None:
        """A generic request exception raises RequestError."""
        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=ru.requests.exceptions.RequestException('down')):
            with _app().test_request_context():
                with pytest.raises(RequestError):
                    ru.validate_subscription_user('x', 'p')
