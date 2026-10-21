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
The one answer to a query the server stopped on its time budget

An aggregation a client shapes - a list route's ``?filter=``, the search, the export, the ISMS reports - runs under a
server-side budget (``database_constants.QUERY_TIME_LIMIT_MS`` / ``LONG_QUERY_TIME_LIMIT_MS``). One the server stopped
on it reaches a route as a typed ``DocumentQueryTimeLimitError`` somewhere in the error chain, and every route answers
it with the same 503 naming the budget: the shared decorators of ``route_utils`` call ``abort_if_query_too_slow``
before their own answers, and so does every hand-written ``except`` of a manager's iteration error
"""
from http import HTTPStatus
from logging import Logger, getLogger
from flask import abort

from cmdb.interface.request_limits_constants import MILLISECONDS_PER_SECOND, QUERY_TIME_LIMIT_RESPONSE_MESSAGE
from cmdb.utils import find_cause

from cmdb.errors.database import DocumentQueryTimeLimitError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['abort_if_query_too_slow']

LOGGER: Logger = getLogger(__name__)


def abort_if_query_too_slow(err: BaseException) -> None:
    """
    Answers a query the server stopped on its time budget with the one 503 every route gives

    The database layer raises a typed ``DocumentQueryTimeLimitError`` for it, and the managers wrap that in their
    own iteration error - so the cause is looked for in the chain rather than assumed. The message names the budget
    the query ran past. Anything else returns, for the caller to answer as it would have. Call it first in an
    ``except`` of a manager's iteration error, before that arm reports the failure its own way

    Args:
        err (BaseException): The error the read raised

    Raises:
        werkzeug.exceptions.ServiceUnavailable: Aborts with 503 when the query ran past its time budget
    """
    timeout: DocumentQueryTimeLimitError | None = find_cause(err, DocumentQueryTimeLimitError)

    if timeout is not None:
        LOGGER.warning("[abort_if_query_too_slow] %s: %s", type(err).__name__, err)
        abort(
            HTTPStatus.SERVICE_UNAVAILABLE,
            QUERY_TIME_LIMIT_RESPONSE_MESSAGE.format(seconds=timeout.time_limit_ms // MILLISECONDS_PER_SECOND),
        )
