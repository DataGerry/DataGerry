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
Implementation of helper methods for API routes
"""
import os
import base64
import functools
import inspect
import json
from http import HTTPStatus
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any, Callable, Collection
import requests
from requests.exceptions import ConnectTimeout, Timeout, ConnectionError
from flask import request, abort, current_app, has_request_context
from werkzeug._internal import _wsgi_decoding_dance
from werkzeug.exceptions import HTTPException

from cmdb.database.database_services import CollectionValidator, DatabaseUpdater
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    UsersManager,
    GroupsManager,
    SecurityManager,
    SettingsManager,
    CachedUserManager,
)

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.login_name import normalize_login_email, strip_login
from cmdb import __title__
from cmdb.security.token.validator import TokenValidator
from cmdb.security.token.token_constants import TokenClaim, TokenClaimWrapperKey
from cmdb.security.token.generator import TokenGenerator

from cmdb.models.user_model import CmdbUser, CmdbUserKey

from cmdb.errors.security import (
    TokenValidationError,
    TokenKeyMaterialError,
    InvalidCloudUserError,
    NoAccessTokenError,
    MissingApiKeyError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE
from cmdb.utils import find_cause
from cmdb.errors.database import (
    SetDatabaseError,
    DocumentNetworkError,
    DocumentLockTimeoutError,
    DocumentTooLargeError,
    TRANSIENT_DATABASE_ERRORS,
)
from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.open_celium import AuthError
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

# -------------------------------------------------------------------------------------------------------------------- #

def get_cached_user_manager() -> CachedUserManager:
    """
    Builds a CachedUserManager for the process-wide cloud user cache

    **Why this is not `ManagerProvider.get_manager`.** Every other manager is resolved there, and this
    one deliberately is not: the cache does not live in a tenant's database. `CachedUserManager`
    ignores the database argument entirely - its collection is always `DG_CACHE_DB` - so the tenant
    name `ManagerProvider` would pass is discarded, and `get_manager` REQUIRES a request_user in cloud
    mode, which the login path (`validate_with_service_portal`) cannot supply: nobody is authenticated
    yet. That is why `ManagerType` carries no entry for it

    Called from the login path, the /setup routes and the OpenCelium routes; keeping it in one place
    makes a change to how the cache is reached one edit rather than one per caller

    Returns:
        CachedUserManager: A manager bound to this process' database handle and the cache database
    """
    return CachedUserManager(current_app.database_manager)


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


def handle_db_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Maps the two transient database errors onto statuses that tell a caller to retry

    Catches:
        - DocumentNetworkError -> 503 Service Unavailable
        - DocumentLockTimeoutError -> 423 Locked

    **It only sees what escapes the view**, being the outermost decorator. A route ending in
    `except Exception: abort(500, ...)`, or a manager re-wrapping the raw errors into its own type,
    makes it inert: neither status is ever emitted and a lock timeout is reported as an internal
    server error. Both layers therefore re-raise these two unchanged

    So a route decorated with this **must not** swallow them in a blanket `except Exception` of its
    own; if it does, the decorator silently does nothing and the failure looks like a server fault
    rather than a retryable one
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except DocumentNetworkError as err:
            LOGGER.error("[DB Network Error] %s: %s", type(err), err, exc_info=True)
            abort(503, "Database connection issue. Please try again!")
        except DocumentLockTimeoutError as err:
            LOGGER.error("[DB Lock Timeout] %s: %s", type(err), err, exc_info=True)
            abort(423, "Database collection currently in use. Please try again!")

    return wrapper


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

    One failure is never a 500: a write refused on MongoDB's 16 MB document limit is the caller's, and is answered
    with the shared 400 of ``abort_if_too_large`` before the 500 is considered

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
            except TRANSIENT_DATABASE_ERRORS:
                # A TRANSIENT database failure is not an internal error: `@handle_db_errors` maps it to
                # 423 / 503 so the caller knows to retry, and it only ever sees what escapes this
                # wrapper. Claiming it here would make that a flat 500 instead
                raise
            except Exception as err:
                # A document past the size limit is the caller's, not a server fault
                abort_if_too_large(err)

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
    ``abort_if_too_large`` - the table's message for the write's error would read like a database failure

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
    Decorator to catch OpenCelium-related errors and return proper HTTP responses

    Args:
        context (str): Extra description for generic exceptions,
                       appended to the default message prefix
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException as http_err:
                raise http_err
            except AuthError as err:
                LOGGER.error("[OC General Error] AuthError: %s", err, exc_info=True)
                abort(500, "Authentication with OpenCelium failed!")
            except ConnectTimeout as err:
                LOGGER.error("[OC General Error] ConnectTimeout: %s", err, exc_info=True)
                abort(500, "Connection to OpenCelium could not be established!")
            except ConnectionError as err:
                LOGGER.error("[OC General Error] ConnectionError: %s", err, exc_info=True)
                abort(500,
                      "Connection refused. Please check your web server's network settings!"
                )
            except Timeout as err:
                LOGGER.error("[OC General Error] Timeout: %s", err, exc_info=True)
                abort(500, "Connecting to OpenCelium failed due to a timeout!")
            except Exception as err:
                LOGGER.error("[OC General Error] Exception: %s. Type: %s", err, type(err), exc_info=True)
                message = f"An internal server error occurred while {context}" if context\
                                else "An internal server error occurred!"
                abort(500, message)
        return wrapper
    return decorator


def parse_assistant_parameters(**optional: Any) -> Callable[..., Any]:  # pylint: disable=unused-argument
    # '**optional' is an extensibility placeholder, matching the other parameter decorators
    """
    Decorator to parse and extract query parameters from an HTTP request

    Returns a decorator that:
    - Extracts query parameters from the current request (via `request.args.to_dict()`)
    - Injects them as the FIRST positional argument of the decorated function
    - Forwards any remaining positional/keyword arguments (e.g. the `request_user` the
      authentication decorators above it injected) unchanged

    Like every parser it sits BELOW the authentication decorators, so it reads the request of a
    caller who has already been identified

    Used only by the DataGerry assistant route. It is a plain request decorator like the others here,
    so it lives with them rather than on a blueprint type

    Args:
        **optional (Any): Placeholder for optional keyword arguments (currently unused)

    Returns:
        Callable: A decorator that injects parsed request parameters into the decorated function
    """
    def _parse(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def _decorate(*args: Any, **kwargs: Any) -> Any:
            # `to_dict` cannot raise: Werkzeug has already parsed the query string by the time a view
            # runs, and it tolerates duplicate keys and embedded null bytes. A try/except around this
            # - and a 400 for it - could therefore never fire
            location_args = request.args.to_dict()

            return func(location_args, *args, **kwargs)

        return _decorate

    return _parse


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
    resolved from the token like any other request

    Once the user is resolved, a deactivated account is refused, and then the licence gates are
    enforced (`license_guard.enforce_request_licenses`): the feature of a gated blueprint and, for
    HTTP Basic credentials, the REST API feature. Running them here - after authentication - is what
    keeps the licence state from a caller without valid credentials

    Args:
        func (Callable): The route function to decorate

    Returns:
        Callable: The wrapped function with `request_user` injected, if authentication succeeds

    Raises:
        werkzeug.exceptions.HTTPException: Returns a 401 Unauthorized error if token validation fails
                                           or the user cannot be resolved, and a 403 when a feature
                                           the request needs is not licensed.
    """
    @functools.wraps(func)
    def get_request_user(*args: Any, **kwargs: Any) -> Any:
        with current_app.app_context():
            users_manager: UsersManager = UsersManager(current_app.database_manager)
        # Outside the try below: an error raised by the route is the route's, not a token failure
        if request_authenticates_by_api_key():
            return func(*args, **kwargs)

        try:
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                abort(401, "No Authorization header provided!")

            token = parse_authorization_header(auth_header)

            with current_app.app_context():
                decrypted_token = decode_request_token(token)
        except HTTPException as http_err:
            raise http_err
        except TokenKeyMaterialError as err:
            LOGGER.error("[insert_request_user] TokenKeyMaterialError: %s", err, exc_info=True)
            abort(500, "The token could not be verified because of a server-side key problem!")
        except TokenValidationError:
            abort(401, "Invalid Token!")
        except Exception as err:
            LOGGER.debug("[insert_request_user] Exception: %s, Type: %s", err, type(err), exc_info=True)
            abort(401, "Token could not be validated!")

        try:
            user_claim = token_user_claim(decrypted_token)
            user_id = user_claim['public_id']

            if current_app.cloud_mode:
                database = user_claim['database']
                users_manager = UsersManager(current_app.database_manager, database)

            user = users_manager.get_user(user_id)

            if user:
                kwargs.update({'request_user': user})
            else:
                abort(401, "Invalid user!")
        except HTTPException as http_err:
            raise http_err
        except ValueError:
            abort(401)
        except Exception as err:
            LOGGER.error("[insert_request_user] User Exception: %s, Type: %s", err, type(err))
            abort(401)

        # Read on every request, so a deactivation takes effect on the token's next use
        refuse_inactive_user(kwargs['request_user'])

        # Only an authenticated caller learns whether a feature is licensed. Deferred: the routes
        # package imports this module, so a module-level import of the guard is a cycle
        # pylint: disable-next=import-outside-toplevel
        from cmdb.interface.rest_api.routes.cmdb_license.license_guard import enforce_request_licenses
        enforce_request_licenses(kwargs['request_user'], request_uses_basic_auth())

        return func(*args, **kwargs)

    return get_request_user


