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
The glue every REST route is wrapped in

Two concerns live here:

    - the route decorators and their answers: the error tails (`handle_route_errors`, `handle_manager_errors`,
      `handle_oc_errors`), the upload limits (`accepts_upload`), the shared size-limit answer (`abort_if_too_large`)
      and the rights check (`user_has_right`)
    - who the request is: the Authorization header read once (`split_authorization_header`), Basic credentials and
      bearer tokens (`parse_authorization_header`), the request user injected into the route (`insert_request_user`)
      and the cloud API access with its level (`verify_api_access`)

The cloud user behind a hosted-cloud request - the Service Portal check, the user cache and the tenant helpers - is
`cloud_user_helper`'s; `verify_api_access` reads its three functions through this module, which is where a test
patches them
"""
import base64
import functools
import inspect
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Any, Callable, Collection
from requests import exceptions as requests_errors
from flask import request, abort, current_app, has_request_context
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    UsersManager,
    GroupsManager,
    SecurityManager,
    SettingsManager,
)

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.login_name import strip_login
from cmdb import __title__
from cmdb.security.token.validator import TokenValidator
from cmdb.security.token.token_constants import TokenClaim, TokenClaimWrapperKey, TokenPayloadKey
from cmdb.security.token.generator import TokenGenerator

from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.cached_user_model import CachedSubscriptionKey, CachedUserKey

from cmdb.errors.security import (
    InvalidCloudUserError,
    MissingApiKeyError,
    NoAccessTokenError,
    RequestError,
    RequestTimeoutError,
    TokenValidationError,
    TokenKeyMaterialError,
)
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE
from cmdb.interface.query_time_limit import abort_if_query_too_slow
from cmdb.interface.tenant_availability import abort_if_tenant_unavailable
from cmdb.interface.cloud_user_helper import check_user_in_service_portal, retrieve_user, set_admin_user
from cmdb.utils import find_cause
from cmdb.errors.database import (
    DocumentTooLargeError,
    TRANSIENT_DATABASE_ERRORS,
    APP_HANDLED_DATABASE_ERRORS,
)
from cmdb.errors.open_celium import AuthError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

DEFAULT_MIME_TYPE = 'application/json'

# The refusal every authentication path answers for a CmdbUser whose `active` flag is false. Only ever
# shown to a caller who has proven the password or holds a valid token, so it reveals nothing new
USER_DEACTIVATED_MESSAGE: str = 'This user account is deactivated!'

AUTHORIZATION_HEADER: str = 'Authorization'

# Prefix of an `Authorization` header carrying HTTP Basic credentials (e.g. "Basic dXNlcjpwYXNz")
BASIC_AUTH_HEADER_PREFIX: str = f'{AuthMethod.BASIC.value} '

# The cloud API-key header a subscription's external automation sends next to its Basic credentials
API_KEY_HEADER: str = 'x-api-key'

# The refusal (HTTP 401) of HTTP Basic credentials sent WITHOUT an x-api-key in cloud mode. The Service Portal
# answers such a login with every subscription and no tenant to log into, so the key is what names the tenant
CLOUD_BASIC_WITHOUT_API_KEY_MESSAGE: str = (
    f'In cloud mode HTTP Basic credentials are accepted only together with an {API_KEY_HEADER} header!'
)

# The 500 of a request whose token cannot be verified or signed because the key material cannot be obtained - the
# server's fault, so never a 401 (which would log the user out)
KEY_MATERIAL_UNAVAILABLE_MESSAGE: str = "The token could not be verified because of a server-side key problem!"

# The 401s of a request whose credentials do not identify a user: no header, a token that does not decode or
# validate - or carries no user claim -, a cloud token naming no tenant, and a user the tenant does not hold
NO_AUTHORIZATION_HEADER_MESSAGE: str = "No Authorization header provided!"
INVALID_TOKEN_MESSAGE: str = "Invalid Token!"
NO_TENANT_DATABASE_MESSAGE: str = "The token names no tenant database!"
INVALID_USER_MESSAGE: str = "Invalid user!"

# The 500 of a request whose user is stored but cannot be read - the server's fault, so never a 401 (which would log
# the user out)
USER_UNREADABLE_MESSAGE: str = "The user of this token could not be read!"

# The answers of the cloud API-key channel (`verify_api_access`): the caller's credentials and account (401 / 403),
# and the faults that are not the caller's - the Service Portal's and the server's own (500)
INVALID_API_CREDENTIALS_MESSAGE: str = "Invalid API credentials!"
NO_SUBSCRIPTION_MESSAGE: str = "The user has no assigned subscription!"
API_USER_NOT_FOUND_MESSAGE: str = "User not found!"
API_LEVEL_DENIED_MESSAGE: str = "No permission for this action!"
PORTAL_NOT_CONFIGURED_MESSAGE: str = "No access token found for the service portal!"
PORTAL_TIMEOUT_MESSAGE: str = "The service portal did not answer in time!"
PORTAL_REQUEST_FAILED_MESSAGE: str = "The request to the service portal failed!"
API_USER_UNREADABLE_MESSAGE: str = "The API user could not be read from the database!"
API_USER_NOT_STORED_MESSAGE: str = "The API user could not be stored in the database!"

# The Authorization schemes the header parsers tell apart, compared lower-cased. A header without a scheme reads as a
# bearer token, which is how older clients send one
BASIC_AUTH_SCHEME: str = 'basic'
BEARER_AUTH_SCHEME: str = 'bearer'

# What `handle_oc_errors` answers (always a 500) for a failure on the way to OpenCelium, by the error's arm
OC_AUTH_FAILED_MESSAGE: str = 'Authentication with OpenCelium failed!'
OC_CONNECT_TIMEOUT_MESSAGE: str = 'Connection to OpenCelium could not be established!'
OC_CONNECTION_FAILED_MESSAGE: str = "Connection refused. Please check your web server's network settings!"
OC_TIMEOUT_MESSAGE: str = 'Connecting to OpenCelium failed due to a timeout!'
OC_REQUEST_FAILED_MESSAGE: str = 'The request to OpenCelium failed!'
OC_GENERIC_ERROR_MESSAGE: str = 'An internal server error occurred!'
OC_GENERIC_ERROR_CONTEXT_MESSAGE: str = 'An internal server error occurred while {context}'

# How WSGI hands a header value over (each byte one latin-1 character), and how the bytes are read back
WSGI_HEADER_ENCODING: str = 'latin-1'
HEADER_DECODING_ERRORS: str = 'replace'

# -------------------------------------------------------------------------------------------------------------------- #

def decode_header_value(value: str) -> str:
    """
    Reads a request header's value as the UTF-8 text the client sent

    WSGI hands every header over as a str with one latin-1 character per byte, so a UTF-8 password in Basic credentials
    arrives mangled. The bytes are restored and read as UTF-8; a byte sequence that is no UTF-8 becomes U+FFFD rather
    than an error

    Args:
        value (str): The header's value as WSGI handed it over

    Returns:
        str: The value as text
    """
    return value.encode(WSGI_HEADER_ENCODING).decode(errors=HEADER_DECODING_ERRORS)


def split_authorization_header(header: str) -> tuple[str, str]:
    """
    Splits an Authorization header into its scheme and its credentials

    The one parser behind both readers of the header (`parse_authorization_header` and the API-user read of
    `verify_api_access`). The scheme is lower-cased; a value without one - no whitespace in it - is a bearer token

    Args:
        header (str): The header's value as WSGI handed it over

    Returns:
        tuple[str, str]: The scheme (lower-cased) and the credentials
    """
    value: str = decode_header_value(header)

    try:
        auth_type, auth_info = value.split(None, 1)
    except ValueError:
        return BEARER_AUTH_SCHEME, value

    return auth_type.lower(), auth_info


def user_has_right(required_right: str, request_user: CmdbUser) -> bool:
    """
    Determine whether a user holds the specified access right

    The user is the one `insert_request_user` resolved for the request - `APIBlueprint.protect` runs
    below it and hands it in, so nothing here reads the token or the user again. The right is held
    directly or through an extended (wildcard) right of the user's group. A user whose group no longer
    exists authenticates but holds no right

    A failure to READ the group is not answered here: it propagates, so a database outage is reported
    as one instead of as a missing right

    Args:
        required_right (str): The permission/right to verify
        request_user (CmdbUser): The authenticated user of the request

    Raises:
        BaseManagerInitError | GroupsManagerGetError: When the user's group could not be read, or a
            cloud user carries no database to read it from

    Returns:
        bool: True if the user's group holds the right or an extended right of it, False otherwise
    """
    # The provider binds the user's tenant database in cloud mode only - a manager given a database
    # uses it in every mode, and an on-premise user carries the model's default name
    groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    group = groups_manager.get_group(request_user.group_id)

    if group is None:
        return False

    return group.has_right(required_right) or group.has_extended_right(required_right)


def format_route_message(
        signature: inspect.Signature,
        message: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any]) -> str:
    """
    Fills a route's message template with the arguments the route was called with

    Bound to the route's signature, so a placeholder is filled whether the caller passed the value
    positionally or by keyword - the shared route bodies do the former. A template the arguments cannot
    fill is answered as it is: a broken error message must not replace the error it reports

    Args:
        signature (inspect.Signature): Signature of the route the arguments belong to
        message (str): The template, e.g. ``"while retrieving the Subnet with ID: {public_id}"``
        args (tuple[Any, ...]): The positional arguments of the call
        kwargs (dict[str, Any]): The keyword arguments of the call

    Returns:
        str: The filled message, or the template unchanged when it cannot be filled
    """
    try:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()

        return message.format(**bound.arguments)
    except (KeyError, IndexError, TypeError, ValueError):
        return message


def _keep_route_signature(wrapper: Callable[..., Any], signature: inspect.Signature) -> None:
    """
    Drops a route wrapper's ``__wrapped__`` link while keeping the route's own signature on it

    ``functools.wraps`` copies the name and docstring (the log labels read the former) and sets a
    ``__wrapped__`` link. The link is deliberately dropped: the route tests unwrap a handler to call it
    without auth, and following the link would unwrap the error mapping with it - every "an error maps
    to 400 / 500" test would then see the raw exception instead. The signature is pinned in its place,
    because ``inspect.signature`` of the wrapper is otherwise ``(*args, **kwargs)`` and an error
    decorator stacked above could no longer fill its message from the route's arguments

    Args:
        wrapper (Callable[..., Any]): The wrapper returned by a route error decorator
        signature (inspect.Signature): Signature of the function the wrapper wraps
    """
    del wrapper.__wrapped__
    wrapper.__signature__ = signature


def abort_if_too_large(err: BaseException) -> None:
    """
    Answers a write refused on MongoDB's 16 MB document limit with the one 400 every route gives

    The database layer raises a typed ``DocumentTooLargeError`` for it, and a manager wraps that in its own write
    error - so the cause is looked for in the chain rather than assumed. Anything else returns, for the caller to
    answer as it would have. Call it first in an ``except`` of a manager's insert / update error, before that arm
    reports the failure its own way

    Args:
        err (BaseException): The error the write raised

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the write failed on the document size limit
    """
    if find_cause(err, DocumentTooLargeError) is not None:
        LOGGER.warning("[abort_if_too_large] %s: %s", type(err).__name__, err)
        abort(HTTPStatus.BAD_REQUEST, DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE)


def accepts_upload(max_content_length: int, max_form_memory_size: int | None = None) -> Callable[..., Any]:
    """
    Raises the request size limits for one upload route, before anything reads its body

    Flask's ``MAX_CONTENT_LENGTH`` holds every request to the JSON-body limit; a route that takes a file raises it
    for its own request (Flask 3.1 lets a request carry its own limits). ``max_form_memory_size`` is for a route
    that receives its upload as a plain form FIELD rather than a file part - Werkzeug keeps such a field in memory
    and caps it at 500 KB by default. A larger body is still a 413, answered by Werkzeug itself

    Stack it with the parsers, below the authentication decorators: it reads nothing, so the caller is still
    identified before the body is, and it must run before the handler touches ``request.files`` / ``request.form``

    Args:
        max_content_length (int): The largest body the route accepts, in bytes
        max_form_memory_size (int | None): The largest non-file form field, in bytes. Defaults to None (Werkzeug's)

    Returns:
        Callable[..., Any]: The decorator
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request.max_content_length = max_content_length

            if max_form_memory_size is not None:
                request.max_form_memory_size = max_form_memory_size

            return func(*args, **kwargs)

        return wrapper

    return decorator


def handle_route_errors(message: str) -> Callable[..., Any]:
    """
    Owns a route's generic error tail: re-raise an HTTPException, map anything else to a 500

    Nearly every route ends in the same two arms - ``except HTTPException: raise`` so an ``abort``
    raised inside the handler keeps its own status, then ``except Exception`` logging the failure and
    aborting 500. Written out, that is ~300 copies of six lines whose only per-route content is the
    message; written here, a route says what it was doing and stops repeating how to fail

    The message is a TEMPLATE formatted with the route's own arguments (see ``format_route_message``),
    so the per-route text stays per route: ``"while retrieving the Subnet with ID: {public_id}"`` reads
    the handler's ``public_id``

    What it deliberately does NOT do is own the arms in between. A route that maps its manager's errors
    to 400s states those rules with ``handle_manager_errors``, stacked directly below this decorator so
    its aborts pass through the HTTPException arm here

    Two failures are never a 500: a write refused on MongoDB's 16 MB document limit is the caller's, and is answered
    with the shared 400 of ``abort_if_too_large``; a query the server stopped on its time budget is answered with the
    shared 503 of ``abort_if_query_too_slow``. Both are considered before the 500

    Args:
        message (str): What the route was doing, as a template over its arguments

    Returns:
        Callable[..., Any]: The decorator
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature: inspect.Signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except APP_HANDLED_DATABASE_ERRORS:
                # A TRANSIENT database failure is not an internal error: the app's error handlers answer it
                # with 423 / 503 so the caller knows to retry, and they only ever see what escapes this
                # wrapper. Claiming it here would make that a flat 500 instead. The connector's own
                # DatabaseConnectionError goes the same way: its handler tells a lost connection (503) apart
                raise
            except Exception as err:
                # A document past the size limit is the caller's, not a server fault
                abort_if_too_large(err)
                # Nor is a query that ran past its time budget
                abort_if_query_too_slow(err)

                LOGGER.error(
                    "[%s] Exception: %s. Type: %s", func.__name__, err, type(err).__name__, exc_info=True,
                )

                detail: str = format_route_message(signature, message, args, kwargs)

                abort(HTTPStatus.INTERNAL_SERVER_ERROR, f"An internal server error occured {detail}!")

        _keep_route_signature(wrapper, signature)

        return wrapper

    return decorator


def closest_listed_error_class(
        error_classes: Collection[type[Exception]],
        err: Exception) -> type[Exception] | None:
    """
    Picks the listed class a raised error belongs to, the most specific one winning

    The error's own class is looked up first, then its bases in method resolution order, so a mapping
    that lists both a base class and one of its subclasses answers the subclass with its own entry

    Args:
        error_classes (Collection[type[Exception]]): The listed error classes
        err (Exception): The raised error

    Returns:
        type[Exception] | None: The closest listed class, None when the error is none of them
    """
    for error_class in type(err).__mro__:
        if error_class in error_classes:
            return error_class

    return None


def handle_manager_errors(
        failures: dict[type[Exception], str],
        refusals: dict[type[Exception], str] | None = None) -> Callable[..., Any]:
    """
    Maps the manager errors a route names onto a 400 with that route's message

    The typed arms that sat between a route's body and its generic tail - ``except XxxManagerGetError:
    log; abort(400, "...")`` - are one table per route: an error class and what to say about it. This
    decorator holds that table, so the route states its rules without repeating how to answer them

    ``failures`` are manager operations that went wrong; they are logged as errors with the traceback.
    ``refusals`` are business rules a manager enforced (e.g. "still used by a Risk"): the request was
    understood and declined, so they are logged as warnings without a traceback. Both answer 400. The
    messages are templates over the route's arguments, filled like ``handle_route_errors``' message

    Stack it directly below ``handle_route_errors``: its aborts are HTTPExceptions, which that decorator
    hands through untouched, and every error it does not name still reaches that decorator's 500

    Before the table is consulted, a write refused on MongoDB's 16 MB document limit gets the shared 400 of
    ``abort_if_too_large``, and a query the server stopped on its time budget the shared 503 of
    ``abort_if_query_too_slow`` - the table's message for either error would read like a database failure

    Args:
        failures (dict[type[Exception], str]): Error class -> message, logged as an error
        refusals (dict[type[Exception], str] | None): Error class -> message, logged as a warning

    Raises:
        ValueError: When no error class is given at all, or one class is listed as both

    Returns:
        Callable[..., Any]: The decorator
    """
    refusals = refusals or {}

    if not failures and not refusals:
        raise ValueError("handle_manager_errors needs at least one error class to map!")

    overlap: list[str] = sorted(error_class.__name__ for error_class in set(failures) & set(refusals))

    if overlap:
        raise ValueError(f"Error classes listed as both failure and refusal: {overlap}")

    messages: dict[type[Exception], str] = {**failures, **refusals}

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature: inspect.Signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as err:
                # Whatever this route's table says about the write that failed: the size limit has one answer
                abort_if_too_large(err)
                # ... and so has a query that ran past its time budget
                abort_if_query_too_slow(err)

                error_class: type[Exception] | None = closest_listed_error_class(messages, err)

                # Not one of this route's rules: the generic tail above decides what it is
                if error_class is None:
                    raise

                if error_class in refusals:
                    LOGGER.warning("[%s] %s: %s", func.__name__, type(err).__name__, err)
                else:
                    LOGGER.error("[%s] %s: %s", func.__name__, type(err).__name__, err, exc_info=True)

                abort(
                    HTTPStatus.BAD_REQUEST,
                    format_route_message(signature, messages[error_class], args, kwargs),
                )

        _keep_route_signature(wrapper, signature)

        return wrapper

    return decorator


def handle_oc_errors(context: str = "") -> Callable[..., Any]:
    """
    Decorator that turns a failure on the way to OpenCelium into a 500 with a message saying which kind it was

    It sits outermost on every OpenCelium route. OpenCelium's transport errors reach it raw - the connector re-raises
    what `requests` raised - so the arms are `requests`' own classes, tried in this order, each a 500:

        - an HTTPException (an `abort` below) keeps its own status
        - a lost database connection, a lock timeout or the connector's own `DatabaseConnectionError`
          (`APP_HANDLED_DATABASE_ERRORS`) passes through untouched - the app's error handlers answer it, as on every
          other route
        - `AuthError` -> ``OC_AUTH_FAILED_MESSAGE``
        - `requests` ConnectTimeout -> ``OC_CONNECT_TIMEOUT_MESSAGE``. It is a ConnectionError AND a Timeout, so it
          must come before both
        - `requests` ConnectionError (SSLError and ProxyError too) -> ``OC_CONNECTION_FAILED_MESSAGE``
        - `requests` Timeout (a ReadTimeout) -> ``OC_TIMEOUT_MESSAGE``
        - any other `requests` failure - a stored URL without a scheme, too many redirects - ->
          ``OC_REQUEST_FAILED_MESSAGE``
        - anything else -> the generic message, naming `context` when given

    `requests`' ConnectionError is no subclass of Python's builtin one, so a builtin ConnectionError reaches the generic
    arm

    Args:
        context (str): What the route was doing, appended to the generic message

    Returns:
        Callable[..., Any]: The decorator
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException as http_err:
                raise http_err
            except APP_HANDLED_DATABASE_ERRORS:
                # A lost connection or a lock timeout is not OpenCelium's: the app's error handlers answer it
                raise
            except AuthError as err:
                LOGGER.error("[OC General Error] AuthError: %s", err, exc_info=True)
                abort(500, OC_AUTH_FAILED_MESSAGE)
            except requests_errors.ConnectTimeout as err:
                LOGGER.error("[OC General Error] ConnectTimeout: %s", err, exc_info=True)
                abort(500, OC_CONNECT_TIMEOUT_MESSAGE)
            except requests_errors.ConnectionError as err:
                LOGGER.error("[OC General Error] ConnectionError: %s", err, exc_info=True)
                abort(500, OC_CONNECTION_FAILED_MESSAGE)
            except requests_errors.Timeout as err:
                LOGGER.error("[OC General Error] Timeout: %s", err, exc_info=True)
                abort(500, OC_TIMEOUT_MESSAGE)
            except requests_errors.RequestException as err:
                LOGGER.error("[OC General Error] RequestException: %s. Type: %s", err, type(err), exc_info=True)
                abort(500, OC_REQUEST_FAILED_MESSAGE)
            except Exception as err:
                LOGGER.error("[OC General Error] Exception: %s. Type: %s", err, type(err), exc_info=True)
                abort(500, OC_GENERIC_ERROR_CONTEXT_MESSAGE.format(context=context) if context
                      else OC_GENERIC_ERROR_MESSAGE)
        return wrapper
    return decorator


def request_uses_basic_auth() -> bool:
    """
    Whether the current request authenticates with HTTP Basic credentials

    The scheme is matched case-insensitively: `parse_authorization_header` lowercases it before
    accepting it, so a lowercase "basic " header authenticates too

    Returns:
        bool: True if the `Authorization` header carries the Basic scheme
    """
    auth_header: str | None = request.headers.get(AUTHORIZATION_HEADER)

    return bool(auth_header) and auth_header.lower().startswith(BASIC_AUTH_HEADER_PREFIX.lower())


def request_is_cloud_basic_without_api_key() -> bool:
    """
    Whether the current request sends HTTP Basic credentials without an ``x-api-key`` in cloud mode

    Such a request has no way in: the Service Portal answers a key-less login with every subscription of the
    account and no tenant database, so there is nothing to log into. The frontend authenticates with a Bearer
    token and every documented API client sends the key, so the request is refused with its own 401 instead of
    the generic token failure

    Returns:
        bool: True in cloud mode for a Basic request carrying no ``x-api-key``
    """
    return bool(current_app.cloud_mode) and request_uses_basic_auth() and API_KEY_HEADER not in request.headers


def request_authenticates_by_api_key() -> bool:
    """
    Whether `verify_api_access`, not `insert_request_user`, authenticates the current request

    In cloud mode an `x-api-key` request with HTTP Basic credentials is checked against the Service
    Portal by `verify_api_access`, which also resolves and injects the request user. The key alone
    decides nothing: with a Bearer token the request is resolved from the token like any other

    Returns:
        bool: True for a cloud-mode request carrying an `x-api-key` header and Basic credentials
    """
    return bool(current_app.cloud_mode) and API_KEY_HEADER in request.headers and request_uses_basic_auth()


def refuse_inactive_user(user: CmdbUser) -> None:
    """
    Refuses a CmdbUser whose account is deactivated

    The one spelling of the rule, shared by the login and by every request: a user stored with
    `active: false` gets no token and cannot use one issued before. It runs only after the caller has
    authenticated - the password verified or the token decoded - so a caller without either never
    learns whether the account exists or is deactivated

    Args:
        user (CmdbUser): The authenticated user

    Raises:
        HTTPException: 401 when the account is deactivated
    """
    if not user.active:
        abort(401, USER_DEACTIVATED_MESSAGE)


def insert_request_user(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that injects the authenticated user into a route handler as `request_user`

    This decorator handles token extraction and validation from the `Authorization` header,
    retrieves the user based on the token contents, and adds the `request_user` keyword argument
    to the wrapped function. It supports both cloud and non-cloud modes

    In cloud mode, an `x-api-key` request with HTTP Basic credentials is authenticated by
    `verify_api_access` instead, which injects the request user, so it is passed through without token
    validation (see `request_authenticates_by_api_key`). An `x-api-key` next to a Bearer token is
    resolved from the token like any other request. HTTP Basic WITHOUT an `x-api-key` is refused in cloud mode
    with its own 401 (`request_is_cloud_basic_without_api_key`) - only on premise do Basic credentials log in
    here. A cloud token naming no tenant database is a 401, and one naming a tenant that failed its startup
    update a 503 (`abort_if_tenant_unavailable`)

    The token is read by `decode_authorization_token` and its user by `resolve_token_user`, each with its own
    answers; the decorator only puts the steps in order. Once the user is resolved, a deactivated account is
    refused, and then the licence gates are enforced (`license_guard.enforce_request_licenses`): the feature of a
    gated blueprint and, for HTTP Basic credentials, the REST API feature. Running them here - after
    authentication - is what keeps the licence state from a caller without valid credentials

    **Only the caller's credentials answer 401.** A server fault - key material it cannot obtain, a stored user it
    cannot read - is a 500, and a database outage or lock timeout is left to the app's error handlers (503 / 423):
    the frontend answers a 401 by logging the user out, which an outage must not do. A programming error is not
    caught

    Args:
        func (Callable): The route function to decorate

    Returns:
        Callable: The wrapped function with `request_user` injected, if authentication succeeds

    Raises:
        werkzeug.exceptions.HTTPException: 401 when the credentials do not identify a user (no header, an invalid
            token, a token without a user or - in cloud mode - without a tenant, an unknown user) or the account is
            deactivated; 403 when a feature the request needs is not licensed; 503 for a cloud tenant that failed its
            startup update; 500 when the key material cannot be obtained or the stored user cannot be read
        DocumentNetworkError: When the database server was lost while the key or the user was read - left to the
            app's error handler, which answers 503
        DocumentLockTimeoutError: When a lock timed out during those reads - answered 423
    """
    @functools.wraps(func)
    def get_request_user(*args: Any, **kwargs: Any) -> Any:
        # Outside the token read: an error raised by the route is the route's, not a token failure
        if request_authenticates_by_api_key():
            return func(*args, **kwargs)

        if request_is_cloud_basic_without_api_key():
            abort(401, CLOUD_BASIC_WITHOUT_API_KEY_MESSAGE)

        request_user: CmdbUser = resolve_token_user(decode_authorization_token())

        # Read on every request, so a deactivation takes effect on the token's next use
        refuse_inactive_user(request_user)

        # Only an authenticated caller learns whether a feature is licensed. Deferred: the routes
        # package imports this module, so a module-level import of the guard is a cycle
        # pylint: disable-next=import-outside-toplevel
        from cmdb.interface.rest_api.routes.cmdb_license.license_guard import enforce_request_licenses
        enforce_request_licenses(request_user, request_uses_basic_auth())

        return func(*args, request_user=request_user, **kwargs)

    return get_request_user


def decode_authorization_token() -> dict[str, Any]:
    """
    Reads the request's `Authorization` header and answers the claims of the token it carries

    Basic credentials are exchanged for a token first (on premise; see `parse_authorization_header`), a bearer token is
    validated. Anything that is not a valid token - an unknown scheme, failed credentials, a malformed or expired
    token - is a `TokenValidationError` by then, answered 401. A server that cannot obtain its key material is the
    500, and a database outage is left to the app's error handlers (503 / 423): neither is the caller's fault, and a
    401 would log the user out. A programming error is not caught

    Raises:
        HTTPException: 401 without a header or for an invalid token; 500 when the key material is unavailable
        DocumentNetworkError: When the database server was lost while the key was read - answered 503
        DocumentLockTimeoutError: When a lock timed out while the key was read - answered 423

    Returns:
        dict[str, Any]: The decoded JWT claims
    """
    auth_header: str | None = request.headers.get(AUTHORIZATION_HEADER)

    if not auth_header:
        abort(401, NO_AUTHORIZATION_HEADER_MESSAGE)

    try:
        return decode_request_token(parse_authorization_header(auth_header))
    except TokenKeyMaterialError as err:
        LOGGER.error("[decode_authorization_token] TokenKeyMaterialError: %s", err, exc_info=True)
        abort(500, KEY_MATERIAL_UNAVAILABLE_MESSAGE)
    except TokenValidationError:
        abort(401, INVALID_TOKEN_MESSAGE)


def resolve_token_user(claims: dict[str, Any]) -> CmdbUser:
    """
    Reads the CmdbUser a token's claims name - in the tenant the token names, in cloud mode

    A token whose claims carry no user (or one without a `public_id`, or in cloud mode without a `database`) is
    an invalid token, 401. A cloud token naming no tenant is a 401 and one naming a tenant that failed its startup
    update a 503 (`abort_if_tenant_unavailable`). A user the database does not hold is a 401; a stored user that
    cannot be read is the server's fault, 500, and a database outage is left to the app's error handlers (503 /
    423) - neither may answer 401, which would log the user out. A programming error is not caught

    Args:
        claims (dict[str, Any]): The decoded JWT claims (`decode_authorization_token`)

    Raises:
        HTTPException: 401 for claims without a usable user, a cloud token without a tenant, or an unknown user;
            503 for an unavailable tenant; 500 when the stored user cannot be read
        DocumentNetworkError: When the database server was lost during the user read - answered 503
        DocumentLockTimeoutError: When a lock timed out during the user read - answered 423

    Returns:
        CmdbUser: The user the token names
    """
    try:
        user_claim: dict[str, Any] = token_user_claim(claims)
        user_id: Any = user_claim[CmdbUserKey.PUBLIC_ID.value]
        database: str | None = user_claim[CmdbUserKey.DATABASE.value] if current_app.cloud_mode else None
    except (KeyError, TypeError):
        abort(401, INVALID_TOKEN_MESSAGE)

    if current_app.cloud_mode:
        # No tenant would bind the manager to the process-wide database - another tenant's user, or none
        if not database:
            abort(401, NO_TENANT_DATABASE_MESSAGE)

        abort_if_tenant_unavailable(database)

    try:
        user: CmdbUser | None = UsersManager(current_app.database_manager, database).get_user(user_id)
    except UsersManagerGetError as err:
        LOGGER.error("[resolve_token_user] UsersManagerGetError: %s", err, exc_info=True)
        abort(500, USER_UNREADABLE_MESSAGE)

    if not user:
        abort(401, INVALID_USER_MESSAGE)

    return user


def verify_api_access(*, required_api_level: ApiLevel | None = None) -> Callable[..., Any]:
    """
    Decorator holding the cloud API key to a route's API level

    Applies to one channel only: in cloud mode, a request with HTTP Basic credentials (and the `x-api-key` the
    portal check needs) is authenticated against the Service Portal, its user injected as `request_user`, and its
    account's level compared with `required_api_level` - all in `authenticate_api_key_request`. Everything else
    passes untouched:

    - on-premise the decorator is a no-op: the licensed REST API (HTTP Basic) reaches every route its rights allow,
      `LOCKED` ones included, and the frontend's token likewise
    - a cloud request with a Bearer token skips the level check (the frontend's channel); the token is validated by
      the route's `insert_request_user` - a route without one must refuse Bearer itself, as the setup routes do

    What a caller may do is the rights' and ACLs' to decide, not this level's (see `ApiLevel`)

    Args:
        required_api_level (ApiLevel | None): The level the cloud API key must reach for the route

    Behavior (each answer is `authenticate_api_key_request`'s):
    - credentials the portal refuses, or none it can read: 401; an account without a subscription: 401
    - an account whose tenant failed its startup update: 503, before the tenant is touched
    - the tenant holds no such user: 403; a deactivated one: 401; a key below the route's level, or a `LOCKED` route:
      403
    - the portal unreachable, timing out or not configured, or the tenant user not storable: 500
    - a database outage or lock timeout: 503 / 423 (the app's handlers); a programming error: 500

    Returns:
        Callable[..., Any]: A decorator applying the cloud API's level to the decorated function
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not current_app.cloud_mode:
                return func(*args, **kwargs)

            request_user: CmdbUser | None = authenticate_api_key_request(required_api_level)

            if request_user is not None:
                kwargs['request_user'] = request_user

            return func(*args, **kwargs)
        return wrapper

    return decorator


def authenticate_api_key_request(required_api_level: ApiLevel | None) -> CmdbUser | None:
    """
    Authenticates a cloud request on the API-key channel and holds it to the route's API level

    A Bearer request is the frontend's and is not judged here (None). HTTP Basic credentials go to the Service Portal
    (`check_api_key_credentials`); below `SUPER_ADMIN` the account's tenant user is resolved
    (`resolve_api_key_user`) - a `SUPER_ADMIN` route acts on no tenant. Then the key's level is compared with the
    route's. No catch-all: every failure answers as its own kind, and an outage reaches the app's handlers

    Args:
        required_api_level (ApiLevel | None): The level the cloud API key must reach for the route

    Raises:
        HTTPException: 400 for an Authorization header of neither scheme; 401 / 403 / 500 / 503 as listed in
            `check_api_key_credentials` and `resolve_api_key_user`; 403 when the key is below the route's level
        DocumentNetworkError: When the database server was lost - answered 503
        DocumentLockTimeoutError: When a lock timed out - answered 423

    Returns:
        CmdbUser | None: The tenant user to inject, or None (a Bearer request, or a `SUPER_ADMIN` route)
    """
    if __get_request_auth_method() != AuthMethod.BASIC:
        return None

    user_instance: dict[str, Any] = check_api_key_credentials()
    request_user: CmdbUser | None = (
        None if required_api_level == ApiLevel.SUPER_ADMIN else resolve_api_key_user(user_instance)
    )

    if not __check_api_level(user_instance, required_api_level):
        abort(403, API_LEVEL_DENIED_MESSAGE)

    return request_user


def check_api_key_credentials() -> dict[str, Any]:
    """
    Checks the request's HTTP Basic credentials and `x-api-key` with the Service Portal

    Credentials the portal refuses (or no readable credentials, or a missing key) are the caller's fault, 401 on every
    route level. A portal that is not configured, does not answer in time or fails the request is not the caller's
    fault: 500, logged. Anything else - a database outage while the user cache is read, a programming error - is not
    caught

    Raises:
        HTTPException: 401 for refused or unreadable credentials; 500 for a portal fault

    Returns:
        dict[str, Any]: The portal's user data - its subscriptions and API level
    """
    credentials: dict[str, str] | None = __get_request_api_user()

    if not credentials:
        abort(401, INVALID_API_CREDENTIALS_MESSAGE)

    try:
        user_instance: dict[str, Any] | None = check_user_in_service_portal(
            credentials[CmdbUserKey.EMAIL.value],
            credentials[CmdbUserKey.PASSWORD.value],
            __get_x_api_key(),
            api_key_required=True,
        )
    except (InvalidCloudUserError, MissingApiKeyError):
        abort(401, INVALID_API_CREDENTIALS_MESSAGE)
    except NoAccessTokenError as err:
        LOGGER.error("[check_api_key_credentials] NoAccessTokenError: %s", err)
        abort(500, PORTAL_NOT_CONFIGURED_MESSAGE)
    except RequestTimeoutError as err:
        LOGGER.error("[check_api_key_credentials] RequestTimeoutError: %s", err)
        abort(500, PORTAL_TIMEOUT_MESSAGE)
    except RequestError as err:
        LOGGER.error("[check_api_key_credentials] RequestError: %s", err)
        abort(500, PORTAL_REQUEST_FAILED_MESSAGE)

    if not user_instance:
        abort(401, INVALID_API_CREDENTIALS_MESSAGE)

    return user_instance


def resolve_api_key_user(user_instance: dict[str, Any]) -> CmdbUser:
    """
    Reads the tenant user an API-key account acts as - in its first subscription's database

    An account without a subscription (or one naming no database) is a 401, a tenant that failed its startup update
    a 503 (`abort_if_tenant_unavailable`). The tenant's copy of the user is created or brought up to date
    (`set_admin_user`) and read (`retrieve_user`); a read or a write that fails is the server's fault, 500, and a
    database outage or lock timeout passes through both as itself (the app's handlers answer 503 / 423). A tenant
    without the user is a 403, a deactivated user a 401 (`refuse_inactive_user`)

    Args:
        user_instance (dict[str, Any]): The portal's user data (`check_api_key_credentials`)

    Raises:
        HTTPException: 401 without a subscription or for a deactivated user; 503 for an unavailable tenant; 500 when
            the tenant user cannot be read or stored; 403 when the tenant holds no such user
        DocumentNetworkError: When the database server was lost - answered 503
        DocumentLockTimeoutError: When a lock timed out - answered 423

    Returns:
        CmdbUser: The tenant user
    """
    subscriptions: Any = user_instance.get(CachedUserKey.SUBSCRIPTIONS.value)
    subscription: Any = subscriptions[0] if isinstance(subscriptions, list) and subscriptions else None
    database: Any = subscription.get(CachedSubscriptionKey.DATABASE.value) if isinstance(subscription, dict) else None

    if not database:
        abort(401, NO_SUBSCRIPTION_MESSAGE)

    abort_if_tenant_unavailable(database)

    try:
        set_admin_user(user_instance, subscription)
        user_model: CmdbUser | None = retrieve_user(user_instance, database)
    except UsersManagerGetError as err:
        LOGGER.error("[resolve_api_key_user] UsersManagerGetError: %s", err, exc_info=True)
        abort(500, API_USER_UNREADABLE_MESSAGE)
    except UsersManagerInsertError as err:
        LOGGER.error("[resolve_api_key_user] UsersManagerInsertError: %s", err, exc_info=True)
        abort(500, API_USER_NOT_STORED_MESSAGE)

    if not user_model:
        abort(403, API_USER_NOT_FOUND_MESSAGE)

    # The portal accepted the credentials; this tenant's own flag still decides
    refuse_inactive_user(user_model)

    return user_model


def __get_x_api_key() -> str | None:
    """
    Retrieve the 'x-api-key' from the request headers

    Returns:
        str | None: The value of the 'x-api-key' header if present, otherwise None
    """
    x_api_key: str | None = request.headers.get(API_KEY_HEADER)

    return x_api_key


def __get_request_api_user() -> dict[str, str] | None:
    """Retrieve the API user credentials from the 'Authorization' request header

    Extracts and decodes the 'Authorization' header to obtain Basic Authentication credentials

    Returns:
        dict[str, str] | None: A dictionary containing 'email' and 'password' if authentication is Basic.
                               Returns None if the header is missing, improperly formatted, or uses an
                               unsupported authentication type
    """
    try:
        auth_type, auth_info = split_authorization_header(request.headers[AUTHORIZATION_HEADER])

        if auth_type == BASIC_AUTH_SCHEME:
            email, password = base64.b64decode(auth_info).split(b":", 1)

            return {'email': email.decode("utf-8"), 'password': password.decode("utf-8")}

        return None
    except Exception as err:
        LOGGER.error("[__get_request_api_user] User Exception: %s, Type: %s", err, type(err))
        return None


def __get_request_auth_method() -> AuthMethod | None:
    """
    Determine the authentication method from the request headers

    This function checks the 'Authorization' header to determine whether the request uses 
    Basic Authentication or JWT-based authentication

    Returns:
        AuthMethod | None: 
            - `AuthMethod.BASIC` if the 'Authorization' header starts with 'Basic '
            - `AuthMethod.JWT` if the header starts with 'Bearer '
            - Aborts the request with a 400 error if the auth method is invalid or missing
    """
    try:
        auth_header = request.headers.get('Authorization')

        if auth_header:
            if auth_header.startswith('Basic '):
                return AuthMethod.BASIC

            if auth_header.startswith('Bearer '):
                return AuthMethod.JWT

        abort(400, "Invalid auth method!")
    except Exception as err:
        LOGGER.error("[__get_request_auth_method] Exception: %s, Type: %s", err, type(err))
        abort(400, "Invalid auth method!")


def __check_api_level(
        user_instance: dict[str, Any] | None = None,
        required_api_level: ApiLevel = ApiLevel.NO_API
) -> bool:
    """
    Check if the user has the required API access level

    This function verifies whether a user has the necessary API level permissions.
    The check is only performed in cloud mode

    Args:
        user_instance (dict | None): A dictionary containing user details, including API level
        required_api_level (ApiLevel): The minimum API level required for access

    Returns:
        bool: 
            - `True` if the API level requirement is met or cloud mode is disabled
            - `False` if the user does not have the required API level or an error occurs
    """
    # Only validate in cloud mode
    if not current_app.cloud_mode:
        return True

    if not user_instance or required_api_level == ApiLevel.LOCKED:
        return False

    try:
        if required_api_level == ApiLevel.SUPER_ADMIN:
            return user_instance[CachedUserKey.API_LEVEL.value] >= required_api_level

        subscription: dict[str, Any] = user_instance[CachedUserKey.SUBSCRIPTIONS.value][0]

        return subscription[CachedSubscriptionKey.API_LEVEL.value] >= required_api_level
    except Exception as err:
        LOGGER.debug("[__check_api_level] Exception: %s, Type: %s", err, type(err))
        return False


# Per-request caches. Accepting a token costs a settings read of the RSA key document plus an RSA
# signature verification, and up to three decorators of one route each would redo the whole chain -
# a single GET costing 4 TokenValidator constructions, 4 decodes and 12 reads of the key
# document. The header parse (which for a bearer token also VALIDATES it, see _validate_bearer) and
# the decode are therefore memoised for the duration of the request
_PARSED_TOKEN_CACHE_KEY: str = 'dg_parsed_authorization_headers'
_DECODED_TOKEN_CACHE_KEY: str = 'dg_decoded_tokens'


def _request_cache(key: str) -> dict[str, Any] | None:
    """
    Returns the per-request cache under the given key, creating it on first use

    Kept on the REQUEST object, which lives exactly as long as the request. `flask.g` would too, as long as nothing
    pushes an application context of its own inside the request - and none of the decorators does

    Args:
        key (str): The request attribute holding the cache

    Returns:
        dict[str, Any] | None: The cache, or None when there is no request to scope it to (a unit
            test calling these helpers directly, or a CLI code path)
    """
    if not has_request_context():
        return None

    cache: dict[str, Any] | None = getattr(request, key, None)

    if cache is None:
        cache = {}
        setattr(request, key, cache)

    return cache


def decode_request_token(token: str | bytes) -> dict[str, Any]:
    """
    Decodes a token's claims, once per request

    The claims of one token cannot change within a request, so the decode - an RSA signature
    verification plus a key read - is done for the first decorator that asks and answered from the
    cache afterwards. Expiration is NOT checked here: `parse_authorization_header` has already run
    the full two-step validation for the token it returns (see `_validate_bearer`)

    Args:
        token (str | bytes): The encoded JWT

    Raises:
        TokenValidationError: If the token is invalid, malformed or has a bad signature
        TokenKeyMaterialError: If the public key could not be obtained (a server-side fault)

    Returns:
        dict[str, Any]: The decoded JWT claims
    """
    cache = _request_cache(_DECODED_TOKEN_CACHE_KEY)
    cache_key = token.decode('utf-8') if isinstance(token, bytes) else token

    if cache is not None and cache_key in cache:
        return cache[cache_key]

    claims = TokenValidator(current_app.database_manager).decode_token(token)

    if cache is not None:
        cache[cache_key] = claims

    return claims


def token_user_claim(claims: dict[str, Any]) -> dict[str, Any]:
    """
    Reads the acting user's data out of a token's claims

    The `DATAGERRY` claim is wrapped - `{'essential': True, 'value': {...}}` - so without this every
    consumer spells `claims['DATAGERRY']['value']['user']` by hand. See `token_constants` for why the
    wrapper exists and why it stays

    Args:
        claims (dict[str, Any]): The decoded JWT claims

    Raises:
        KeyError: If the token carries no DataGerry user payload, which the callers answer with 401

    Returns:
        dict[str, Any]: The user payload - at least its `public_id`, plus `database` in cloud mode
    """
    return claims[TokenClaim.DATAGERRY.value][TokenClaimWrapperKey.VALUE.value][TokenPayloadKey.USER.value]


def parse_authorization_header(header: str | None) -> str | None:
    """
    Parses the HTTP Auth Header to a JWT Token

    Basic credentials are authenticated (via the service portal in cloud mode) and exchanged for a
    freshly generated JWT; a bearer token is validated and returned unchanged. Anything else yields None

    Args:
        header (str | None): Authorization header of the HTTP Request
    Examples:
        request.headers['Authorization'] or something same
    Raises:
        TokenKeyMaterialError: When the key material to verify or sign a token cannot be obtained
        DocumentNetworkError: When the database server was lost while the key was read

    Returns:
        str | None: Valid JWT token, or None when the header is missing/unsupported or authentication fails
    """
    if not header:
        return None

    cache = _request_cache(_PARSED_TOKEN_CACHE_KEY)

    if cache is not None and header in cache:
        return cache[header]

    auth_type, auth_info = split_authorization_header(header)

    if auth_type == BASIC_AUTH_SCHEME:
        token = _authenticate_basic(auth_info)
    elif auth_type == BEARER_AUTH_SCHEME:
        token = _validate_bearer(auth_info)
    else:
        token = None

    if cache is not None:
        cache[header] = token

    return token


def _authenticate_basic(auth_info: str) -> str | None:
    """
    Authenticates on-premise Basic credentials and exchanges them for a freshly generated JWT

    Decodes the ``email:password`` pair, logs in through the AuthModule and returns a new JWT for the
    authenticated user. **On premise only.** In cloud mode HTTP Basic is answered by the Service Portal and
    needs an ``x-api-key`` (``verify_api_access``); ``insert_request_user`` refuses one without a key before it
    gets here (``request_is_cloud_basic_without_api_key``), and this function refuses it again rather than
    log in against a database the portal never named

    Args:
        auth_info (str): The base64-encoded ``email:password`` portion of a Basic Authorization header

    Raises:
        TokenKeyMaterialError: When the signing key could not be obtained - the server's fault, answered 500
        DocumentNetworkError: When the database server was lost while the key was read - answered 503

    Returns:
        str | None: A freshly generated JWT, or None in cloud mode, when the credentials are invalid or an
            error occurs
    """
    if current_app.cloud_mode:
        return None

    try:
        username, password = base64.b64decode(auth_info).split(b":", 1)

        username = strip_login(username.decode("utf-8"))
        password = password.decode("utf-8")

        users_manager = UsersManager(current_app.database_manager)
        security_manager = SecurityManager(current_app.database_manager)
        settings_manager = SettingsManager(current_app.database_manager)

        auth_settings = settings_manager.get_all_values_from_section('auth', AuthModule.__DEFAULT_SETTINGS__)
        auth_module = AuthModule(auth_settings,
                                 security_manager=security_manager,
                                 users_manager=users_manager)

        try:
            user_instance = auth_module.login(username, password)
        except Exception:
            return None

        if not user_instance:
            return None

        token_payload = {TokenPayloadKey.USER.value: {CmdbUserKey.PUBLIC_ID.value: user_instance.get_public_id()}}

        return TokenGenerator(current_app.database_manager).generate_token(payload=token_payload)
    except (TokenKeyMaterialError, *TRANSIENT_DATABASE_ERRORS):
        # The credentials were fine and the server could not sign for them: its fault, not a failed login -
        # answering None would make the request a 401 that logs the user out. load_key_holder has logged it
        raise
    except Exception as err:
        LOGGER.error("[_authenticate_basic] Exception: %s", err)
        return None


def _validate_bearer(auth_info: str) -> str | None:
    """
    Validates a bearer token and returns it unchanged when valid

    Args:
        auth_info (str): The bearer token from the Authorization header

    Raises:
        TokenKeyMaterialError: When the public key could not be obtained - the server's fault, answered 500
        DocumentNetworkError: When the database server was lost while the key was read - answered 503

    Returns:
        str | None: The token when it decodes and validates, otherwise None
    """
    try:
        validator = TokenValidator(current_app.database_manager)
        decoded_token = validator.decode_token(auth_info)
        validator.validate_claims(decoded_token)
        validator.validate_issuer(decoded_token, __title__)

        # The claims are what every decorator of the route is about to ask for; handing them to the
        # request cache here means the token is decoded ONCE per request instead of once per
        # decorator
        cache = _request_cache(_DECODED_TOKEN_CACHE_KEY)

        if cache is not None:
            cache[auth_info] = decoded_token

        return auth_info
    except (TokenKeyMaterialError, *TRANSIENT_DATABASE_ERRORS):
        # Not the caller's fault, and answering None here would report it as a bad token - let it
        # surface so the route can answer 500 (or 503 for an outage) instead of logging the user out.
        # load_key_holder has logged it
        raise
    except Exception as err:
        LOGGER.debug("[_validate_bearer] Token refused: %s", err)

        return None
