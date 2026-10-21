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
domain managers. Every test drives a helper inside a BaseCmdbApp ``test_request_context`` (``stub_cmdb_app``) with
the managers, TokenValidator/TokenGenerator, AuthModule and the cloud-user checks patched at the module path - no
Mongo, no service-portal HTTP. The ``cloud_mode`` / ``local_mode`` flags on the app select the branch under test.

These pin: the rights check (``user_has_right``, on the user it is handed),
the error-mapping decorators (``handle_oc_errors`` 500s; the transient database errors are the app's), the
request-user injection / API-access decorators, the Authorization-header parsing and Basic/Bearer
authentication. The cloud user (the Service Portal check, the user cache, the tenant helpers) is
``cloud_user_helper``'s, tested in test_cloud_user_helper.py; ``verify_api_access`` reads its three functions through
this module, so they are patched here.
"""
# pylint: disable=protected-access  # these tests intentionally exercise module-private helpers
import ast
import base64
import inspect
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from requests import exceptions as requests_errors
from werkzeug.exceptions import Forbidden, HTTPException

from flask import abort

import cmdb.interface.route_utils as ru
from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.errors.database import (
    DatabaseConnectionError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
from cmdb.errors.security import (
    InvalidCloudUserError,
    MissingApiKeyError,
    NoAccessTokenError,
    RequestError,
    RequestTimeoutError,
    TokenValidationError,
    TokenKeyMaterialError,
)
from cmdb.errors.open_celium import AuthError
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.route_utils'
# What a wrapped OpenCelium route says it was doing, for the generic message
OC_CONTEXT: str = 'doing things'
LICENSE_GUARD_PATH: str = 'cmdb.interface.rest_api.routes.cmdb_license.license_guard'

# Module-level aliases for the double-underscore module functions (avoids name-mangling inside classes)
_get_x_api_key: Callable[..., Any] = getattr(ru, '__get_x_api_key')
_get_request_api_user: Callable[..., Any] = getattr(ru, '__get_request_api_user')
_get_request_auth_method: Callable[..., Any] = getattr(ru, '__get_request_auth_method')
_check_api_level: Callable[..., Any] = getattr(ru, '__check_api_level')

# Base64 of "user@test.com:secret"
BASIC_CREDENTIALS: str = 'dXNlckB0ZXN0LmNvbTpzZWNyZXQ='
BASIC_EMAIL: str = 'user@test.com'
BASIC_PASSWORD: str = 'secret'
BASIC_HEADER: str = f'Basic {BASIC_CREDENTIALS}'
BEARER_HEADER: str = 'Bearer sometoken'
NO_TENANT_TOKEN_MSG: str = 'The token names no tenant database!'
UNAVAILABLE_TENANT: str = 'tenant_failed_update'
API_KEY_BASIC_HEADERS: dict[str, str] = {'Authorization': BASIC_HEADER, 'x-api-key': 'k'}

DECODED_TOKEN: dict[str, Any] = {
    'DATAGERRY': {'value': {'user': {'public_id': 42, 'database': 'cloud_db'}}}
}



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

        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route()

        assert exc_info.value.code == HTTPStatus.NOT_FOUND
        assert exc_info.value.description == 'not there'

    def test_any_other_error_becomes_a_500(self) -> None:
        """The message is the route's own, wrapped in the wording every route used."""
        @ru.handle_route_errors('while doing the thing')
        def route():
            raise RuntimeError('boom')

        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route()

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == 'An internal server error occured while doing the thing!'

    def test_the_message_reads_the_routes_keyword_arguments(self) -> None:
        """`{public_id}` is what keeps the per-route text as specific as it was inline."""
        @ru.handle_route_errors('while retrieving the Subnet with ID: {public_id}')
        def route(public_id: int):
            del public_id
            raise RuntimeError('boom')

        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route(public_id=42)

        assert 'Subnet with ID: 42' in exc_info.value.description

    def test_a_positional_argument_fills_the_template_too(self) -> None:
        """The shared route bodies pass their arguments positionally, and must read the same."""
        @ru.handle_route_errors('while determining {subject} for Type with ID: {public_id}')
        def route(public_id: int, subject: str):
            del public_id, subject
            raise RuntimeError('boom')

        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            route(7, 'location-field usage')

        assert exc_info.value.description == (
            'An internal server error occured while determining location-field usage for Type with ID: 7!'
        )

    def test_an_unfillable_placeholder_leaves_the_template_alone(self) -> None:
        """A broken error message must not replace the error it was meant to describe."""
        @ru.handle_route_errors('while doing {nothing_the_route_takes}')
        def route():
            raise RuntimeError('boom')

        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
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

        with stub_cmdb_app().test_request_context(), pytest.raises(DocumentLockTimeoutError):
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
        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._decorate(raised)(ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert exc_info.value.description == template.format(public_id=ROUTE_ID)

    def test_a_failure_is_logged_as_an_error_with_the_traceback(self, caplog: pytest.LogCaptureFixture) -> None:
        """A failed operation is something to investigate."""
        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException):
            self._decorate(_ManagerFailure('boom'))(ROUTE_ID)

        record = next(r for r in caplog.records if r.name == MODULE_PATH)
        assert record.levelname == 'ERROR'
        assert record.exc_info is not None

    def test_a_refusal_is_logged_as_a_warning_without_one(self, caplog: pytest.LogCaptureFixture) -> None:
        """A declined request is the rule working, not a fault."""
        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException):
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
        with stub_cmdb_app().test_request_context(), pytest.raises(Forbidden) as exc_info:
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
        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._route(_ManagerFailure('boom'))(public_id=ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_anything_else_is_the_generic_500_with_its_placeholder_filled(self) -> None:
        """
        The generic tail fills `{public_id}` through the manager wrapper

        Without the signature the inner wrapper pins, the tail would see `(*args, **kwargs)`, fail to
        bind, and answer the unfilled template.
        """
        with stub_cmdb_app().test_request_context(), pytest.raises(HTTPException) as exc_info:
            self._route(RuntimeError('boom'))(public_id=ROUTE_ID)

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == (
            f'An internal server error occured while reading the Thing with ID: {ROUTE_ID}!'
        )


class TestUserHasRight:
    """``user_has_right`` checks the request user's group - the user is handed in, never re-read."""

    @staticmethod
    def _check(group: Any, user: Any = None) -> tuple[bool, MagicMock]:
        """Runs user_has_right with the provided GroupsManager answering `group`; answers it and the provider."""
        user = user or SimpleNamespace(group_id=3, database=None)
        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager') as get_manager:
            get_manager.return_value.get_group.return_value = group
            with stub_cmdb_app().test_request_context():
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
            with stub_cmdb_app().test_request_context():
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
        with stub_cmdb_app().test_request_context():
            assert wrapped() == 'ok'

    def test_reraises_http_exception(self) -> None:
        """An HTTPException raised by the handler is re-raised unchanged."""
        def _handler() -> None:
            raise HTTPException(description='teapot')

        with stub_cmdb_app().test_request_context():
            with pytest.raises(HTTPException):
                ru.handle_oc_errors()(_handler)()

    @pytest.mark.parametrize('error, message', [
        (AuthError('a'), ru.OC_AUTH_FAILED_MESSAGE),
        (requests_errors.ConnectTimeout('c'), ru.OC_CONNECT_TIMEOUT_MESSAGE),
        (requests_errors.ConnectionError('r'), ru.OC_CONNECTION_FAILED_MESSAGE),
        (requests_errors.SSLError('s'), ru.OC_CONNECTION_FAILED_MESSAGE),
        (requests_errors.ProxyError('p'), ru.OC_CONNECTION_FAILED_MESSAGE),
        (requests_errors.Timeout('t'), ru.OC_TIMEOUT_MESSAGE),
        (requests_errors.ReadTimeout('rt'), ru.OC_TIMEOUT_MESSAGE),
        (requests_errors.MissingSchema('m'), ru.OC_REQUEST_FAILED_MESSAGE),
        (requests_errors.InvalidURL('u'), ru.OC_REQUEST_FAILED_MESSAGE),
        (requests_errors.TooManyRedirects('x'), ru.OC_REQUEST_FAILED_MESSAGE),
        (requests_errors.RequestException('e'), ru.OC_REQUEST_FAILED_MESSAGE),
        (ValueError('generic'), ru.OC_GENERIC_ERROR_CONTEXT_MESSAGE.format(context=OC_CONTEXT)),
        (ConnectionError('builtin'), ru.OC_GENERIC_ERROR_CONTEXT_MESSAGE.format(context=OC_CONTEXT)),
    ], ids=['auth', 'connect-timeout', 'connection', 'ssl', 'proxy', 'timeout', 'read-timeout', 'missing-schema',
            'invalid-url', 'redirects', 'request', 'generic', 'builtin-connection-error'])
    def test_each_error_gets_its_arms_500(self, error: Exception, message: str) -> None:
        """
        The arm decides the message, so an arm swapped or moved shows here. ConnectTimeout is a ConnectionError and a
        Timeout - it must reach its own arm; Python's builtin ConnectionError is not requests' and is generic
        """
        def _handler() -> None:
            raise error

        with stub_cmdb_app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.handle_oc_errors(OC_CONTEXT)(_handler)()

        assert (exc_info.value.code, exc_info.value.description) == (HTTPStatus.INTERNAL_SERVER_ERROR, message)

    @pytest.mark.parametrize('error', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked')],
                             ids=['network', 'lock'])
    def test_a_transient_database_error_passes_through_untouched(self, error: Exception) -> None:
        """Not OpenCelium's: the app's error handlers answer it 503 / 423, as on every other route"""
        def _handler() -> None:
            raise error

        with stub_cmdb_app().test_request_context():
            with pytest.raises(type(error)) as exc_info:
                ru.handle_oc_errors(OC_CONTEXT)(_handler)()

        assert exc_info.value is error

    def test_without_a_context_the_generic_message_names_none(self) -> None:
        """The plain generic message, not 'while ' with nothing after it"""
        def _handler() -> None:
            raise ValueError('generic')

        with stub_cmdb_app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.handle_oc_errors()(_handler)()

        assert exc_info.value.description == ru.OC_GENERIC_ERROR_MESSAGE

    def test_the_six_messages_are_distinct(self) -> None:
        """Each arm says something different, so a reader can tell what failed"""
        messages = {ru.OC_AUTH_FAILED_MESSAGE, ru.OC_CONNECT_TIMEOUT_MESSAGE, ru.OC_CONNECTION_FAILED_MESSAGE,
                    ru.OC_TIMEOUT_MESSAGE, ru.OC_REQUEST_FAILED_MESSAGE, ru.OC_GENERIC_ERROR_MESSAGE}

        assert len(messages) == 6

    def test_the_module_does_not_shadow_the_builtin_connection_error(self) -> None:
        """requests' exceptions are reached through their module; the name ConnectionError stays Python's"""
        assert 'ConnectionError' not in vars(ru)
        assert ru.requests_errors is requests_errors


class TestEveryRouteErrorTailPassesTheAppsDatabaseErrorsThrough:
    """
    A route error decorator that catches Exception must let every error the app's handlers answer through to them -
    a lost connection, a lock timeout and the connector's own DatabaseConnectionError. The scan finds every decorator
    here that catches Exception, so a new one cannot miss it
    """

    # The decorators a route's error tail is built from, with how to apply one to a handler
    TAILS: dict[str, Callable[[Callable[..., Any]], Callable[..., Any]]] = {
        'handle_route_errors': lambda handler: ru.handle_route_errors('doing things')(handler),
        'handle_oc_errors': lambda handler: ru.handle_oc_errors(OC_CONTEXT)(handler),
        'handle_manager_errors': lambda handler: ru.handle_manager_errors(
            failures={ValueError: 'failed {public_id}'})(handler),
    }

    def test_the_census_names_every_error_tail(self) -> None:
        """Every module-level handle_* decorator that catches Exception is one of TAILS"""
        tree = ast.parse(Path(ru.__file__).read_text(encoding='utf-8'))
        catching: set[str] = {
            function.name for function in tree.body
            if isinstance(function, ast.FunctionDef) and function.name.startswith('handle_')
            and any(isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name)
                    and node.type.id == 'Exception' for node in ast.walk(function))
        }

        assert catching == set(self.TAILS)

    @pytest.mark.parametrize('tail', sorted(TAILS))
    @pytest.mark.parametrize('error_class', [DocumentNetworkError, DocumentLockTimeoutError, DatabaseConnectionError],
                             ids=['network', 'lock', 'connector'])
    def test_each_tail_re_raises_it_unchanged(self, tail: str, error_class: type[Exception]) -> None:
        """The same instance, so its handler sees the original error"""
        error: Exception = error_class('transient')

        def _handler(*_args: Any, **_kwargs: Any) -> None:
            raise error

        with stub_cmdb_app().test_request_context():
            with pytest.raises(error_class) as exc_info:
                self.TAILS[tail](_handler)()

        assert exc_info.value is error


