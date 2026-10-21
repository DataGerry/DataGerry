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

These pin: the rights check (``user_has_right``, on the user it is handed),
the error-mapping decorators (``handle_oc_errors`` 500s; the transient database errors are the app's), the
request-user injection / API-access decorators, the Authorization-header parsing and Basic/Bearer
authentication, the service-portal check with its cache-sync helpers, and the small DB/user helpers.
"""
# pylint: disable=protected-access  # these tests intentionally exercise module-private helpers
import ast
import base64
import inspect
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch, mock_open

import pytest
from werkzeug.exceptions import Forbidden, HTTPException

from flask import abort

import cmdb.interface.route_utils as ru
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.manager.manager_provider_model.manager_provider import MANAGER_CLASSES
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.errors.database import (
    DatabaseConnectionError,
    SetDatabaseError,
    DocumentLockTimeoutError,
)
from cmdb.errors.security import (
    TokenValidationError,
    TokenKeyMaterialError,
    InvalidCloudUserError,
    NoAccessTokenError,
    MissingApiKeyError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.open_celium import AuthError
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.route_utils'
LICENSE_GUARD_PATH: str = 'cmdb.interface.rest_api.routes.cmdb_license.license_guard'

# Module-level aliases for the double-underscore module functions (avoids name-mangling inside classes)
_get_x_api_key: Callable[..., Any] = getattr(ru, '__get_x_api_key')
_get_request_api_user: Callable[..., Any] = getattr(ru, '__get_request_api_user')
_get_request_auth_method: Callable[..., Any] = getattr(ru, '__get_request_auth_method')
_check_api_level: Callable[..., Any] = getattr(ru, '__check_api_level')

# Base64 of "user@test.com:secret"
BASIC_CREDENTIALS: str = 'dXNlckB0ZXN0LmNvbTpzZWNyZXQ='
TYPED_EMAIL: str = ' User@Test.COM '
NORMALISED_EMAIL: str = 'user@test.com'
BASIC_HEADER: str = f'Basic {BASIC_CREDENTIALS}'
BEARER_HEADER: str = 'Bearer sometoken'
NO_TENANT_TOKEN_MSG: str = 'The token names no tenant database!'
UNAVAILABLE_TENANT: str = 'tenant_failed_update'
API_KEY_BASIC_HEADERS: dict[str, str] = {'Authorization': BASIC_HEADER, 'x-api-key': 'k'}

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

class TestHandleRouteErrors:
    """
    The shared error tail: an HTTPException keeps its status, anything else becomes a 500

    ~300 handlers wrote these two arms out. What the decorator must preserve is the per-route MESSAGE
    (the text tests assert on) and the log label (the handler's own name), and what it must not do is
    swallow an `abort` the handler raised on purpose.
    """

    def test_an_abort_keeps_its_own_status(self) -> None:
        """A 404 raised inside the route is the route's answer, not an internal error."""
        @ru.handle_route_errors('while doing the thing')
        def route():
            abort(404, 'not there')

        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route()

        assert exc_info.value.code == HTTPStatus.NOT_FOUND
        assert exc_info.value.description == 'not there'

    def test_any_other_error_becomes_a_500(self) -> None:
        """The message is the route's own, wrapped in the wording every route used."""
        @ru.handle_route_errors('while doing the thing')
        def route():
            raise RuntimeError('boom')

        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route()

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == 'An internal server error occured while doing the thing!'

    def test_the_message_reads_the_routes_keyword_arguments(self) -> None:
        """`{public_id}` is what keeps the per-route text as specific as it was inline."""
        @ru.handle_route_errors('while retrieving the Subnet with ID: {public_id}')
        def route(public_id: int):
            del public_id
            raise RuntimeError('boom')

        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route(public_id=42)

        assert 'Subnet with ID: 42' in exc_info.value.description

    def test_a_positional_argument_fills_the_template_too(self) -> None:
        """The shared route bodies pass their arguments positionally, and must read the same."""
        @ru.handle_route_errors('while determining {subject} for Type with ID: {public_id}')
        def route(public_id: int, subject: str):
            del public_id, subject
            raise RuntimeError('boom')

        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route(7, 'location-field usage')

        assert exc_info.value.description == (
            'An internal server error occured while determining location-field usage for Type with ID: 7!'
        )

    def test_an_unfillable_placeholder_leaves_the_template_alone(self) -> None:
        """A broken error message must not replace the error it was meant to describe."""
        @ru.handle_route_errors('while doing {nothing_the_route_takes}')
        def route():
            raise RuntimeError('boom')

        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route()

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_transient_database_error_is_left_for_the_database_decorator(self) -> None:
        """
        423 / 503 must survive the generic tail

        The app's error handlers map a lock timeout and a network failure to statuses that tell the caller
        to retry, and they only see what escapes this wrapper - which is why the routes must not
        swallow them.
        """
        @ru.handle_route_errors('while doing the thing')
        def route():
            raise DocumentLockTimeoutError('lock timeout')

        with _app().test_request_context(), pytest.raises(DocumentLockTimeoutError):
            route()

    def test_the_handler_keeps_its_name_but_not_its_wrapped_link(self) -> None:
        """
        The log label reads `__name__`; the missing `__wrapped__` is what keeps the tail testable

        The route tests unwrap a handler to call it without auth. Following `__wrapped__` here would
        unwrap the error tail with it, and every "an unexpected error is a 500" test would see the raw
        exception instead of the mapped status.
        """
        @ru.handle_route_errors('while doing the thing')
        def route():
            return 'ok'

        assert route.__name__ == 'route'
        assert not hasattr(route, '__wrapped__')


class _ManagerFailure(Exception):
    """A manager operation that went wrong."""


class _SpecificManagerFailure(_ManagerFailure):
    """A narrower failure, listed with a message of its own."""


class _ManagerRefusal(Exception):
    """A business rule the manager enforced."""


FAILURE_MESSAGE: str = 'Failed to read the Thing with ID: {public_id}!'
SPECIFIC_FAILURE_MESSAGE: str = 'Failed to read the specific Thing with ID: {public_id}!'
REFUSAL_MESSAGE: str = 'The Thing with ID: {public_id} is still used!'
ROUTE_ID: int = 42


class TestFormatRouteMessage:
    """The template filling both route error decorators share."""

    @staticmethod
    def _route(public_id: int, subject: str = 'the default subject') -> None:
        """A route signature with a defaulted parameter."""
        del public_id, subject

    def test_keyword_and_positional_arguments_fill_alike(self) -> None:
        """The shared route bodies call positionally; Flask calls by keyword."""
        signature = inspect.signature(self._route)

        assert ru.format_route_message(signature, 'ID {public_id}', (ROUTE_ID,), {}) == f'ID {ROUTE_ID}'
        assert ru.format_route_message(signature, 'ID {public_id}', (), {'public_id': ROUTE_ID}) == f'ID {ROUTE_ID}'

    def test_a_defaulted_parameter_fills_too(self) -> None:
        """apply_defaults: a placeholder over a parameter the caller left out still reads its default."""
        signature = inspect.signature(self._route)

        assert ru.format_route_message(signature, '{subject}', (ROUTE_ID,), {}) == 'the default subject'

    @pytest.mark.parametrize('args, kwargs, template', [
        ((ROUTE_ID,), {}, 'while doing {nothing_the_route_takes}'),
        ((), {}, 'while reading {public_id}'),
        ((ROUTE_ID,), {}, 'while reading {0}'),
        ((ROUTE_ID,), {}, 'while reading {public_id'),
    ], ids=['unknown-placeholder', 'unbindable-call', 'positional-placeholder', 'malformed-template'])
    def test_an_unfillable_template_is_answered_as_it_is(self, args: tuple, kwargs: dict, template: str) -> None:
        """A broken error message must not replace the error it reports."""
        assert ru.format_route_message(inspect.signature(self._route), template, args, kwargs) == template


class TestClosestListedErrorClass:
    """Which listed class a raised error answers to."""

    def test_the_errors_own_class(self) -> None:
        """An exact match."""
        assert ru.closest_listed_error_class({_ManagerFailure}, _ManagerFailure()) is _ManagerFailure

    def test_a_listed_base_class_catches_a_subclass(self) -> None:
        """A subclass nobody listed answers to its listed base."""
        assert ru.closest_listed_error_class({_ManagerFailure}, _SpecificManagerFailure()) is _ManagerFailure

    def test_the_most_specific_listed_class_wins(self) -> None:
        """Listing base and subclass answers the subclass with its own entry, whatever the order."""
        listed = [_ManagerFailure, _SpecificManagerFailure]

        assert ru.closest_listed_error_class(listed, _SpecificManagerFailure()) is _SpecificManagerFailure

    def test_an_unlisted_error(self) -> None:
        """None: the error is not one of the route's rules."""
        assert ru.closest_listed_error_class({_ManagerFailure}, RuntimeError()) is None


class TestHandleManagerErrors:
    """
    A route's manager-error table: each listed error is a 400 with the route's own message

    Failures log as errors with the traceback, refusals as warnings without it. Everything the table does
    not name - an abort, an unexpected error - passes through untouched for the generic tail above it.
    """

    @staticmethod
    def _decorate(raised: Exception | None = None):
        """A route taking a public_id, raising `raised`, under a table with one failure and one refusal."""
        @ru.handle_manager_errors(
            {_ManagerFailure: FAILURE_MESSAGE, _SpecificManagerFailure: SPECIFIC_FAILURE_MESSAGE},
            refusals={_ManagerRefusal: REFUSAL_MESSAGE},
        )
        def route(public_id: int):
            del public_id
            if raised is not None:
                raise raised
            return 'ok'

        return route

    def test_a_route_that_succeeds_answers_as_it_did(self) -> None:
        """The table only matters when something is raised."""
        assert self._decorate()(public_id=ROUTE_ID) == 'ok'

    @pytest.mark.parametrize('raised, template', [
        (_ManagerFailure('boom'), FAILURE_MESSAGE),
        (_SpecificManagerFailure('boom'), SPECIFIC_FAILURE_MESSAGE),
        (_ManagerRefusal('used'), REFUSAL_MESSAGE),
    ], ids=['failure', 'specific-failure', 'refusal'])
    def test_a_listed_error_is_a_400_with_its_own_message(self, raised: Exception, template: str) -> None:
        """The message is the listed one, filled from the route's argument."""
        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._decorate(raised)(ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert exc_info.value.description == template.format(public_id=ROUTE_ID)

    def test_a_failure_is_logged_as_an_error_with_the_traceback(self, caplog: pytest.LogCaptureFixture) -> None:
        """A failed operation is something to investigate."""
        with _app().test_request_context(), pytest.raises(HTTPException):
            self._decorate(_ManagerFailure('boom'))(ROUTE_ID)

        record = next(r for r in caplog.records if r.name == MODULE_PATH)
        assert record.levelname == 'ERROR'
        assert record.exc_info is not None

    def test_a_refusal_is_logged_as_a_warning_without_one(self, caplog: pytest.LogCaptureFixture) -> None:
        """A declined request is the rule working, not a fault."""
        with _app().test_request_context(), pytest.raises(HTTPException):
            self._decorate(_ManagerRefusal('used'))(ROUTE_ID)

        record = next(r for r in caplog.records if r.name == MODULE_PATH)
        assert record.levelname == 'WARNING'
        assert not record.exc_info

    def test_an_unlisted_error_passes_through_raw(self) -> None:
        """Not this table's business: the generic tail decides what it is."""
        with pytest.raises(RuntimeError):
            self._decorate(RuntimeError('boom'))(ROUTE_ID)

    def test_an_abort_keeps_its_own_status(self) -> None:
        """A route's own abort is not a manager error."""
        with _app().test_request_context(), pytest.raises(Forbidden) as exc_info:
            self._decorate(Forbidden())(ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_an_empty_table_is_refused(self) -> None:
        """A decorator that maps nothing is a mistake at the route, not a no-op."""
        with pytest.raises(ValueError):
            ru.handle_manager_errors({})

    def test_a_class_listed_as_both_failure_and_refusal_is_refused(self) -> None:
        """It could be logged only one way."""
        with pytest.raises(ValueError):
            ru.handle_manager_errors({_ManagerFailure: FAILURE_MESSAGE}, refusals={_ManagerFailure: REFUSAL_MESSAGE})

    def test_the_wrapper_keeps_the_routes_signature_but_not_its_wrapped_link(self) -> None:
        """No `__wrapped__` for the route tests to unwrap past; the signature for the decorator above."""
        route = self._decorate()

        assert route.__name__ == 'route'
        assert not hasattr(route, '__wrapped__')
        assert list(inspect.signature(route).parameters) == ['public_id']


class TestTheTwoErrorDecoratorsStacked:
    """The order every route uses: handle_route_errors above handle_manager_errors."""

    @staticmethod
    def _route(raised: Exception):
        """A route under both decorators, both messages templated over its public_id."""
        @ru.handle_route_errors('while reading the Thing with ID: {public_id}')
        @ru.handle_manager_errors({_ManagerFailure: FAILURE_MESSAGE})
        def route(public_id: int):
            del public_id
            raise raised

        return route

    def test_a_listed_error_is_the_manager_tables_400(self) -> None:
        """The 400 is an HTTPException, which the generic tail hands through."""
        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._route(_ManagerFailure('boom'))(public_id=ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_anything_else_is_the_generic_500_with_its_placeholder_filled(self) -> None:
        """
        The generic tail fills `{public_id}` through the manager wrapper

        Without the signature the inner wrapper pins, the tail would see `(*args, **kwargs)`, fail to
        bind, and answer the unfilled template.
        """
        with _app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._route(RuntimeError('boom'))(public_id=ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == (
            f'An internal server error occured while reading the Thing with ID: {ROUTE_ID}!'
        )


class TestGetCachedUserManager:
    """
    The one place the cloud user-cache manager is built

    Eighteen call sites wrote `CachedUserManager(current_app.database_manager)` by hand. What the
    helper records is WHY it is not `ManagerProvider.get_manager`: the cache never lives in a tenant
    database, and the login path has no authenticated user to resolve one with.
    """

    def test_it_builds_the_manager_from_the_app_database_handle(self) -> None:
        """The process' own handle - there is no per-request or per-tenant choice to make here."""
        app = _app()

        with app.test_request_context(), patch(f'{MODULE_PATH}.CachedUserManager') as manager_cls:
            built = ru.get_cached_user_manager()

        manager_cls.assert_called_once_with(app.database_manager)
        assert built is manager_cls.return_value

    def test_it_takes_no_request_user(self) -> None:
        """
        It cannot: the login path calls this before anyone is authenticated

        That is the reason the cache manager is built directly instead of through ManagerProvider,
        whose cloud-mode path requires a request_user.
        """
        assert not inspect.signature(ru.get_cached_user_manager).parameters

    def test_the_manager_type_registry_does_not_offer_it(self) -> None:
        """
        `ManagerType` deliberately carries no CACHED_USER entry any more

        It was registered and used by nobody: `CachedUserManager` ignores the database argument
        `ManagerProvider` would pass it, so resolving it there would look tenant-aware and not be.
        """
        assert not hasattr(ManagerType, 'CACHED_USER')
        assert ru.CachedUserManager not in MANAGER_CLASSES.values()


class TestUserHasRight:
    """``user_has_right`` checks the request user's group - the user is handed in, never re-read."""

    @staticmethod
    def _check(group: Any, user: Any = None) -> tuple[bool, MagicMock]:
        """Runs user_has_right with the provided GroupsManager answering `group`; answers it and the provider."""
        user = user or SimpleNamespace(group_id=3, database=None)
        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager') as get_manager:
            get_manager.return_value.get_group.return_value = group
            with _app().test_request_context():
                return ru.user_has_right('base.right', user), get_manager

    def test_a_group_holding_the_right_grants_it(self) -> None:
        """The direct right is enough; the extended check is not asked"""
        group = MagicMock()
        group.has_right.return_value = True

        granted, _ = self._check(group)

        assert granted is True
        group.has_extended_right.assert_not_called()

    def test_an_extended_right_grants_it(self) -> None:
        """A wildcard right of a parent segment counts"""
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = True

        assert self._check(group)[0] is True

    def test_neither_right_refuses(self) -> None:
        """No direct and no extended right"""
        group = MagicMock()
        group.has_right.return_value = False
        group.has_extended_right.return_value = False

        assert self._check(group)[0] is False

    def test_a_user_whose_group_is_gone_holds_no_right(self) -> None:
        """A deleted group resolves to None: authenticated, but refused every right"""
        assert self._check(None)[0] is False

    def test_the_groups_manager_comes_from_the_provider_for_this_user(self) -> None:
        """ManagerProvider picks the database: the user's tenant in cloud mode, the process's own otherwise"""
        user = SimpleNamespace(group_id=3, database='test')

        _, get_manager = self._check(MagicMock(), user)

        get_manager.assert_called_once_with(ManagerType.GROUPS, user)
        get_manager.return_value.get_group.assert_called_once_with(3)

    def test_a_failed_group_read_propagates(self) -> None:
        """An outage is not answered as a missing right - protect maps it to a 500"""
        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager') as get_manager:
            get_manager.return_value.get_group.side_effect = GroupsManagerGetError('db down')
            with _app().test_request_context():
                with pytest.raises(GroupsManagerGetError):
                    ru.user_has_right('base.right', SimpleNamespace(group_id=3, database=None))


# ================================================== handle_db_errors ================================================ #

def test_handle_db_errors_is_gone() -> None:
    """The app's error handlers answer the transient database errors for every route; the per-route decorator is gone"""
    assert not hasattr(ru, 'handle_db_errors')


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
        """In cloud mode an x-api-key request with Basic credentials is left to verify_api_access."""
        handler = MagicMock(return_value='done')
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header') as parse:
            with _app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                assert ru.insert_request_user(handler)() == 'done'
        handler.assert_called_once()
        parse.assert_not_called()

    def test_cloud_basic_without_an_api_key_is_refused_with_its_own_401(self) -> None:
        """Not the generic token failure: the caller is told the key is missing, and nothing is authenticated"""
        handler = MagicMock()
        with patch(f'{MODULE_PATH}.parse_authorization_header') as parse:
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(handler)()

        assert exc_info.value.code == 401
        assert exc_info.value.description == ru.CLOUD_BASIC_WITHOUT_API_KEY_MESSAGE
        parse.assert_not_called()
        handler.assert_not_called()

    def test_an_error_of_the_route_on_the_api_key_path_is_not_a_token_failure(self) -> None:
        """The route's own error reaches the caller - it is not turned into 'Token could not be validated!'"""
        handler = MagicMock(side_effect=RuntimeError('the route failed'))
        with patch(f'{MODULE_PATH}.UsersManager'):
            with _app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                with pytest.raises(RuntimeError):
                    ru.insert_request_user(handler)()

    def test_an_api_key_next_to_a_bearer_token_is_resolved_from_the_token(self) -> None:
        """The key alone decides nothing: the token's user is injected as for any other request"""
        users_manager = MagicMock()
        user = SimpleNamespace(public_id=42, active=True)
        users_manager.get_user.return_value = user
        captured: dict[str, Any] = {}

        def _handler(**kwargs: Any) -> str:
            captured.update(kwargs)
            return 'ran'

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            headers: dict[str, str] = {'Authorization': BEARER_HEADER, ru.API_KEY_HEADER: 'k'}
            with _app(cloud_mode=True).test_request_context(headers=headers):
                assert ru.insert_request_user(_handler)() == 'ran'
        assert captured['request_user'] is user

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

    def test_key_material_failure_aborts_500(self) -> None:
        """The decorator every route carries reports a key problem as the server's, not the caller's"""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.decode_request_token', side_effect=TokenKeyMaterialError('no key')):
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

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
        user = SimpleNamespace(public_id=42, active=True)
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

    @pytest.mark.parametrize('database', [None, ''], ids=['null', 'empty'])
    def test_a_cloud_token_naming_no_database_aborts_401(self, database: Any) -> None:
        """
        A cloud token without a tenant is refused before any user is read

        A null database would bind the UsersManager to the process-wide database, where the token's user
        id names another tenant's user or nobody
        """
        claims: dict[str, Any] = {'DATAGERRY': {'value': {'user': {'public_id': 42, 'database': database}}}}
        handler = MagicMock()

        with patch(f'{MODULE_PATH}.UsersManager') as users_manager_cls, \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = claims
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(handler)()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        assert exc_info.value.description == NO_TENANT_TOKEN_MSG
        users_manager_cls.return_value.get_user.assert_not_called()
        handler.assert_not_called()

    def test_a_cloud_token_naming_an_unavailable_tenant_aborts_503(self) -> None:
        """A tenant that failed its startup update is refused before its database is read"""
        claims: dict[str, Any] = {'DATAGERRY': {'value': {'user': {'public_id': 42, 'database': UNAVAILABLE_TENANT}}}}
        handler = MagicMock()
        app = _app(cloud_mode=True)
        app.unavailable_tenants = frozenset({UNAVAILABLE_TENANT})

        with patch(f'{MODULE_PATH}.UsersManager') as users_manager_cls, \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = claims
            with app.test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(handler)()

        assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert exc_info.value.description == TENANT_UNAVAILABLE_RESPONSE_MESSAGE
        users_manager_cls.assert_not_called()
        handler.assert_not_called()

    def test_a_cloud_token_of_another_tenant_is_served_beside_an_unavailable_one(self) -> None:
        """Only the failed tenant is fenced off - the token's own tenant is read as usual"""
        users_manager = MagicMock()
        users_manager.get_user.return_value = SimpleNamespace(public_id=42, active=True)
        app = _app(cloud_mode=True)
        app.unavailable_tenants = frozenset({UNAVAILABLE_TENANT})

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with app.test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.insert_request_user(lambda **_: 'ran')() == 'ran'

    def test_an_on_premise_token_needs_no_database(self) -> None:
        """On premise the token carries no database and the user is read from the one database"""
        users_manager = MagicMock()
        users_manager.get_user.return_value = SimpleNamespace(public_id=42, active=True)
        claims: dict[str, Any] = {'DATAGERRY': {'value': {'user': {'public_id': 42}}}}

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = claims
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.insert_request_user(lambda **_: 'ran')() == 'ran'

    def test_the_api_key_path_builds_no_users_manager(self) -> None:
        """verify_api_access resolves that user; nothing is built here only to be thrown away"""
        with patch(f'{MODULE_PATH}.UsersManager') as users_manager_cls:
            with _app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                ru.insert_request_user(lambda **_: 'ran')()

        users_manager_cls.assert_not_called()

    @pytest.mark.parametrize('cloud_mode, user_claim, database', [
        (False, {'public_id': 42}, None),
        (True, {'public_id': 42, 'database': 'tenant_db'}, 'tenant_db'),
    ], ids=['on-premise', 'cloud'])
    def test_one_users_manager_bound_to_the_users_database(self, cloud_mode: bool, user_claim: dict[str, Any],
                                                           database: str | None) -> None:
        """Built once, after the token: the one database on premise, the token's tenant in cloud mode"""
        claims: dict[str, Any] = {'DATAGERRY': {'value': {'user': user_claim}}}
        app = _app(cloud_mode=cloud_mode)

        with patch(f'{MODULE_PATH}.UsersManager') as users_manager_cls, \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            users_manager_cls.return_value.get_user.return_value = SimpleNamespace(public_id=42, active=True)
            tv_cls.return_value.decode_token.return_value = claims
            with app.test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.insert_request_user(lambda **_: 'ran')() == 'ran'

        users_manager_cls.assert_called_once_with(app.database_manager, database)

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

    def test_missing_user_keeps_its_message(self) -> None:
        """The 'Invalid user!' refusal reaches the caller rather than being replaced by a bare 401"""
        users_manager = MagicMock()
        users_manager.get_user.return_value = None

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.description == 'Invalid user!'

    def test_a_deactivated_user_is_refused_and_the_handler_never_runs(self) -> None:
        """A valid token for a user stored with active: false is a 401 - deactivation revokes tokens"""
        users_manager = MagicMock()
        users_manager.get_user.return_value = SimpleNamespace(public_id=42, active=False)
        handler = MagicMock()

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(handler)()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        assert exc_info.value.description == ru.USER_DEACTIVATED_MESSAGE
        handler.assert_not_called()

    @staticmethod
    def _run_resolving(user: Any, handler: Any, enforce: MagicMock) -> None:
        """Runs insert_request_user on-premise for a token resolving to `user`, the licence enforcement mocked"""
        users_manager = MagicMock()
        users_manager.get_user.return_value = user

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls, \
             patch(f'{LICENSE_GUARD_PATH}.enforce_request_licenses', enforce):
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                ru.insert_request_user(handler)()

    def test_the_licences_are_enforced_for_the_resolved_user_before_the_handler(self) -> None:
        """Enforcement sees the authenticated user, and runs before the route body"""
        user = SimpleNamespace(public_id=42, active=True)
        order: list[str] = []
        enforce = MagicMock(side_effect=lambda *_args: order.append('licence'))

        self._run_resolving(user, lambda **_: order.append('handler'), enforce)

        enforce.assert_called_once_with(user, False)
        assert order == ['licence', 'handler']

    def test_a_licence_refusal_stops_the_handler(self) -> None:
        """The 403 from the enforcement is the answer - the route body never runs"""
        handler = MagicMock()
        enforce = MagicMock(side_effect=Forbidden('The ISMS feature requires a valid license!'))

        with pytest.raises(HTTPException) as exc_info:
            self._run_resolving(SimpleNamespace(public_id=42, active=True), handler, enforce)

        assert exc_info.value.code == HTTPStatus.FORBIDDEN
        handler.assert_not_called()

    def test_a_deactivated_user_is_refused_before_the_licences_are_asked(self) -> None:
        """The account's state is decided first, so a deactivated caller learns nothing about the licence"""
        enforce = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            self._run_resolving(SimpleNamespace(public_id=42, active=False), MagicMock(), enforce)

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        enforce.assert_not_called()

    @pytest.mark.parametrize('headers', [{}, {'Authorization': BEARER_HEADER}], ids=['no header', 'bad token'])
    def test_an_unauthenticated_caller_never_reaches_the_licences(self, headers: dict[str, str]) -> None:
        """A 401 without a token or with one that does not validate - the licence is never consulted"""
        enforce = MagicMock()

        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls, \
             patch(f'{LICENSE_GUARD_PATH}.enforce_request_licenses', enforce):
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with _app().test_request_context(headers=headers):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(MagicMock())()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        enforce.assert_not_called()

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
        user_model = SimpleNamespace(public_id=1, active=True)
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

    def test_a_deactivated_api_key_user_is_refused_and_the_handler_never_runs(self) -> None:
        """The portal accepted the credentials, the tenant stored the account deactivated: 401"""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        handler = MagicMock()

        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=False)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with _app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(handler)()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        assert exc_info.value.description == ru.USER_DEACTIVATED_MESSAGE
        handler.assert_not_called()

    def test_an_api_key_user_of_an_unavailable_tenant_aborts_503_before_any_write(self) -> None:
        """The tenant is checked before set_admin_user writes to it and before the user is read"""
        user_instance = {'subscriptions': [{'database': UNAVAILABLE_TENANT, 'api_level': 1}], 'api_level': 1}
        handler = MagicMock()
        app = _app(cloud_mode=True)
        app.unavailable_tenants = frozenset({UNAVAILABLE_TENANT})

        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user') as set_admin, \
             patch(f'{MODULE_PATH}.retrieve_user') as retrieve, \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with app.test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(handler)()

        assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert exc_info.value.description == TENANT_UNAVAILABLE_RESPONSE_MESSAGE
        set_admin.assert_not_called()
        retrieve.assert_not_called()
        handler.assert_not_called()

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
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=True)), \
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

    def test_the_parse_is_cached_for_the_request(self) -> None:
        """
        The same header is parsed once per request

        Parsing a bearer header VALIDATES the token (see _validate_bearer), and a route carries up to
        three decorators that each call this - the second and third read the cached answer.
        """
        with patch(f'{MODULE_PATH}._validate_bearer', return_value='sometoken') as mocked:
            with _app().test_request_context():
                first = ru.parse_authorization_header(BEARER_HEADER)
                second = ru.parse_authorization_header(BEARER_HEADER)

        assert (first, second) == ('sometoken', 'sometoken')
        mocked.assert_called_once_with('sometoken')

    def test_a_different_header_is_parsed_on_its_own(self) -> None:
        """The cache is keyed by the header, so two credentials in one request cannot be confused"""
        with patch(f'{MODULE_PATH}._validate_bearer', side_effect=['first', 'second']) as mocked:
            with _app().test_request_context():
                assert ru.parse_authorization_header('Bearer one') == 'first'
                assert ru.parse_authorization_header('Bearer two') == 'second'

        assert mocked.call_count == 2

    def test_a_refused_header_is_cached_too(self) -> None:
        """A None answer is an answer: re-validating a bad token per decorator buys nothing"""
        with patch(f'{MODULE_PATH}._validate_bearer', return_value=None) as mocked:
            with _app().test_request_context():
                assert ru.parse_authorization_header(BEARER_HEADER) is None
                assert ru.parse_authorization_header(BEARER_HEADER) is None

        mocked.assert_called_once()

    def test_without_a_request_nothing_is_cached(self) -> None:
        """
        The helpers stay callable outside a request

        There is nothing to scope a cache to then - a CLI path or a direct unit test - so each call
        parses again rather than failing. The context check is patched rather than assumed: another
        module in the suite can leave a request context pushed.
        """
        with patch(f'{MODULE_PATH}.has_request_context', return_value=False), \
             patch(f'{MODULE_PATH}._validate_bearer', return_value='sometoken') as mocked:
            assert ru.parse_authorization_header(BEARER_HEADER) == 'sometoken'
            assert ru.parse_authorization_header(BEARER_HEADER) == 'sometoken'

        assert mocked.call_count == 2


# ================================================ decode_request_token ============================================== #

class TestDecodeRequestToken:
    """The decode every decorator of a route shares."""

    def test_the_claims_are_answered(self) -> None:
        """The claims are what the caller reads the acting user out of"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context():
                assert ru.decode_request_token('sometoken') == DECODED_TOKEN

    def test_the_decode_is_cached_for_the_request(self) -> None:
        """
        One RSA verification and one key read per request instead of one per decorator

        A single GET was measured at 4 decodes and 12 reads of the key document before this.
        """
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context():
                ru.decode_request_token('sometoken')
                ru.decode_request_token('sometoken')

        tv_cls.return_value.decode_token.assert_called_once()

    def test_a_bytes_token_hits_the_same_cache_entry(self) -> None:
        """The generator answers bytes and the header carries a str - the same token either way"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context():
                ru.decode_request_token('sometoken')
                ru.decode_request_token(b'sometoken')

        tv_cls.return_value.decode_token.assert_called_once()

    def test_a_failure_is_not_cached_as_a_result(self) -> None:
        """A refused token raises for every caller, rather than the first one poisoning the cache"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with _app().test_request_context():
                for _ in range(2):
                    with pytest.raises(TokenValidationError):
                        ru.decode_request_token('sometoken')

        assert tv_cls.return_value.decode_token.call_count == 2

    def test_without_a_request_it_still_decodes(self) -> None:
        """No request to scope a cache to is not an error - it just decodes every time"""
        with patch(f'{MODULE_PATH}.has_request_context', return_value=False), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN

            assert ru.decode_request_token('sometoken') == DECODED_TOKEN
            assert ru.decode_request_token('sometoken') == DECODED_TOKEN
            assert tv_cls.return_value.decode_token.call_count == 2


# ================================================= token_user_claim ================================================= #

class TestTokenUserClaim:
    """Reading the acting user out of the wrapped DataGerry claim."""

    def test_the_user_payload_is_answered(self) -> None:
        """Four call sites would otherwise spell claims['DATAGERRY']['value']['user'] by hand"""
        assert ru.token_user_claim(DECODED_TOKEN)['public_id'] == DECODED_TOKEN['DATAGERRY']['value']['user'][
            'public_id'
        ]

    @pytest.mark.parametrize('claims', [{}, {'DATAGERRY': {}}, {'DATAGERRY': {'value': {}}}])
    def test_a_token_without_the_payload_raises(self, claims: dict) -> None:
        """The callers turn this into a 401 - a token without a user identifies nobody"""
        with pytest.raises(KeyError):
            ru.token_user_claim(claims)


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

    @pytest.mark.parametrize('local_mode', [False, True], ids=['hosted', 'local'])
    def test_cloud_mode_never_logs_in(self, local_mode: bool) -> None:
        """
        Cloud Basic without an x-api-key has no tenant to log into: refused before the portal or a provider runs

        The portal's key-less answer names every subscription and no database, and the password digest a portal
        user stores is checked by the portal, not here - so nothing on this path could ever succeed
        """
        with self._patches(login_result=MagicMock()), \
             patch(f'{MODULE_PATH}.check_user_in_service_portal') as portal:
            with _app(cloud_mode=True, local_mode=local_mode).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

            portal.assert_not_called()
            ru.AuthModule.return_value.login.assert_not_called()

    def test_on_premise_the_login_is_stripped(self) -> None:
        """The case is AuthModule's to try; the whitespace is removed here"""
        credentials: str = base64.b64encode(b' Admin :secret').decode('utf-8')
        with self._patches(login_result=MagicMock()):
            with _app(cloud_mode=False).test_request_context():
                ru._authenticate_basic(credentials)

            assert ru.AuthModule.return_value.login.call_args.args == ('Admin', 'secret')

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

    def test_expired_token_returns_none(self) -> None:
        """
        A token whose claims fail validation yields None

        This is the ONLY place expiry is enforced for a request - the per-route decorators decode
        but do not re-validate - so the step is asserted here by name.
        """
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.validate_claims.side_effect = TokenValidationError('expired')
            with _app().test_request_context():
                assert ru._validate_bearer('sometoken') is None

    def test_foreign_issuer_returns_none(self) -> None:
        """A token this product did not issue is refused, even with a valid signature"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.validate_issuer.side_effect = TokenValidationError('foreign')
            with _app().test_request_context():
                assert ru._validate_bearer('sometoken') is None

    def test_without_a_request_the_claims_are_not_cached(self) -> None:
        """
        The validation still runs, there is simply nowhere to keep its result

        `_validate_bearer` hands its already-decoded claims to the request cache so the decorators
        do not decode again; called outside a request there is no cache to hand them to.
        """
        with patch(f'{MODULE_PATH}.has_request_context', return_value=False), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with _app().test_request_context():
                assert ru._validate_bearer('sometoken') == 'sometoken'

        tv_cls.return_value.validate_claims.assert_called_once()

    def test_a_key_material_failure_is_not_answered_as_a_bad_token(self) -> None:
        """
        A server-side key problem propagates instead of degrading to None

        Answering None here would make the caller abort 401, i.e. log every user out over a
        misconfigured installation.
        """
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenKeyMaterialError('no key')
            with _app().test_request_context():
                with pytest.raises(TokenKeyMaterialError):
                    ru._validate_bearer('sometoken')


# ============================================ check_user_in_service_portal ========================================== #

class TestCheckUserInServicePortal:
    """``check_user_in_service_portal`` validates users locally or via the portal + cache."""

    def test_local_mode_delegates_to_local_loader(self) -> None:
        """In local mode the local test-user loader is used, and its plaintext password comes back as its HMAC"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value={'email': 'x', 'password': 'p'}) as loader, \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            security_manager.return_value.generate_hmac.side_effect = lambda plain: f'hmac({plain})'
            with _app(local_mode=True).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p') == {'email': 'x', 'password': 'hmac(p)'}
        loader.assert_called_once_with('x', 'p')

    def test_local_mode_refusal_stays_none(self) -> None:
        """Nothing to hash when the fixture refuses"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value=None), \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            with _app(local_mode=True).test_request_context():
                assert ru.check_user_in_service_portal('x', 'p') is None
        security_manager.return_value.generate_hmac.assert_not_called()

    def test_the_email_is_normalised_before_the_local_loader(self) -> None:
        """Stripped and lower-cased, whatever the caller submitted"""
        with patch(f'{MODULE_PATH}._load_local_test_user', return_value=None) as loader:
            with _app(local_mode=True).test_request_context():
                ru.check_user_in_service_portal(TYPED_EMAIL, 'p')
        loader.assert_called_once_with(NORMALISED_EMAIL, 'p')

    def test_the_cache_and_the_portal_see_the_normalised_email(self) -> None:
        """One address is one cache entry - the unique cache index compares case-sensitively"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', return_value={}) as portal:
            with _app(local_mode=False).test_request_context():
                ru.check_user_in_service_portal(TYPED_EMAIL, 'p', 'key', api_key_required=True)
        cached_mgr.cached_user_exists.assert_called_once_with(NORMALISED_EMAIL)
        portal.assert_called_once_with(NORMALISED_EMAIL, 'p', 'key', True)

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
        """A recognised portal error propagates unchanged - the same object, not made its own cause"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.return_value = False
        refusal = InvalidCloudUserError('no')
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'), \
             patch(f'{MODULE_PATH}.validate_subscription_user', side_effect=refusal):
            with _app(local_mode=False).test_request_context():
                with pytest.raises(InvalidCloudUserError) as exc_info:
                    ru.check_user_in_service_portal('x', 'p')

        assert exc_info.value is refusal
        assert exc_info.value.__cause__ is not refusal

    @pytest.mark.parametrize('failure', [
        RuntimeError('boom'),
        DatabaseConnectionError('cache down'),
        ValueError("No symmetric AES key provided via the 'DG_SYMMETRIC_KEY' environment variable"),
    ], ids=['bug', 'cache-read', 'missing-key'])
    def test_any_other_error_propagates_as_itself(self, failure: Exception) -> None:
        """Not wrapped in a bare Exception, so the caller's own arms (cloud_login's DatabaseConnectionError) match it"""
        cached_mgr = MagicMock()
        cached_mgr.cached_user_exists.side_effect = failure
        with patch(f'{MODULE_PATH}.CachedUserManager', return_value=cached_mgr), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app(local_mode=False).test_request_context():
                with pytest.raises(type(failure)) as exc_info:
                    ru.check_user_in_service_portal('x', 'p')

        assert exc_info.value is failure


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

    def test_a_created_user_stores_the_digest_it_is_handed(self) -> None:
        """The portal check already HMACed the password; hashing it again stored a digest nothing could match"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager') as security_manager:
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

        assert users_manager.insert_user.call_args.args[0].password == self.USER_DATA['password']
        security_manager.return_value.generate_hmac.assert_not_called()

    def test_an_update_leaves_the_stored_password_alone(self) -> None:
        """Only the subscription's three fields are refreshed"""
        users_manager = MagicMock()
        existing = MagicMock(password='stored-digest')
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.SUBSCRIPTION)

        assert existing.password == 'stored-digest'

    # The portal's numbers as strings: both branches have to convert them to int
    STRING_SUBSCRIPTION: dict[str, Any] = {'database': 'db', 'api_level': '1', 'config_item_limit': '10'}

    def test_the_update_path_stores_integers_for_string_numbers(self) -> None:
        """An updated user carries int api_level / config_items_limit, so the limit check can compare"""
        users_manager = MagicMock()
        existing = MagicMock()
        users_manager.get_user_by.return_value = existing
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.STRING_SUBSCRIPTION)

        assert existing.config_items_limit == self.SUBSCRIPTION['config_item_limit']
        assert existing.api_level == self.SUBSCRIPTION['api_level']
        assert isinstance(existing.config_items_limit, int)

    def test_the_create_path_stores_integers_for_string_numbers(self) -> None:
        """The created user gets the same types the update path writes"""
        users_manager = MagicMock()
        users_manager.get_user_by.return_value = None
        users_manager.get_next_public_id.return_value = 1
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                ru.set_admin_user(self.USER_DATA, self.STRING_SUBSCRIPTION)

        created = users_manager.insert_user.call_args.args[0]
        assert created.config_items_limit == self.SUBSCRIPTION['config_item_limit']
        assert created.api_level == self.SUBSCRIPTION['api_level']

    def test_a_non_numeric_limit_is_refused_before_any_write(self) -> None:
        """The conversion runs before either branch, so a bad value writes nothing and names the failure"""
        users_manager = MagicMock()
        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.SecurityManager'):
            with _app().test_request_context():
                with pytest.raises(UsersManagerInsertError):
                    ru.set_admin_user(self.USER_DATA, {**self.SUBSCRIPTION, 'config_item_limit': 'lots'})

        users_manager.insert_user.assert_not_called()
        users_manager.update_user.assert_not_called()

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
        """A request timeout raises RequestTimeoutError, carrying the timeout itself."""
        failure = ru.requests.exceptions.Timeout('slow')

        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=failure):
            with _app().test_request_context():
                with pytest.raises(RequestTimeoutError) as caught:
                    ru.validate_subscription_user('x', 'p')

        assert caught.value.args[0] is failure

    def test_request_exception_raises_request_error(self) -> None:
        """A generic request exception raises RequestError, carrying the exception itself."""
        failure = ru.requests.exceptions.RequestException('down')

        with patch(f'{MODULE_PATH}.os.getenv', side_effect=_portal_env), \
             patch(f'{MODULE_PATH}.requests.post', side_effect=failure):
            with _app().test_request_context():
                with pytest.raises(RequestError) as caught:
                    ru.validate_subscription_user('x', 'p')

        assert caught.value.args[0] is failure


