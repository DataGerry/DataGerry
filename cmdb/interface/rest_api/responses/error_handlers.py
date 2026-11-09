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
The REST API's single error handler: every failure answers the same JSON envelope

**One handler for every status, rather than one per status.** Registering statuses individually would
leave anything outside the list falling through to Flask's HTML page - which breaks the envelope the
Angular client reads (`err?.error?.message`) for any status nobody thought of. That is not
hypothetical: **415 is reachable without any route raising it**, because Werkzeug raises it while
parsing the request, before any route runs and therefore out of reach of any `abort()` census.

Registering the `HTTPException` **class** covers the whole family at once, including the statuses a
future route invents, and including an unhandled non-HTTP exception - Flask converts one to
`InternalServerError`, which is an `HTTPException`, so it lands here as a 500 too.

**The envelope** is `{description, message, response, status}`. The `description` is the Werkzeug
class's default text and the `response` prefix is that class's `name`; both are read off the exception
rather than spelled out per status, so there is nothing to keep in sync

**The status' own headers are kept.** An exception carries the headers its status needs - a 405 names the
methods the route takes in `Allow`, a 429 or 503 may say when to come back in `Retry-After`, a 401 how to
authenticate in `WWW-Authenticate`. The envelope replaces only the body, so every one of them is copied onto the
JSON response except `Content-Type`, which describes Werkzeug's HTML page and is the JSON body's own. **The body
is always the envelope**: an exception that carries a ready-made response of its own (`abort(Response)`) still
answers the envelope, because the frontend reads `message` off every failure

**Two database errors get a status of their own** (`database_unavailable`, `database_locked`). A lost connection
(`DocumentNetworkError`) is a **503** and a lock timeout (`DocumentLockTimeoutError`) a **423**: both are "try again",
not a server fault. They are registered for the app, so every route answers them the same way - the shared route tail
`handle_route_errors` re-raises them for exactly this - and they answer the same envelope as every other failure