# ================================================ insert_request_user =============================================== #

class TestInsertRequestUser:
    """``insert_request_user`` injects the resolved user as ``request_user``."""

    def test_cloud_api_key_passes_through(self) -> None:
        """In cloud mode an x-api-key request with Basic credentials is left to verify_api_access."""
        handler = MagicMock(return_value='done')
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header') as parse:
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                assert ru.insert_request_user(handler)() == 'done'
        handler.assert_called_once()
        parse.assert_not_called()

    def test_cloud_basic_without_an_api_key_is_refused_with_its_own_401(self) -> None:
        """Not the generic token failure: the caller is told the key is missing, and nothing is authenticated"""
        handler = MagicMock()
        with patch(f'{MODULE_PATH}.parse_authorization_header') as parse:
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=headers):
                assert ru.insert_request_user(_handler)() == 'ran'
        assert captured['request_user'] is user

    def test_missing_header_aborts_401(self) -> None:
        """A request without an Authorization header aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_invalid_token_aborts_401(self) -> None:
        """A token that fails validation aborts with 401."""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED

    def test_key_material_failure_aborts_500(self) -> None:
        """The decorator every route carries reports a key problem as the server's, not the caller's"""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.decode_request_token', side_effect=TokenKeyMaterialError('no key')):
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_database_outage_is_left_to_the_app_handler(self) -> None:
        """Not a 401: the app's handler answers a DocumentNetworkError 503, so the user is not logged out"""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', side_effect=DocumentNetworkError('lost')):
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(DocumentNetworkError):
                    ru.insert_request_user(lambda **_: None)()

    def test_a_bug_while_decoding_is_not_a_401(self) -> None:
        """A programming error reaches the app (500) instead of looking like an expired session"""
        with patch(f'{MODULE_PATH}.UsersManager'), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = RuntimeError('boom')
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(RuntimeError):
                    ru.insert_request_user(lambda **_: None)()

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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
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
        app = stub_cmdb_app(cloud_mode=True)
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
        app = stub_cmdb_app(cloud_mode=True)
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
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.insert_request_user(lambda **_: 'ran')() == 'ran'

    def test_the_api_key_path_builds_no_users_manager(self) -> None:
        """verify_api_access resolves that user; nothing is built here only to be thrown away"""
        with patch(f'{MODULE_PATH}.UsersManager') as users_manager_cls:
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
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
        app = stub_cmdb_app(cloud_mode=cloud_mode)

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
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
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
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
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
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
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
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
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
            with stub_cmdb_app().test_request_context(headers=headers):
                with pytest.raises(HTTPException) as exc_info:
                    ru.insert_request_user(MagicMock())()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        enforce.assert_not_called()

    def test_a_bug_in_the_user_read_is_not_a_401(self) -> None:
        """A programming error while resolving the user reaches the app (500)"""
        users_manager = MagicMock()
        users_manager.get_user.side_effect = ValueError('bad')

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = {'DATAGERRY': {'value': {'user': {'public_id': 1}}}}
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(ValueError):
                    ru.insert_request_user(lambda **_: None)()

    @staticmethod
    def _resolve_raising(raised: Exception) -> None:
        """Runs the decorator with a user read that raises `raised`"""
        users_manager = MagicMock()
        users_manager.get_user.side_effect = raised

        with patch(f'{MODULE_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = {'DATAGERRY': {'value': {'user': {'public_id': 1}}}}
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                ru.insert_request_user(lambda **_: None)()

    def test_an_unreadable_user_is_a_500_not_a_logout(self) -> None:
        """A stored user the manager cannot read is the server's fault"""
        with pytest.raises(HTTPException) as exc_info:
            self._resolve_raising(UsersManagerGetError('broken'))

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == ru.USER_UNREADABLE_MESSAGE

    @pytest.mark.parametrize('outage', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked')],
                             ids=['network', 'lock'])
    def test_an_outage_in_the_user_read_is_left_to_the_app_handler(self, outage: Exception) -> None:
        """The app answers 503 / 423, so the frontend does not log the user out"""
        with pytest.raises(type(outage)):
            self._resolve_raising(outage)


# ============================================ decode_authorization_token ============================================ #

class TestDecodeAuthorizationToken:
    """The token half: only the caller's credentials answer 401."""

    def test_no_header_is_a_401_with_its_message(self) -> None:
        """Nothing to read"""
        with stub_cmdb_app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                ru.decode_authorization_token()

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.UNAUTHORIZED, ru.NO_AUTHORIZATION_HEADER_MESSAGE)

    def test_answers_the_claims(self) -> None:
        """The parsed token decoded once"""
        with patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok') as parse, \
             patch(f'{MODULE_PATH}.decode_request_token', return_value=DECODED_TOKEN) as decode:
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                assert ru.decode_authorization_token() == DECODED_TOKEN

        parse.assert_called_once_with(BEARER_HEADER)
        decode.assert_called_once_with('tok')

    def test_an_invalid_token_is_a_401_with_its_message(self) -> None:
        """A failed login, an unknown scheme and a bad token all reach here as TokenValidationError"""
        with patch(f'{MODULE_PATH}.parse_authorization_header', return_value=None), \
             patch(f'{MODULE_PATH}.decode_request_token', side_effect=TokenValidationError('bad')):
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.decode_authorization_token()

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.UNAUTHORIZED, ru.INVALID_TOKEN_MESSAGE)

    def test_missing_key_material_is_a_500(self) -> None:
        """The server's fault, never a logout"""
        with patch(f'{MODULE_PATH}.parse_authorization_header', return_value='tok'), \
             patch(f'{MODULE_PATH}.decode_request_token', side_effect=TokenKeyMaterialError('no key')):
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.decode_authorization_token()

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.INTERNAL_SERVER_ERROR, ru.KEY_MATERIAL_UNAVAILABLE_MESSAGE)

    @pytest.mark.parametrize('raised', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'),
                                        RuntimeError('bug')], ids=['network', 'lock', 'bug'])
    def test_anything_else_passes_through(self, raised: Exception) -> None:
        """An outage is the app handler's (503 / 423), a bug the app's 500"""
        with patch(f'{MODULE_PATH}.parse_authorization_header', side_effect=raised):
            with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
                with pytest.raises(type(raised)):
                    ru.decode_authorization_token()