# ============================================ parse_assistant_parameters ============================================ #
class TestParseAssistantParameters:
    """
    The decorator behind the assistant route: query parameters as the first positional argument

    It carries no `try/except Exception -> abort(400)` of its own. Werkzeug has already parsed
    the query string by the time a view runs and `to_dict` tolerates duplicate keys and embedded null
    bytes, so the arm - and the 400 its docstring promised - could never fire.
    """

    @staticmethod
    def _decorated():
        """A view that simply returns whatever the decorator injected."""
        @ru.parse_assistant_parameters()
        def _view(location_args, *args, **kwargs):
            return location_args, args, kwargs

        return _view

    def test_injects_the_query_parameters_first(self) -> None:
        """The decorated view reads them as its first positional argument, not off `request`."""
        with _app().test_request_context('/?profile=network&steps=3'):
            location_args, _, _ = self._decorated()()

        assert location_args == {'profile': 'network', 'steps': '3'}

    def test_an_empty_query_string_is_an_empty_dict(self) -> None:
        """A request with no parameters still calls the view, with nothing to act on."""
        with _app().test_request_context('/'):
            location_args, _, _ = self._decorated()()

        assert location_args == {}

    def test_later_arguments_are_forwarded_unchanged(self) -> None:
        """An inner decorator's `request_user` has to survive being pushed one position along."""
        with _app().test_request_context('/?a=1'):
            _, args, kwargs = self._decorated()('positional', request_user='user')

        assert args == ('positional',)
        assert kwargs == {'request_user': 'user'}

    def test_a_duplicate_key_keeps_the_first_value(self) -> None:
        """`to_dict` collapses duplicates rather than raising - one reason the old guard was dead."""
        with _app().test_request_context('/?profile=a&profile=b'):
            location_args, _, _ = self._decorated()()

        assert location_args == {'profile': 'a'}

    def test_it_preserves_the_wrapped_functions_identity(self) -> None:
        """`functools.wraps` matters here: Flask registers the view by its __name__."""
        @ru.parse_assistant_parameters()
        def _named_view(location_args):
            return location_args

        assert _named_view.__name__ == '_named_view'