def verify_api_access(*, required_api_level: ApiLevel | None = None) -> Callable[..., Any]:
    """
    Decorator to verify API access based on authentication method and required API level

    Args:
        required_api_level (ApiLevel | None): Minimum API access level required to execute the decorated function
    
    Behavior:
    - If the user does not meet the required API level, the request is aborted with a 403 status
    - If authentication fails or an error occurs, the request is aborted with a 400 status

    Returns:
        Callable[..., Any]: A decorator applying API access control to the decorated function
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not current_app.cloud_mode:
                return func(*args, **kwargs)

            try:
                auth_method = __get_request_auth_method()
                api_user_dict = __get_request_api_user()
                x_api_key = __get_x_api_key()

                if auth_method == AuthMethod.BASIC:
                    user_instance = check_user_in_service_portal(
                                                                api_user_dict['email'],
                                                                api_user_dict['password'],
                                                                x_api_key,
                                                                api_key_required=True
                                                           )

                    # Set the user as request User
                    if required_api_level != ApiLevel.SUPER_ADMIN:
                        set_admin_user(user_instance, user_instance['subscriptions'][0])
                        user_model = retrieve_user(user_instance, user_instance['subscriptions'][0]['database'])

                        if not user_model:
                            abort(403, "User not found!")

                        # The portal accepted the credentials; this tenant's own flag still decides
                        refuse_inactive_user(user_model)
                        kwargs.update({'request_user': user_model})

                    if not __check_api_level(user_instance, required_api_level):
                        abort(403, "No permission for this action!")
            except HTTPException as http_err:
                raise http_err
            except Exception as err:
                LOGGER.error("[verify_api_access] Exception: %s. Type: %s", err, type(err), exc_info=True)
                abort(400, "Failed to verify API access!")

            return func(*args, **kwargs)
        return wrapper

    return decorator


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
        value: str = _wsgi_decoding_dance(request.headers['Authorization'])

        try:
            auth_type, auth_info = value.split(None, 1)
            auth_type = auth_type.lower()
        except ValueError:
            auth_type = "bearer"
            auth_info = value

        if auth_type == "basic":
            email, password = base64.b64decode(auth_info).split(b":", 1)

            with current_app.app_context():
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
            return user_instance['api_level'] >= required_api_level

        return user_instance['subscriptions'][0]['api_level'] >= required_api_level
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

    Kept on the REQUEST object rather than on `flask.g`: `g` is bound to the application context,
    and two of the three decorators push one of their own around the decode - so a `g`-based cache
    would be thrown away with that inner context and never hit

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
    return claims[TokenClaim.DATAGERRY.value][TokenClaimWrapperKey.VALUE.value]['user']


def parse_authorization_header(header: str | None) -> str | None:
    """
    Parses the HTTP Auth Header to a JWT Token

    Basic credentials are authenticated (via the service portal in cloud mode) and exchanged for a
    freshly generated JWT; a bearer token is validated and returned unchanged. Anything else yields None

    Args:
        header (str | None): Authorization header of the HTTP Request
    Examples:
        request.headers['Authorization'] or something same
    Returns:
        str | None: Valid JWT token, or None when the header is missing/unsupported or authentication fails
    """
    if not header:
        return None

    cache = _request_cache(_PARSED_TOKEN_CACHE_KEY)

    if cache is not None and header in cache:
        return cache[header]

    value = _wsgi_decoding_dance(header)

    try:
        auth_type, auth_info = value.split(None, 1)
        auth_type = auth_type.lower()
    except ValueError:
        # Fallback for old versions
        auth_type = "bearer"
        auth_info = value

    if auth_type == "basic":
        token = _authenticate_basic(auth_info)
    elif auth_type == "bearer":
        token = _validate_bearer(auth_info)
    else:
        token = None

    if cache is not None:
        cache[header] = token

    return token


def _authenticate_basic(auth_info: str) -> str | None:
    """
    Authenticates Basic credentials and exchanges them for a freshly generated JWT

    Decodes the ``email:password`` pair, resolves the target database (via the service portal in
    cloud mode), logs in through the AuthModule and returns a new JWT for the authenticated user. In
    cloud mode the AuthModule is given the email the portal answered with, so a login typed in another
    case finds the tenant user it belongs to

    Args:
        auth_info (str): The base64-encoded ``email:password`` portion of a Basic Authorization header

    Returns:
        str | None: A freshly generated JWT, or None when the credentials are invalid or an error occurs
    """
    try:
        username, password = base64.b64decode(auth_info).split(b":", 1)

        with current_app.app_context():
            username = strip_login(username.decode("utf-8"))
            password = password.decode("utf-8")

            db_name = None
            if current_app.cloud_mode:
                user_data = check_user_in_service_portal(username, password)

                if not user_data:
                    return None

                # The tenant user is stored under the address the portal answers with, whatever spelling
                # the caller typed - the login route and the x-api-key path look it up the same way
                username = user_data.get(CmdbUserKey.EMAIL.value) or username

                if current_app.local_mode:
                    # Test API only with user with 1 subscription
                    db_name = user_data['subscriptions'][0]['database']
                else:
                    db_name = user_data['database']

            users_manager = UsersManager(current_app.database_manager, db_name)
            security_manager = SecurityManager(current_app.database_manager, db_name)
            settings_manager = SettingsManager(current_app.database_manager, db_name)

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

            token_payload = {'user': {'public_id': user_instance.get_public_id()}}

            if current_app.cloud_mode:
                token_payload['user']['database'] = user_instance.database

            # The token lifetime is the tenant's own setting: db_name is the tenant database in cloud mode
            return TokenGenerator(current_app.database_manager, db_name).generate_token(payload=token_payload)
    except SetDatabaseError as err:
        LOGGER.error("[_authenticate_basic] SetDatabaseError: %s", err)
        return None
    except Exception as err:
        LOGGER.error("[_authenticate_basic] Exception: %s", err)
        return None


def _validate_bearer(auth_info: str) -> str | None:
    """
    Validates a bearer token and returns it unchanged when valid

    Args:
        auth_info (str): The bearer token from the Authorization header

    Returns:
        str | None: The token when it decodes and validates, otherwise None
    """
    try:
        with current_app.app_context():
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
    except TokenKeyMaterialError as err:
        # Not the caller's fault, and answering None here would report it as a bad token - let it
        # surface so the route can answer 500 instead of logging the user out
        LOGGER.error("[_validate_bearer] TokenKeyMaterialError: %s", err, exc_info=True)
        raise
    except Exception as err:
        LOGGER.debug("[_validate_bearer] Token refused: %s", err)

        return None

# ------------------------------------------------------ HELPER ------------------------------------------------------ #

def check_user_in_service_portal(
    email: str,
    password: str,
    x_api_key: str | None = None,
    api_key_required: bool = False
) -> dict[str, Any] | None:
    """Check if a user exists in the service portal

    The email is normalised first (stripped and lower-cased), whatever spelling the caller submitted.
    This function verifies user credentials in two modes:
    - **Local mode**: Loads test users from a JSON file and verifies credentials
    - **Cloud mode**: Validates user credentials via the service portal

    Args:
        email (str): The user's email address
        password (str): The user's password
        x_api_key (str | None): API key for authentication. Defaults to None
        api_key_required (bool): When True, the request is rejected unless an ``x_api_key`` is supplied

    Raises:
        NoAccessTokenError: If the service portal authentication fails due to a missing access token
        InvalidCloudUserError: If the user is invalid in the cloud authentication system
        RequestTimeoutError: If the authentication request times out
        RequestError: For general request failures
        Exception: For any other unexpected errors

    Returns:
        dict | None: A dictionary representing the user if authentication is successful, otherwise None
    """
    # Every cloud entry point funnels through here, so the portal and the user cache always see the
    # same spelling of one address - see cmdb.security.auth.login_name
    email = normalize_login_email(email)

    if current_app.local_mode:
        return _load_local_test_user(email, password)

    # Validation through service portal
    try:
        # Early out if no api_key is provided when it is required
        if api_key_required and not x_api_key:
            return None

        cached_user_manager: CachedUserManager = get_cached_user_manager()
        security_manager = SecurityManager(current_app.database_manager)

        user_exists_in_cache = cached_user_manager.cached_user_exists(email)
        # 1. Check cache first
        if user_exists_in_cache:
            cached_user: dict[str, Any] | None = cached_user_manager.get_validated_user_data(
                                                                    email,
                                                                    security_manager.generate_hmac(password),
                                                                    x_api_key,
                                                                    api_key_required
                                                                )

            if cached_user:
                return cached_user

        # 2. Not cached or invalid data → validate against portal, then sync the cache
        user_data: dict[str, Any] = validate_subscription_user(email, password, x_api_key, api_key_required)

        if user_data:
            user_data["password"] = security_manager.generate_hmac(user_data["password"])

            if api_key_required and x_api_key:
                _sync_api_cached_user(
                    cached_user_manager, security_manager, email, password, x_api_key,
                    user_data, user_exists_in_cache
                )
            else:
                _sync_frontend_cached_user(cached_user_manager, email, user_data, user_exists_in_cache)

        return user_data
    except (NoAccessTokenError, MissingApiKeyError, InvalidCloudUserError, RequestTimeoutError, RequestError) as err:
        raise err from err
    except Exception as err:
        #TODO: ERROR-FIX (proper exception required)
        raise Exception(err) from err


def _load_local_test_user(email: str, password: str) -> dict[str, Any] | None:
    """
    Validates credentials against the local ``etc/test_users.json`` fixture (local mode only)

    Args:
        email (str): The user's email address (key into the fixture)
        password (str): The user's password to match

    Returns:
        dict[str, Any] | None: The matching test user, or None when unknown / wrong password / on error
    """
    try:
        with open('etc/test_users.json', 'r', encoding='utf-8') as users_file:
            users_data = json.load(users_file)

        user = users_data.get(email)

        if user and user["password"] == password:
            return user

        return None
    except Exception as err:
        LOGGER.debug("[_load_local_test_user] Exception: %s, Type: %s", err, type(err))
        return None


def _sync_api_cached_user(
    cached_user_manager: CachedUserManager,
    security_manager: SecurityManager,
    email: str,
    password: str,
    x_api_key: str,
    user_data: dict[str, Any],
    user_exists_in_cache: bool,
) -> None:
    """
    Syncs the cached user for an external-API (x-api-key) login

    The portal returns a single subscription for an API login. An already-cached user just gets the
    api_key stamped onto the matching subscription; an uncached user is only created when its database
    exists, and then from the FULL subscription list (a second portal call) with the api_key applied.
    The password of a newly cached user is HMAC-hashed before storage so it matches what
    `CachedUserManager.get_validated_user_data` compares against (which hashes the login password) -
    otherwise the cached entry never validates and every request falls back to the portal.

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        security_manager (SecurityManager): Used to HMAC the password before it is cached
        email (str): The user's email
        password (str): The user's (plain) password, for the full-subscription portal call
        x_api_key (str): The API key to associate with the matching subscription
        user_data (dict[str, Any]): The single-subscription user data from the portal
        user_exists_in_cache (bool): Whether the user is already cached
    """
    target_db = user_data['subscriptions'][0]['database']

    if user_exists_in_cache:
        # A cached entry whose password is the current HMAC only lacked this api_key (frontend-first
        # then API case) - just stamp the key. Otherwise the entry is stale (e.g. a plaintext password
        # rather than its HMAC), so drop it and fall through to recreate it correctly.
        if _cached_password_is_current(cached_user_manager, security_manager, email, password):
            cached_user_manager.update_cached_user_api_key(email, target_db, x_api_key)
            return

        cached_user_manager.delete_cached_user(email)

    # Only create if the user's database exists
    if not check_db_exists(target_db):
        return

    # External API returns one subscription, so re-fetch the full subscription list to cache
    full_user_data: dict[str, Any] = validate_subscription_user(email, password)

    if full_user_data:
        # Store the password as its HMAC (the cache validation hashes the login password to compare)
        full_user_data["password"] = security_manager.generate_hmac(full_user_data["password"])

        for sub in full_user_data["subscriptions"]:
            if sub["database"] == target_db:
                sub["api_key"] = x_api_key
                break

        cached_user_manager.insert_cached_user(full_user_data)


def _cached_password_is_current(
    cached_user_manager: CachedUserManager,
    security_manager: SecurityManager,
    email: str,
    password: str,
) -> bool:
    """
    Reports whether the cached user's stored password is the current HMAC of the login password

    Used to distinguish a still-valid cached entry (only missing an api_key) from a stale one that must
    be rewritten - e.g. an entry still holding a plaintext password rather than its HMAC.

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        security_manager (SecurityManager): Used to HMAC the login password for comparison
        email (str): The user's email
        password (str): The (plain) login password to hash and compare

    Returns:
        bool: True if a cached entry exists and its stored password equals the HMAC of the login password
    """
    cached_user = cached_user_manager.get_cached_user(email)

    return bool(cached_user) and cached_user.get("password") == security_manager.generate_hmac(password)


def _sync_frontend_cached_user(
    cached_user_manager: CachedUserManager,
    email: str,
    user_data: dict[str, Any],
    user_exists_in_cache: bool,
) -> None:
    """
    Syncs the cached user for a frontend login (all subscriptions cached)

    A new user is cached as-is; an existing cached user is refreshed with the fresh subscription data,
    restoring any api_key that was previously stored for a given database

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        email (str): The user's email
        user_data (dict[str, Any]): The full (all-subscriptions) user data from the portal
        user_exists_in_cache (bool): Whether the user is already cached
    """
    if not user_exists_in_cache:
        cached_user_manager.insert_cached_user(user_data)
        return

    cached_user = cached_user_manager.get_cached_user(email)

    if not cached_user:
        return

    # Restore any previously-cached api_key onto the matching fresh subscription
    cached_api_keys: dict[Any, Any] = {
        sub["database"]: sub.get("api_key")
        for sub in cached_user.get("subscriptions", [])
        if sub.get("api_key")
    }

    for sub in user_data["subscriptions"]:
        if sub["database"] in cached_api_keys:
            sub["api_key"] = cached_api_keys[sub["database"]]

    cached_user_manager.update_cached_user(email, user_data)


def check_db_exists(db_name: str) -> bool:
    """
    This function checks if a given database name exists within the current database manager

    Args:
        db_name (str): The name of the database to check

    Returns:
        bool: True if the database exists, False otherwise
    """
    return current_app.database_manager.check_database_exists(db_name)


def init_db_routine(db_name: str) -> None:
    """
    Creates a database with the given name and all corresponding collections

    Args:
        db_name (str): Name of the database
    """
    # Initialise the database
    collection_validator = CollectionValidator(db_name, current_app.database_manager)
    collection_validator.validate_collections()

    # Sets the update version to the newest version
    database_updater = DatabaseUpdater(current_app.database_manager, db_name)
    database_updater.set_update_version(database_updater.get_highest_update_version())


def set_admin_user(user_data: dict[str, Any], subscription: dict[str, Any]) -> None:
    """
    Ensures an admin user exists for a subscription's database (cloud mode)

    Creates the admin user in the subscription's database when it is missing; otherwise updates the
    existing user's database, api_level and config_items_limit from the subscription. Both numbers
    are converted with int() once, before either branch, so a created and an updated user store the
    same type - a string limit on the user would make every later limit check fail with a TypeError

    Args:
        user_data (dict[str, Any]): The portal user data (email, user_name, password)
        subscription (dict[str, Any]): The subscription providing database, api_level and config_item_limit

    Raises:
        UsersManagerGetError: If reading the existing user fails
        UsersManagerInsertError: If creating/updating the admin user fails, including a subscription
            whose api_level or config_item_limit is not a number
    """
    with current_app.app_context():
        users_manager = UsersManager(current_app.database_manager, subscription['database'])
        scm = SecurityManager(current_app.database_manager, subscription['database'])

    try:
        api_level: int = int(subscription['api_level'])
        config_items_limit: int = int(subscription['config_item_limit'])
        admin_user_from_db = None

        try:
            admin_user_from_db = users_manager.get_user_by(
                {CmdbUserKey.EMAIL.value: user_data[CmdbUserKey.EMAIL.value]}
            )
        except UsersManagerGetError:
            pass

        if not admin_user_from_db:
            admin_user = CmdbUser(
                public_id = users_manager.get_next_public_id(inc_id=True),
                user_name = user_data['user_name'],
                email = user_data[CmdbUserKey.EMAIL.value],
                database = subscription['database'],
                active = True,
                api_level = api_level,
                config_items_limit = config_items_limit,
                group_id = 1,
                registration_time = datetime.now(timezone.utc),
                password = scm.generate_hmac(user_data['password']),
            )

            users_manager.insert_user(admin_user)
        else: # Update the database, api-level and config_items_limit of user
            admin_user_from_db.api_level = api_level
            admin_user_from_db.database = subscription['database']
            admin_user_from_db.config_items_limit = config_items_limit

            users_manager.update_user(admin_user_from_db.get_public_id(), admin_user_from_db)

    except UsersManagerGetError as err:
        raise UsersManagerGetError(err) from err
    except Exception as err:
        LOGGER.debug("[set_admin_user] Exception: %s, Type: %s", err, type(err))
        raise UsersManagerInsertError(err) from err


def retrieve_user(user_data: dict[str, Any], database: str) -> CmdbUser | None:
    """
    Retrieve a user from the database by email

    This function fetches a user from the database using the provided email from the user data

    Args:
        user_data (dict[str, str]): A dictionary containing user information (e.g., email)
        database (str): The name of the database to query

    Returns:
        CmdbUser | None: The matching user if found, or None if it does not exist / an error occurs
    """
    with current_app.app_context():
        users_manager = UsersManager(current_app.database_manager, database)

    try:
        return users_manager.get_user_by({CmdbUserKey.EMAIL.value: user_data[CmdbUserKey.EMAIL.value]})
    except UsersManagerGetError as err:
        LOGGER.debug("[retrieve_user] Exception: %s, Type: %s", err, type(err))
        return None


def validate_subscription_user(
    email: str,
    password: str,
    x_api_key: str | None = None,
    api_key_required: bool = False
) -> dict[str , Any]:
    """
    Validates user credentials against the DataGerry service portal

    Posts the credentials (and optionally the API key) to the portal's auth endpoint and returns the
    portal's user payload on success. The endpoint switches to ``/datagerry/auth/subscription`` when an
    ``x_api_key`` is supplied

    Args:
        email (str): The user's email address
        password (str): The user's password
        x_api_key (str | None): API key for a subscription-scoped login. Defaults to None
        api_key_required (bool): When True, the request is rejected unless an ``x_api_key`` is supplied

    Raises:
        MissingApiKeyError: If an API key is required but not provided
        NoAccessTokenError: If the ``X-ACCESS-TOKEN`` env var is not set
        RequestError: If no portal URL is configured or the request fails
        RequestTimeoutError: If the portal request times out
        InvalidCloudUserError: If the portal rejects the credentials

    Returns:
        dict[str, Any]: The portal's user payload on successful authentication
    """
    if api_key_required and not x_api_key:
        raise MissingApiKeyError("No API-KEY provided!")

    x_access_token: str | None = os.getenv("X-ACCESS-TOKEN")

    if not x_access_token:
        raise NoAccessTokenError("No x-access-token provided!")

    headers: dict[str, str] = {
        "x-access-token": x_access_token
    }

    base_url: str | None = os.getenv("DG_SP_BASE_URL")
    target: str = f"{base_url}/datagerry/auth"

    payload: dict[str, str] = {
        "email": email,
        "password": password
    }

    if x_api_key:
        payload['x-api-key'] = x_api_key

        target: str = f"{base_url}/datagerry/auth/subscription"

    try:
        response = requests.post(target, headers=headers, json=payload, timeout=3)

        if response.status_code == 200:
            return response.json()

        try:
            err_msg = response.json().get("message", response.text)
        except ValueError:
            err_msg: str = response.text
        raise InvalidCloudUserError(err_msg)
    except requests.exceptions.Timeout as err:
        raise RequestTimeoutError(err) from err
    except requests.exceptions.RequestException as err:
        raise RequestError(err) from err