# ================================================ resolve_token_user ================================================ #

class TestResolveTokenUser:
    """The user half: claims -> tenant -> user, each refusal with its own answer."""

    @staticmethod
    def _resolve(claims: Any, cloud_mode: bool = False, user: Any = None) -> tuple[Any, MagicMock]:
        """Runs the helper with a users manager answering `user`; the result and the manager class"""
        with patch(f'{MODULE_PATH}.UsersManager') as manager_class, \
             patch(f'{MODULE_PATH}.abort_if_tenant_unavailable'):
            manager_class.return_value.get_user.return_value = user
            with stub_cmdb_app(cloud_mode=cloud_mode).test_request_context():
                return ru.resolve_token_user(claims), manager_class

    @pytest.mark.parametrize('claims', [
        {}, {'DATAGERRY': 'flat'}, {'DATAGERRY': {'value': {}}}, {'DATAGERRY': {'value': {'user': {}}}},
        {'DATAGERRY': {'value': {'user': 'not-a-claim'}}},
    ], ids=['no-claim', 'flat-claim', 'no-user', 'no-public-id', 'user-not-a-dict'])
    def test_claims_without_a_usable_user_are_an_invalid_token(self, claims: Any) -> None:
        """401 with the token's message, before any user read"""
        with pytest.raises(HTTPException) as exc_info:
            self._resolve(claims)

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.UNAUTHORIZED, ru.INVALID_TOKEN_MESSAGE)

    def test_a_cloud_claim_without_a_database_key_is_an_invalid_token(self) -> None:
        """The cloud token always names its tenant"""
        with pytest.raises(HTTPException) as exc_info:
            self._resolve({'DATAGERRY': {'value': {'user': {'public_id': 1}}}}, cloud_mode=True)

        assert exc_info.value.description == ru.INVALID_TOKEN_MESSAGE

    @pytest.mark.parametrize('database', [None, ''], ids=['null', 'empty'])
    def test_a_cloud_claim_naming_no_tenant_is_a_401(self, database: Any) -> None:
        """Its own message"""
        with pytest.raises(HTTPException) as exc_info:
            self._resolve({'DATAGERRY': {'value': {'user': {'public_id': 1, 'database': database}}}},
                          cloud_mode=True)

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.UNAUTHORIZED, ru.NO_TENANT_DATABASE_MESSAGE)

    def test_an_unknown_user_is_a_401(self) -> None:
        """The token is fine, its user is gone"""
        with pytest.raises(HTTPException) as exc_info:
            self._resolve(DECODED_TOKEN)

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.UNAUTHORIZED, ru.INVALID_USER_MESSAGE)

    @pytest.mark.parametrize('cloud_mode, database', [(True, 'cloud_db'), (False, None)],
                             ids=['cloud', 'on-premise'])
    def test_answers_the_user_read_in_the_tokens_tenant(self, cloud_mode: bool, database: Any) -> None:
        """One manager, bound to the tenant in cloud mode and to the process database on premise"""
        user = SimpleNamespace(public_id=42)

        resolved, manager_class = self._resolve(DECODED_TOKEN, cloud_mode=cloud_mode, user=user)

        assert resolved is user
        assert manager_class.call_args.args[1] == database
        manager_class.return_value.get_user.assert_called_once_with(42)