# ================================================= refuse_inactive_user ============================================= #

class TestRefuseInactiveUser:
    """The one spelling of the deactivation rule"""

    def test_an_active_user_passes(self) -> None:
        """Nothing is raised, nothing is returned"""
        with _app().test_request_context():
            assert ru.refuse_inactive_user(SimpleNamespace(active=True)) is None

    def test_a_deactivated_user_is_a_401_naming_the_reason(self) -> None:
        """401 with the explicit message - the caller has already authenticated"""
        with _app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.refuse_inactive_user(SimpleNamespace(active=False))

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        assert exc_info.value.description == ru.USER_DEACTIVATED_MESSAGE


# ============================================ request_uses_basic_auth =============================================== #

@pytest.mark.parametrize(('header', 'expected'), [
    (BASIC_HEADER, True),
    (BASIC_HEADER.lower(), True),
    (BEARER_HEADER, False),
    (None, False),
], ids=['Basic', 'lowercase basic', 'Bearer', 'no header'])
def test_request_uses_basic_auth(header: str | None, expected: bool) -> None:
    """The scheme is matched case-insensitively, as parse_authorization_header accepts it"""
    headers: dict[str, str] = {ru.AUTHORIZATION_HEADER: header} if header else {}

    with _app().test_request_context(headers=headers):
        assert ru.request_uses_basic_auth() is expected


