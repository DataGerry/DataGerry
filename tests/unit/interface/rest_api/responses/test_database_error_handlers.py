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
Unit tests for the app's handler of the connector's own `DatabaseConnectionError` and the predicate it decides by

The connector raises it for a failed connection check, the admin operations for any failure, so only a lost
connection in its cause chain makes it a 503; anything else is a 500 with nothing to retry
"""
from http import HTTPStatus

import pytest
from flask import Flask
from pymongo.errors import ConnectionFailure, OperationFailure

from cmdb.database.mongo_error_helper import LOST_CONNECTION_ERRORS, is_lost_connection
from cmdb.errors.database import (
    APP_HANDLED_DATABASE_ERRORS,
    DatabaseConnectionError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
from cmdb.interface.rest_api.responses.error_handlers import (
    DATABASE_OPERATION_FAILED_MSG,
    DATABASE_UNAVAILABLE_MSG,
    database_connection_failed,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _wrapping(cause: BaseException | None) -> DatabaseConnectionError:
    """A DatabaseConnectionError raised `from cause`"""
    error = DatabaseConnectionError('failed')
    error.__cause__ = cause

    return error


class TestIsLostConnection:
    """A lost connection anywhere in the chain - the connector's own error class alone is not one"""

    @pytest.mark.parametrize('cause', [ConnectionFailure('gone'), DocumentNetworkError('lost')],
                             ids=['driver', 'typed'])
    def test_a_lost_connection_in_the_chain_is_found(self, cause: BaseException) -> None:
        """Itself, and two links down"""
        assert is_lost_connection(cause) is True
        assert is_lost_connection(_wrapping(cause)) is True

    @pytest.mark.parametrize('error', [
        _wrapping(None), _wrapping(OperationFailure('refused')), DocumentLockTimeoutError('locked'), ValueError('x'),
    ], ids=['connector-alone', 'operation-failure', 'lock', 'other'])
    def test_anything_else_is_not(self, error: BaseException) -> None:
        """A DatabaseConnectionError without a lost connection behind it says nothing about the server"""
        assert is_lost_connection(error) is False

    def test_the_classes_are_pinned(self) -> None:
        """The connector's own class stays out - unlike DATABASE_OUTAGE_ERRORS"""
        assert LOST_CONNECTION_ERRORS == (ConnectionFailure, DocumentNetworkError)


class TestDatabaseConnectionFailed:
    """The handler's two answers, in the shared envelope"""

    @pytest.mark.parametrize('cause, status, message', [
        (ConnectionFailure('gone'), HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
        (None, HTTPStatus.INTERNAL_SERVER_ERROR, DATABASE_OPERATION_FAILED_MSG),
        (OperationFailure('refused'), HTTPStatus.INTERNAL_SERVER_ERROR, DATABASE_OPERATION_FAILED_MSG),
    ], ids=['lost-connection', 'no-cause', 'operation-failure'])
    def test_answers_by_the_cause(self, cause: BaseException | None, status: HTTPStatus, message: str) -> None:
        """503 only when the server was lost"""
        with Flask(__name__).test_request_context():
            response = database_connection_failed(_wrapping(cause))

        assert response.status_code == status
        assert response.get_json()['message'] == message


def test_the_app_handled_errors_are_pinned() -> None:
    """What every route error tail lets through to the app's handlers"""
    assert APP_HANDLED_DATABASE_ERRORS == (DocumentLockTimeoutError, DocumentNetworkError, DatabaseConnectionError)