# ================================================= verify_api_access ================================================ #

class TestVerifyApiAccess:
    """``verify_api_access`` gates cloud API access by auth method and API level."""

    def test_non_cloud_passes_through(self) -> None:
        """Outside cloud mode the decorator is a no-op."""
        handler = MagicMock(return_value='ok')
        with stub_cmdb_app(cloud_mode=False).test_request_context():
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                assert ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(_handler)() == 'ran'
        assert captured['request_user'] is user_model

    def test_basic_hands_the_portal_the_header_credentials_and_api_key(self) -> None:
        """The portal is asked with the Basic header's email and password, in that order, and the x-api-key"""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}

        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance) as portal, \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=True)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_kwargs: 'ran')()

        assert portal.call_args.args == (BASIC_EMAIL, BASIC_PASSWORD, API_KEY_BASIC_HEADERS['x-api-key'])
        assert portal.call_args.kwargs == {'api_key_required': True}

    def test_a_deactivated_api_key_user_is_refused_and_the_handler_never_runs(self) -> None:
        """The portal accepted the credentials, the tenant stored the account deactivated: 401"""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        handler = MagicMock()

        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=False)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(handler)()

        assert exc_info.value.code == HTTPStatus.UNAUTHORIZED
        assert exc_info.value.description == ru.USER_DEACTIVATED_MESSAGE
        handler.assert_not_called()

    def test_an_api_key_user_of_an_unavailable_tenant_aborts_503_before_any_write(self) -> None:
        """The tenant is checked before set_admin_user writes to it and before the user is read"""
        user_instance = {'subscriptions': [{'database': UNAVAILABLE_TENANT, 'api_level': 1}], 'api_level': 1}
        handler = MagicMock()
        app = stub_cmdb_app(cloud_mode=True)
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
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
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                assert ru.verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)(handler)() == 'ok'
        set_admin.assert_not_called()

    def test_insufficient_api_level_aborts_403(self) -> None:
        """A user below the required API level aborts with 403."""
        user_instance = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=user_instance), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=True)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=False):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_reraises_http_exception(self) -> None:
        """An HTTPException from the auth flow is re-raised unchanged."""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', side_effect=HTTPException()):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(HTTPException):
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()

    def test_jwt_method_skips_basic_flow(self) -> None:
        """A JWT (Bearer) auth method skips the Basic-login block and runs the handler."""
        handler = MagicMock(return_value='ok')
        with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(handler)() == 'ok'
        handler.assert_called_once()

    def test_a_bug_is_not_a_400(self) -> None:
        """A programming error reaches the app (500) instead of reading as the caller's mistake"""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', side_effect=RuntimeError('boom')):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': BASIC_HEADER}):
                with pytest.raises(RuntimeError):
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()