Note this is the REST API's contract only. The SPA host (`interface/net_app`) registers a 404 of its
own that serves the Angular entry point, and must keep it - that app answers HTML on purpose
"""
from collections.abc import Iterable
from logging import Logger, getLogger
from typing import Any

from flask import Response, request, jsonify
from werkzeug.exceptions import HTTPException, InternalServerError, Locked, ServiceUnavailable

from cmdb.database.mongo_error_helper import is_lost_connection
from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Status used when an HTTPException carries no code of its own (the base class does not)
FALLBACK_STATUS: int = InternalServerError.code

#: The message of the 503 a lost database connection answers
DATABASE_UNAVAILABLE_MSG: str = "Database connection issue. Please try again!"
#: The message of the 423 a database lock timeout answers
DATABASE_LOCKED_MSG: str = "Database collection currently in use. Please try again!"

# The 500 of a database operation that failed for a reason other than a lost connection - nothing to retry
DATABASE_OPERATION_FAILED_MSG: str = "A database operation failed!"

#: The one header of an exception that is not carried over: it describes Werkzeug's HTML page, not the JSON body
REPLACED_HEADER: str = 'Content-Type'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ErrorResponse - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ErrorResponse:
    """
    The JSON body every failed REST request answers with

    Four keys, and they are frontend contract - the Angular error interceptor reads `message` off
    this body, so a response that is not shaped like this surfaces as an empty toast:

        `status`      the HTTP status code
        `response`    the status name and the requested URL, for a human reading a log
        `description` the generic meaning of the status (Werkzeug's text for that class)
        `message`     what this particular failure was, i.e. what `abort(..., "…")` was given
    """

    def __init__(self, status: int, prefix: str, description: str, message: str) -> None:
        """
        Initializes the ErrorResponse

        Args:
            status (int): The HTTP status code to answer with
            prefix (str): The status name, e.g. 'Not Found'; prepended to the request URL
            description (str): The generic meaning of the status
            message (str): The specific failure, as passed to `abort`
        """
        self.status: int = status
        self.response: str = f'{prefix}: {request.url}'
        self.description: str = description
        self.message: str = self._validate_message(message, description) or ''


    @staticmethod
    def _validate_message(message: Any, description: str) -> str | None:
        """
        Drops the message when it only repeats the description

        An `abort(404)` with no text of its own carries the class default as its description, so
        without this the body would state the same sentence twice under two keys

        Args:
            message (Any): The specific failure text, or the class default when none was given
            description (str): The generic meaning of the status

        Returns:
            str | None: The message, or None when it adds nothing
        """
        if message != description:
            return message

        return None


    def make_error(self, headers: Iterable[tuple[str, str]] = ()) -> Response:
        """
        Renders the envelope as a Flask response carrying the status and the status' own headers

        Args:
            headers (Iterable[tuple[str, str]]): Headers the answered exception carries (``carried_headers``), set
                on the response as they are, a repeated header repeated. Defaults to none

        Returns:
            Response: The JSON body with its HTTP status code and the given headers set
        """
        response: Response = jsonify(self.__dict__)
        response.status_code = self.status

        # Added, not assigned: a status may repeat a header (several WWW-Authenticate challenges)
        for name, value in headers:
            response.headers.add(name, value)

        return response


def carried_headers(error: HTTPException) -> list[tuple[str, str]]:
    """
    Lists the headers an HTTPException carries for its status, without the one the JSON body replaces

    Werkzeug builds them for its own HTML page: ``Content-Type`` plus whatever the status needs (``Allow`` on a 405,
    ``Retry-After``, ``WWW-Authenticate``). Everything but ``Content-Type`` belongs to the status, not to the page

    Args:
        error (HTTPException): The exception being answered

    Returns:
        list[tuple[str, str]]: Its headers in order, ``Content-Type`` left out (compared case-insensitively)
    """
    replaced: str = REPLACED_HEADER.lower()

    return [(name, value) for name, value in error.get_headers(request.environ) if name.lower() != replaced]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    THE HANDLER                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def http_exception(error: HTTPException) -> Response:
    """
    Answers any HTTPException with the REST API's JSON envelope

    Registered for the `HTTPException` **class**, so it covers every status - the ones the route
    layer aborts, the ones Werkzeug raises while parsing a request (415, 413, 414 …), and the ones a
    future route invents. Flask also routes an unhandled non-HTTP exception here, having converted
    it to an `InternalServerError` first

    The headers the exception carries for its status are kept (``carried_headers``) - a 405 still says in ``Allow``
    which methods the route takes. A ready-made response the exception may carry is not used: the body is always the
    envelope

    Args:
        error (HTTPException): The exception Flask is answering, carrying the status code, the
            status name and - as its `description` - whatever `abort` was given

    Returns:
        Response: The `{description, message, response, status}` body with that status and the status' headers
    """
    status: int = error.code or FALLBACK_STATUS

    # `type(error).description` is the class default - the generic meaning of the status - while
    # `error.description` is what this failure was given. Reading the first one off the class keeps it
    # self-maintaining for every status
    return ErrorResponse(
        status=status,
        prefix=error.name,
        description=type(error).description,
        message=error.description,
    ).make_error(carried_headers(error))


def database_unavailable(error: DocumentNetworkError) -> Response:
    """
    Answers a lost database connection with a 503 - the request may succeed if tried again

    Args:
        error (DocumentNetworkError): The connection failure that escaped the route

    Returns:
        Response: The JSON envelope with status 503
    """
    LOGGER.error("[DB Network Error] %s: %s", type(error).__name__, error, exc_info=error)

    return http_exception(ServiceUnavailable(DATABASE_UNAVAILABLE_MSG))


def database_locked(error: DocumentLockTimeoutError) -> Response:
    """
    Answers a database lock timeout with a 423 - the collection is busy, the request may succeed if tried again

    Args:
        error (DocumentLockTimeoutError): The lock timeout that escaped the route

    Returns:
        Response: The JSON envelope with status 423
    """
    LOGGER.error("[DB Lock Timeout] %s: %s", type(error).__name__, error, exc_info=error)

    return http_exception(Locked(DATABASE_LOCKED_MSG))


def database_connection_failed(error: DatabaseConnectionError) -> Response:
    """
    Answers the connector's own connection error: a 503 when the server was lost, a 500 otherwise

    The connector raises ``DatabaseConnectionError`` for a failed connection check, but the admin operations raise it
    for any failure (listing, creating or dropping a database or collection). Only a lost connection in its cause
    chain (``is_lost_connection``) makes it "try again"; anything else is the server's fault, with nothing to retry

    Args:
        error (DatabaseConnectionError): The error that escaped the route

    Returns:
        Response: The JSON envelope with status 503 or 500
    """
    LOGGER.error("[DB Connection Error] %s: %s", type(error).__name__, error, exc_info=error)

    if is_lost_connection(error):
        return http_exception(ServiceUnavailable(DATABASE_UNAVAILABLE_MSG))

    return http_exception(InternalServerError(DATABASE_OPERATION_FAILED_MSG))
