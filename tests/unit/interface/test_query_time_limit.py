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
Unit tests for cmdb.interface.query_time_limit.abort_if_query_too_slow and the two shared decorators that call it

Pure tests (no MongoDB, no routes): a query the server stopped on its time budget is answered with one 503 naming
the budget, wherever the typed error sits in the cause chain, and nothing else changes
"""
import logging
from http import HTTPStatus

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database.database_constants import LONG_QUERY_TIME_LIMIT_MS, QUERY_TIME_LIMIT_MS
from cmdb.interface.query_time_limit import abort_if_query_too_slow
from cmdb.interface.request_limits_constants import MILLISECONDS_PER_SECOND, QUERY_TIME_LIMIT_RESPONSE_MESSAGE
from cmdb.interface.route_utils import handle_manager_errors, handle_route_errors
from cmdb.errors.database import DocumentAggregationError, DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

TABLE_MESSAGE: str = 'Failed to retrieve the things!'


class _ThingManagerIterationError(Exception):
    """Stands in for a feature manager's iteration error."""


def _timed_out_in_the_manager(time_limit_ms: int = QUERY_TIME_LIMIT_MS) -> _ThingManagerIterationError:
    """The chain a route catches: feature manager -> BaseManager -> the typed database error."""
    timeout = DocumentQueryTimeLimitError('operation exceeded time limit', time_limit_ms)
    base = BaseManagerIterationError(timeout)
    base.__cause__ = timeout
    feature = _ThingManagerIterationError(base)
    feature.__cause__ = base

    return feature


def _message(time_limit_ms: int) -> str:
    """The 503's text for a budget."""
    return QUERY_TIME_LIMIT_RESPONSE_MESSAGE.format(seconds=time_limit_ms // MILLISECONDS_PER_SECOND)


class TestAbortIfQueryTooSlow:
    """The helper itself."""

    def test_the_typed_error_is_a_503(self) -> None:
        """Not the caller's fault and not an outage: the query ran out of time"""
        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            abort_if_query_too_slow(DocumentQueryTimeLimitError('slow', QUERY_TIME_LIMIT_MS))

        assert caught.value.code == HTTPStatus.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize('time_limit_ms', [QUERY_TIME_LIMIT_MS, LONG_QUERY_TIME_LIMIT_MS])
    def test_the_message_names_the_budget_the_query_ran_past(self, time_limit_ms: int) -> None:
        """10 seconds for a list page, the long budget for the export and the reports"""
        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            abort_if_query_too_slow(DocumentQueryTimeLimitError('slow', time_limit_ms))

        assert caught.value.description == _message(time_limit_ms)
        assert f'{time_limit_ms // MILLISECONDS_PER_SECOND} seconds' in caught.value.description

    def test_it_is_found_through_the_managers_wrapping(self) -> None:
        """Two manager layers deep"""
        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            abort_if_query_too_slow(_timed_out_in_the_manager(LONG_QUERY_TIME_LIMIT_MS))

        assert caught.value.description == _message(LONG_QUERY_TIME_LIMIT_MS)

    def test_any_other_error_is_left_to_the_caller(self) -> None:
        """A plain aggregation failure, or anything else, returns"""
        assert abort_if_query_too_slow(DocumentAggregationError('bad stage')) is None
        assert abort_if_query_too_slow(BaseManagerIterationError(RuntimeError('boom'))) is None

    def test_it_is_logged_as_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A refusal of the request, not a server fault: no traceback"""
        with caplog.at_level(logging.WARNING), Flask(__name__).app_context(), pytest.raises(HTTPException):
            abort_if_query_too_slow(DocumentQueryTimeLimitError('slow', QUERY_TIME_LIMIT_MS))

        records = [record for record in caplog.records if 'abort_if_query_too_slow' in record.getMessage()]
        assert [record.levelno for record in records] == [logging.WARNING]
        assert records[0].exc_info is None


class TestTheSharedDecorators:
    """Both answer the time limit before their own mapping."""

    def test_the_generic_tail_answers_503_not_500(self) -> None:
        """A route with no rule of its own for the read"""
        @handle_route_errors('while retrieving the things')
        def route() -> None:
            raise _timed_out_in_the_manager()

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.SERVICE_UNAVAILABLE
        assert caught.value.description == _message(QUERY_TIME_LIMIT_MS)

    def test_the_error_table_answers_the_time_limit_not_its_400(self) -> None:
        """The table's 'Failed to retrieve' would read like a broken query"""
        @handle_manager_errors({_ThingManagerIterationError: TABLE_MESSAGE})
        def route() -> None:
            raise _timed_out_in_the_manager()

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_the_error_table_keeps_its_400_otherwise(self) -> None:
        """A mapped error that is not the time limit"""
        @handle_manager_errors({_ThingManagerIterationError: TABLE_MESSAGE})
        def route() -> None:
            raise _ThingManagerIterationError('bad stage')

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert caught.value.description == TABLE_MESSAGE

    def test_the_generic_tail_keeps_its_500_otherwise(self) -> None:
        """Nothing else changes"""
        @handle_route_errors('while retrieving the things')
        def route() -> None:
            raise RuntimeError('boom')

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