# ======================================== the API-key channel's answers ============================================ #

API_USER: dict[str, Any] = {'subscriptions': [{'database': 'db', 'api_level': 1}], 'api_level': 1}


def _api_key_request(level: ApiLevel = ApiLevel.ADMIN, headers: dict[str, str] | None = None,
                     check: Any = None, check_answer: Any = API_USER, admin: Any = None,
                     user: Any = SimpleNamespace(public_id=1, active=True)) -> Any:
    """Runs a cloud API-key request through verify_api_access with the portal check and the user helpers patched"""
    with patch(f'{MODULE_PATH}.check_user_in_service_portal', side_effect=check, return_value=check_answer), \
         patch(f'{MODULE_PATH}.set_admin_user', side_effect=admin), \
         patch(f'{MODULE_PATH}.retrieve_user', return_value=user), \
         patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
        with stub_cmdb_app(cloud_mode=True).test_request_context(
                headers=headers if headers is not None else API_KEY_BASIC_HEADERS):
            return ru.verify_api_access(required_api_level=level)(lambda **kwargs: kwargs)()


def _refusal(**kwargs: Any) -> tuple[int, str]:
    """The status and message an API-key request is refused with"""
    with pytest.raises(HTTPException) as exc_info:
        _api_key_request(**kwargs)

    return exc_info.value.code, exc_info.value.description


