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

**One handler for every status, rather than one per status.** Until 2026-09-16 nine codes were
registered individually (400, 401, 403, 404, 405, 406, 410, 500, 503) and anything outside that list
fell through to Flask's HTML page - which broke the envelope the Angular client reads
(`err?.error?.message`) for any status nobody had thought of. That was not hypothetical: **415 was
reachable on the running API today**, because Werkzeug raises it while parsing the request, before
any route runs and therefore out of reach of any `abort()` census (tier 2 T135).

Registering the `HTTPException` **class** closes the whole family at once, including the statuses a
future route invents, and including an unhandled non-HTTP exception - Flask converts one to
`InternalServerError`, which is an `HTTPException`, so it lands here as a 500 too.

**The envelope is unchanged**, deliberately: `{description, message, response, status}` with the same
values the nine hand-written handlers produced. Each of them passed the Werkzeug class's default
`description` and a prefix that was that class's `name`; both are read off the exception here instead
of being spelled out nine times, so the output is identical and there is nothing left to keep in sync

Two statuses this replaces were never raised at all (**406** and **410** - the whole `cmdb/` tree
aborts only 400, 401, 403, 404, 405, 500 and 503) and were kept as defensive catches. Under a
class handler that justification is unnecessary: they are covered because everything is

Note this is the REST API's contract only. The SPA host (`interface/net_app`) registers a 404 of its
own that serves the Angular entry point, and must keep it - that app answers HTML on purpose
"""
from logging import Logger, getLogger
from typing import Any

from flask import Response, request, jsonify
from werkzeug.exceptions import HTTPException, InternalServerError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Status used when an HTTPException carries no code of its own (the base class does not)
FALLBACK_STATUS: int = InternalServerError.code

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


    def make_error(self) -> Response:
        """
        Renders the envelope as a Flask response carrying the status

        Returns:
            Response: The JSON body with its HTTP status code set
        """
        response: Response = jsonify(self.__dict__)
        response.status_code = self.status

        return response


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

    Args:
        error (HTTPException): The exception Flask is answering, carrying the status code, the
            status name and - as its `description` - whatever `abort` was given

    Returns:
        Response: The `{description, message, response, status}` body with that status
    """
    status: int = error.code or FALLBACK_STATUS

    # `type(error).description` is the class default - the generic meaning of the status - while
    # `error.description` is what this failure was given. The nine hand-written handlers spelled the
    # first one out per status; reading it off the class keeps them identical and self-maintaining
    return ErrorResponse(
        status=status,
        prefix=error.name,
        description=type(error).description,
        message=error.description,
    ).make_error()