# ======================================== request_authenticates_by_api_key ========================================== #

@pytest.mark.parametrize(('cloud_mode', 'headers', 'expected'), [
    (True, API_KEY_BASIC_HEADERS, True),
    (True, {'Authorization': BEARER_HEADER, 'x-api-key': 'k'}, False),
    (True, {'Authorization': BASIC_HEADER}, False),
    (True, {'x-api-key': 'k'}, False),
    (False, API_KEY_BASIC_HEADERS, False),
], ids=['cloud key+Basic', 'cloud key+Bearer', 'cloud Basic only', 'cloud key only', 'on-premise key+Basic'])
def test_request_authenticates_by_api_key(cloud_mode: bool, headers: dict[str, str], expected: bool) -> None:
    """Only a cloud request pairing the key with Basic credentials is left to verify_api_access"""
    with _app(cloud_mode=cloud_mode).test_request_context(headers=headers):
        assert ru.request_authenticates_by_api_key() is expected


# ==================================== request_is_cloud_basic_without_api_key ======================================== #

@pytest.mark.parametrize(('cloud_mode', 'headers', 'expected'), [
    (True, {'Authorization': BASIC_HEADER}, True),
    (True, API_KEY_BASIC_HEADERS, False),
    (True, {'Authorization': BEARER_HEADER}, False),
    (False, {'Authorization': BASIC_HEADER}, False),
], ids=['cloud Basic only', 'cloud key+Basic', 'cloud Bearer', 'on-premise Basic'])
def test_request_is_cloud_basic_without_api_key(cloud_mode: bool, headers: dict[str, str], expected: bool) -> None:
    """Only cloud Basic credentials with no key are the refused case"""
    with _app(cloud_mode=cloud_mode).test_request_context(headers=headers):
        assert ru.request_is_cloud_basic_without_api_key() is expected


# ============================================== no nested application context ======================================= #

class TestNoNestedAppContext:
    """
    route_utils runs inside requests only, which always carry an application context

    Pushing another one inside a request gives the code under it a fresh `flask.g`: a value the request stored there
    (the licence guard's per-request state) would silently read as missing
    """

    def test_the_module_pushes_none(self) -> None:
        """No call to app_context() anywhere in the module"""
        tree = ast.parse(Path(ru.__file__).read_text(encoding='utf-8'))
        pushes: list[int] = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'app_context'
        ]

        assert not pushes