class TestTheApiKeyChannelAnswers:
    """Only the caller's credentials and account answer 401 / 403; a fault that is not the caller's never a 400."""

    @pytest.mark.parametrize('level', [ApiLevel.ADMIN, ApiLevel.SUPER_ADMIN], ids=['admin', 'super-admin'])
    @pytest.mark.parametrize('kwargs', [
        {'check': InvalidCloudUserError('refused')}, {'check': MissingApiKeyError('no key')}, {'check_answer': None},
        {'headers': {'Authorization': 'Basic !!!not-base64', 'x-api-key': 'k'}},
    ], ids=['refused', 'no-key', 'no-answer', 'unreadable-credentials'])
    def test_refused_credentials_are_a_401_on_every_level(self, kwargs: dict[str, Any], level: ApiLevel) -> None:
        """The same answer whatever the route's level - a SUPER_ADMIN route answered 403 before"""
        assert _refusal(level=level, **kwargs) == (HTTPStatus.UNAUTHORIZED, ru.INVALID_API_CREDENTIALS_MESSAGE)

    @pytest.mark.parametrize('error, message', [
        (NoAccessTokenError('none'), ru.PORTAL_NOT_CONFIGURED_MESSAGE),
        (RequestTimeoutError('slow'), ru.PORTAL_TIMEOUT_MESSAGE),
        (RequestError('down'), ru.PORTAL_REQUEST_FAILED_MESSAGE),
    ], ids=['not-configured', 'timeout', 'request'])
    def test_a_portal_fault_is_a_500(self, error: Exception, message: str) -> None:
        """Not the caller's fault"""
        assert _refusal(check=error) == (HTTPStatus.INTERNAL_SERVER_ERROR, message)

    @pytest.mark.parametrize('answer', [
        {'api_level': 1}, {'subscriptions': []}, {'subscriptions': 'flat'}, {'subscriptions': ['flat']},
        {'subscriptions': [{'api_level': 1}]}, {'subscriptions': [{'database': ''}]},
    ], ids=['no-key', 'empty', 'not-a-list', 'not-a-dict', 'no-database', 'empty-database'])
    def test_an_account_without_a_subscription_is_a_401(self, answer: dict[str, Any]) -> None:
        """cloud_login's answer for the same account - it crashed into the 400 here"""
        assert _refusal(check_answer=answer) == (HTTPStatus.UNAUTHORIZED, ru.NO_SUBSCRIPTION_MESSAGE)

    def test_a_super_admin_route_needs_no_subscription(self) -> None:
        """It acts on no tenant, so no user is resolved"""
        assert 'request_user' not in _api_key_request(level=ApiLevel.SUPER_ADMIN, check_answer={'api_level': 2})

    @pytest.mark.parametrize('error, message', [
        (UsersManagerGetError('read'), ru.API_USER_UNREADABLE_MESSAGE),
        (UsersManagerInsertError('write'), ru.API_USER_NOT_STORED_MESSAGE),
    ], ids=['read', 'write'])
    def test_a_tenant_user_the_server_cannot_sync_is_a_500(self, error: Exception, message: str) -> None:
        """The server's fault"""
        assert _refusal(admin=error) == (HTTPStatus.INTERNAL_SERVER_ERROR, message)

    @pytest.mark.parametrize('outage', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked')],
                             ids=['network', 'lock'])
    def test_an_outage_in_the_user_sync_reaches_the_app_handler(self, outage: Exception) -> None:
        """set_admin_user lets an outage through as itself; the channel does not catch it (503 / 423)"""
        with pytest.raises(type(outage)):
            _api_key_request(admin=outage)

    def test_a_tenant_user_that_cannot_be_read_is_a_500(self) -> None:
        """retrieve_user no longer answers a failed read as "no such user" (the 403)"""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=API_USER), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', side_effect=UsersManagerGetError('broken')), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=True):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.INTERNAL_SERVER_ERROR, ru.API_USER_UNREADABLE_MESSAGE)

    @pytest.mark.parametrize('outage', [DocumentNetworkError('lost'), DocumentLockTimeoutError('locked')],
                             ids=['network', 'lock'])
    def test_an_outage_in_the_portal_check_reaches_the_app_handler(self, outage: Exception) -> None:
        """The user-cache read is a database read like any other"""
        with pytest.raises(type(outage)):
            _api_key_request(check=outage)

    def test_an_unknown_tenant_user_stays_a_403(self) -> None:
        """Unchanged, with its message"""
        assert _refusal(user=None) == (HTTPStatus.FORBIDDEN, ru.API_USER_NOT_FOUND_MESSAGE)

    def test_an_unknown_scheme_stays_a_400(self) -> None:
        """Neither Basic nor Bearer: a malformed request"""
        with stub_cmdb_app(cloud_mode=True).test_request_context(headers={'Authorization': 'Digest abc'}):
            with pytest.raises(HTTPException) as exc_info:
                ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_the_level_refusal_keeps_its_message(self) -> None:
        """403 below the route's level"""
        with patch(f'{MODULE_PATH}.check_user_in_service_portal', return_value=API_USER), \
             patch(f'{MODULE_PATH}.set_admin_user'), \
             patch(f'{MODULE_PATH}.retrieve_user', return_value=SimpleNamespace(public_id=1, active=True)), \
             patch(f'{MODULE_PATH}.__check_api_level', return_value=False):
            with stub_cmdb_app(cloud_mode=True).test_request_context(headers=API_KEY_BASIC_HEADERS):
                with pytest.raises(HTTPException) as exc_info:
                    ru.verify_api_access(required_api_level=ApiLevel.ADMIN)(lambda **_: None)()

        assert (exc_info.value.code, exc_info.value.description) == (HTTPStatus.FORBIDDEN, ru.API_LEVEL_DENIED_MESSAGE)


# ============================================ request header primitives ============================================= #

class TestRequestHeaderPrimitives:
    """The small header-inspection helpers (x-api-key, api user, auth method)."""

    def test_get_x_api_key_present_and_absent(self) -> None:
        """The x-api-key header is returned when present, else None."""
        with stub_cmdb_app().test_request_context(headers={'x-api-key': 'abc'}):
            assert _get_x_api_key() == 'abc'
        with stub_cmdb_app().test_request_context():
            assert _get_x_api_key() is None

    def test_get_request_api_user_basic_returns_credentials(self) -> None:
        """A Basic Authorization header yields the decoded email/password dict."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': BASIC_HEADER}):
            result = _get_request_api_user()
        assert result == {'email': 'user@test.com', 'password': 'secret'}

    def test_get_request_api_user_bearer_returns_none(self) -> None:
        """A non-Basic header yields None."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert _get_request_api_user() is None

    def test_get_request_api_user_missing_header_returns_none(self) -> None:
        """A missing Authorization header is handled and yields None."""
        with stub_cmdb_app().test_request_context():
            assert _get_request_api_user() is None

    def test_get_request_api_user_schemeless_treated_as_bearer(self) -> None:
        """A single-token header (no scheme) is treated as bearer and yields None."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': 'rawtoken'}):
            assert _get_request_api_user() is None

    def test_get_request_auth_method_basic(self) -> None:
        """A 'Basic ' header maps to AuthMethod.BASIC."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': BASIC_HEADER}):
            assert _get_request_auth_method() == AuthMethod.BASIC

    def test_get_request_auth_method_bearer(self) -> None:
        """A 'Bearer ' header maps to AuthMethod.JWT."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': BEARER_HEADER}):
            assert _get_request_auth_method() == AuthMethod.JWT

    def test_get_request_auth_method_invalid_aborts_400(self) -> None:
        """An unrecognised auth scheme aborts with 400."""
        with stub_cmdb_app().test_request_context(headers={'Authorization': 'Digest xyz'}):
            with pytest.raises(HTTPException) as exc_info:
                _get_request_auth_method()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_get_request_auth_method_missing_aborts_400(self) -> None:
        """A missing header aborts with 400."""
        with stub_cmdb_app().test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                _get_request_auth_method()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ================================================= __check_api_level ================================================ #

class TestCheckApiLevel:
    """``__check_api_level`` compares a user's API level against the requirement."""

    def test_non_cloud_returns_true(self) -> None:
        """Outside cloud mode the check always passes."""
        with stub_cmdb_app(cloud_mode=False).test_request_context():
            assert _check_api_level({}, ApiLevel.ADMIN) is True

    def test_no_user_returns_false(self) -> None:
        """A missing user instance fails the check."""
        with stub_cmdb_app(cloud_mode=True).test_request_context():
            assert _check_api_level(None, ApiLevel.ADMIN) is False

    def test_locked_level_returns_false(self) -> None:
        """A LOCKED requirement always fails."""
        with stub_cmdb_app(cloud_mode=True).test_request_context():
            assert _check_api_level({'api_level': 3}, ApiLevel.LOCKED) is False

    def test_super_admin_compares_top_level(self) -> None:
        """SUPER_ADMIN compares the top-level api_level field."""
        with stub_cmdb_app(cloud_mode=True).test_request_context():
            assert _check_api_level({'api_level': 2}, ApiLevel.SUPER_ADMIN) is True
            assert _check_api_level({'api_level': 1}, ApiLevel.SUPER_ADMIN) is False

    def test_admin_compares_subscription_level(self) -> None:
        """A non-super requirement compares the first subscription's api_level."""
        with stub_cmdb_app(cloud_mode=True).test_request_context():
            assert _check_api_level({'subscriptions': [{'api_level': 1}]}, ApiLevel.ADMIN) is True

    def test_malformed_user_returns_false(self) -> None:
        """A user dict missing the expected keys fails safely."""
        with stub_cmdb_app(cloud_mode=True).test_request_context():
            assert _check_api_level({'subscriptions': []}, ApiLevel.ADMIN) is False


# ============================================ parse_authorization_header ============================================ #

class TestSplitAuthorizationHeader:
    """The one parser of the Authorization header both readers share"""

    @pytest.mark.parametrize('header, expected', [
        ('Basic abc', ('basic', 'abc')),
        ('BEARER xyz', ('bearer', 'xyz')),
        ('Bearer  spaced  token', ('bearer', 'spaced  token')),
        ('onlytoken', ('bearer', 'onlytoken')),
        ('Digest a=b', ('digest', 'a=b')),
    ], ids=['basic', 'scheme-case', 'rest-kept-whole', 'no-scheme-is-bearer', 'other-scheme'])
    def test_scheme_and_credentials(self, header: str, expected: tuple[str, str]) -> None:
        """The scheme lower-cased, the credentials as sent; no scheme reads as a bearer token"""
        assert ru.split_authorization_header(header) == expected

    def test_both_readers_use_it(self) -> None:
        """parse_authorization_header and the API-user read split the header the same way"""
        source: str = inspect.getsource(ru)
        readers = [ru.parse_authorization_header, getattr(ru, '__get_request_api_user')]

        assert all('split_authorization_header(' in inspect.getsource(reader) for reader in readers)
        assert '_wsgi_decoding_dance' not in source and 'werkzeug._internal' not in source


class TestDecodeHeaderValue:
    """WSGI's latin-1 header string read back as the UTF-8 the client sent"""

    def test_utf8_credentials_come_back_whole(self) -> None:
        """A non-ASCII password in Basic credentials survives the WSGI round trip"""
        sent: str = 'Basic pässwörd'
        as_wsgi_hands_it: str = sent.encode('utf-8').decode('latin-1')

        assert ru.decode_header_value(as_wsgi_hands_it) == sent

    def test_ascii_is_unchanged(self) -> None:
        """The common case costs nothing"""
        assert ru.decode_header_value(BEARER_HEADER) == BEARER_HEADER

    def test_bytes_that_are_no_utf8_become_the_replacement_character(self) -> None:
        """Never an error on a header a client got wrong"""
        assert ru.decode_header_value('\xff') == '\ufffd'


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
            with stub_cmdb_app().test_request_context():
                first = ru.parse_authorization_header(BEARER_HEADER)
                second = ru.parse_authorization_header(BEARER_HEADER)

        assert (first, second) == ('sometoken', 'sometoken')
        mocked.assert_called_once_with('sometoken')

    def test_a_different_header_is_parsed_on_its_own(self) -> None:
        """The cache is keyed by the header, so two credentials in one request cannot be confused"""
        with patch(f'{MODULE_PATH}._validate_bearer', side_effect=['first', 'second']) as mocked:
            with stub_cmdb_app().test_request_context():
                assert ru.parse_authorization_header('Bearer one') == 'first'
                assert ru.parse_authorization_header('Bearer two') == 'second'

        assert mocked.call_count == 2

    def test_a_refused_header_is_cached_too(self) -> None:
        """A None answer is an answer: re-validating a bad token per decorator buys nothing"""
        with patch(f'{MODULE_PATH}._validate_bearer', return_value=None) as mocked:
            with stub_cmdb_app().test_request_context():
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
            with stub_cmdb_app().test_request_context():
                assert ru.decode_request_token('sometoken') == DECODED_TOKEN

    def test_the_decode_is_cached_for_the_request(self) -> None:
        """
        One RSA verification and one key read per request instead of one per decorator

        A single GET was measured at 4 decodes and 12 reads of the key document before this.
        """
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with stub_cmdb_app().test_request_context():
                ru.decode_request_token('sometoken')
                ru.decode_request_token('sometoken')

        tv_cls.return_value.decode_token.assert_called_once()

    def test_a_bytes_token_hits_the_same_cache_entry(self) -> None:
        """The generator answers bytes and the header carries a str - the same token either way"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with stub_cmdb_app().test_request_context():
                ru.decode_request_token('sometoken')
                ru.decode_request_token(b'sometoken')

        tv_cls.return_value.decode_token.assert_called_once()

    def test_a_failure_is_not_cached_as_a_result(self) -> None:
        """A refused token raises for every caller, rather than the first one poisoning the cache"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.side_effect = TokenValidationError('bad')
            with stub_cmdb_app().test_request_context():
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

    @pytest.mark.parametrize('failure', [TokenKeyMaterialError('no key'), DocumentNetworkError('lost')],
                             ids=['key-material', 'outage'])
    def test_a_signing_failure_is_not_a_failed_login(self, failure: Exception) -> None:
        """
        The credentials were fine and the server could not sign for them: raised, not None

        None would make the request a 401 that logs the user out over the server's fault
        """
        user = MagicMock()
        user.get_public_id.return_value = 5
        with self._patches(login_result=user), patch(f'{MODULE_PATH}.TokenGenerator', side_effect=failure):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
                with pytest.raises(type(failure)):
                    ru._authenticate_basic(BASIC_CREDENTIALS)

    def test_non_cloud_success_returns_token(self) -> None:
        """Outside cloud mode a successful login returns a freshly generated token."""
        user = MagicMock()
        user.get_public_id.return_value = 5
        with self._patches(login_result=user, token='jwt-token'):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
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
            with stub_cmdb_app(cloud_mode=True, local_mode=local_mode).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

            portal.assert_not_called()
            ru.AuthModule.return_value.login.assert_not_called()

    def test_on_premise_the_login_is_stripped(self) -> None:
        """The case is AuthModule's to try; the whitespace is removed here"""
        credentials: str = base64.b64encode(b' Admin :secret').decode('utf-8')
        with self._patches(login_result=MagicMock()):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
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
            with stub_cmdb_app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_no_user_returns_none(self) -> None:
        """A login that returns no user yields None."""
        with self._patches(login_result=None):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_a_failed_users_manager_build_returns_none(self) -> None:
        """A failure building the UsersManager is caught and yields None."""
        with patch(f'{MODULE_PATH}.UsersManager', side_effect=RuntimeError('bad db')):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
                assert ru._authenticate_basic(BASIC_CREDENTIALS) is None

    def test_generic_error_returns_none(self) -> None:
        """A generic error (e.g. malformed base64) yields None."""
        with stub_cmdb_app(cloud_mode=False).test_request_context():
            assert ru._authenticate_basic('not-valid-base64!!') is None


# ================================================== _validate_bearer ================================================ #

class TestValidateBearer:
    """``_validate_bearer`` returns the token unchanged when it validates."""

    def test_valid_token_returned(self) -> None:
        """A token that decodes and validates is returned unchanged."""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.decode_token.return_value = DECODED_TOKEN
            with stub_cmdb_app().test_request_context():
                assert ru._validate_bearer('sometoken') == 'sometoken'

    def test_expired_token_returns_none(self) -> None:
        """
        A token whose claims fail validation yields None

        This is the ONLY place expiry is enforced for a request - the per-route decorators decode
        but do not re-validate - so the step is asserted here by name.
        """
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.validate_claims.side_effect = TokenValidationError('expired')
            with stub_cmdb_app().test_request_context():
                assert ru._validate_bearer('sometoken') is None

    def test_foreign_issuer_returns_none(self) -> None:
        """A token this product did not issue is refused, even with a valid signature"""
        with patch(f'{MODULE_PATH}.TokenValidator') as tv_cls:
            tv_cls.return_value.validate_issuer.side_effect = TokenValidationError('foreign')
            with stub_cmdb_app().test_request_context():
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
            with stub_cmdb_app().test_request_context():
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
            with stub_cmdb_app().test_request_context():
                with pytest.raises(TokenKeyMaterialError):
                    ru._validate_bearer('sometoken')

    @pytest.mark.parametrize('failure', [TokenKeyMaterialError('no key'), DocumentNetworkError('lost')],
                             ids=['key-material', 'outage'])
    def test_a_validator_that_cannot_be_built_is_not_a_bad_token(self, failure: Exception) -> None:
        """The key is read when the validator is BUILT - that failure propagates too, never None"""
        with patch(f'{MODULE_PATH}.TokenValidator', side_effect=failure):
            with stub_cmdb_app().test_request_context():
                with pytest.raises(type(failure)):
                    ru._validate_bearer('sometoken')


# ================================================= refuse_inactive_user ============================================= #

class TestRefuseInactiveUser:
    """The one spelling of the deactivation rule"""

    def test_an_active_user_passes(self) -> None:
        """Nothing is raised, nothing is returned"""
        with stub_cmdb_app().test_request_context():
            assert ru.refuse_inactive_user(SimpleNamespace(active=True)) is None

    def test_a_deactivated_user_is_a_401_naming_the_reason(self) -> None:
        """401 with the explicit message - the caller has already authenticated"""
        with stub_cmdb_app().test_request_context():
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

    with stub_cmdb_app().test_request_context(headers=headers):
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
    with stub_cmdb_app(cloud_mode=cloud_mode).test_request_context(headers=headers):
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
    with stub_cmdb_app(cloud_mode=cloud_mode).test_request_context(headers=headers):
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
