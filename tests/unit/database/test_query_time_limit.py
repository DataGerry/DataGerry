# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the server-side time budget of an aggregation

Pure tests (no MongoDB): ``MongoDatabaseManager.aggregate_within_time_limit`` against a mocked collection, the
typed ``DocumentQueryTimeLimitError`` and how the budget constants relate. What the server does with the budget -
stopping the aggregation, leaving no operation behind - is the integration test's
"""
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from pymongo.errors import ExecutionTimeout

from cmdb.database.database_constants import (
    LONG_QUERY_TIME_LIMIT_MS,
    MONGO_MAX_TIME_OPTION,
    MONGO_SOCKET_TIMEOUT_MS,
    QUERY_TIME_LIMIT_MS,
)
from cmdb.database import mongo_database_manager as mongo_database_manager_module
from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.errors.database import DocumentAggregationError, DocumentQueryTimeLimitError
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'framework.objects'
DATABASE_NAME: str = 'cmdb-unit'
PIPELINE: list[dict[str, Any]] = [{'$match': {'public_id': 1}}]
BUDGET_MS: int = 4321
ROWS: list[dict[str, Any]] = [{'public_id': 1}, {'public_id': 2}]
MAX_TIME_EXPIRED_CODE: int = 50


def _manager(collection: MagicMock) -> MongoDatabaseManager:
    """A manager without a connection whose every collection is `collection`."""
    manager = MongoDatabaseManager.__new__(MongoDatabaseManager)
    manager.get_collection = MagicMock(return_value=collection)

    return manager


def _timeout() -> ExecutionTimeout:
    """The driver's error for an aggregation the server stopped on its maxTimeMS."""
    return ExecutionTimeout('operation exceeded time limit', code=MAX_TIME_EXPIRED_CODE)


class TestTheBudget:
    """What the aggregation is sent with."""

    def test_the_budget_is_the_aggregations_max_time(self) -> None:
        """maxTimeMS carries the budget, beside the pipeline"""
        collection = MagicMock(name='collection')
        collection.aggregate.return_value = iter(ROWS)

        _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        collection.aggregate.assert_called_once_with(PIPELINE, **{MONGO_MAX_TIME_OPTION: BUDGET_MS})

    def test_further_options_are_kept(self) -> None:
        """allowDiskUse (the ISMS reports) reaches the driver beside the budget"""
        collection = MagicMock(name='collection')
        collection.aggregate.return_value = iter([])

        _manager(collection).aggregate_within_time_limit(
            COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS, allowDiskUse=True,
        )

        assert collection.aggregate.call_args.kwargs == {'allowDiskUse': True, MONGO_MAX_TIME_OPTION: BUDGET_MS}

    def test_the_budget_wins_over_a_max_time_passed_as_an_option(self) -> None:
        """The budget argument is THE budget - an option cannot widen it"""
        collection = MagicMock(name='collection')
        collection.aggregate.return_value = iter([])

        _manager(collection).aggregate_within_time_limit(
            COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS, **{MONGO_MAX_TIME_OPTION: BUDGET_MS * 10},
        )

        assert collection.aggregate.call_args.kwargs[MONGO_MAX_TIME_OPTION] == BUDGET_MS

    def test_the_collection_and_database_are_the_callers(self) -> None:
        """The collection is looked up in the named database"""
        collection = MagicMock(name='collection')
        collection.aggregate.return_value = iter([])
        manager = _manager(collection)

        manager.aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        manager.get_collection.assert_called_once_with(COLLECTION, DATABASE_NAME)


class TestTheResult:
    """What it answers."""

    def test_every_row_is_read(self) -> None:
        """A list, not the cursor - read to the end inside the method"""
        collection = MagicMock(name='collection')
        collection.aggregate.return_value = iter(ROWS)

        result = _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        assert result == ROWS
        assert isinstance(result, list)


class TestATimeout:
    """The server stopped the aggregation on its budget."""

    def test_on_the_command_it_is_the_typed_error_carrying_the_budget(self) -> None:
        """The first batch never came: DocumentQueryTimeLimitError, naming the budget, wrapping the driver's error"""
        collection = MagicMock(name='collection')
        timeout = _timeout()
        collection.aggregate.side_effect = timeout

        with pytest.raises(DocumentQueryTimeLimitError) as exc_info:
            _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        assert exc_info.value.time_limit_ms == BUDGET_MS
        assert exc_info.value.args[0] is timeout
        assert exc_info.value.__cause__ is timeout

    def test_while_reading_it_is_the_same_typed_error(self) -> None:
        """A later batch ran past the budget while the cursor was read - still inside the sorting"""
        def _cursor() -> Iterator[dict[str, Any]]:
            yield ROWS[0]
            raise _timeout()

        collection = MagicMock(name='collection')
        collection.aggregate.return_value = _cursor()

        with pytest.raises(DocumentQueryTimeLimitError) as exc_info:
            _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        assert exc_info.value.time_limit_ms == BUDGET_MS

    def test_it_is_not_retried(self) -> None:
        """A deterministic answer: one attempt, however much retry budget is left"""
        collection = MagicMock(name='collection')
        collection.aggregate.side_effect = _timeout()

        with pytest.raises(DocumentQueryTimeLimitError):
            _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        assert collection.aggregate.call_count == 1

    def test_any_other_failure_is_a_plain_aggregation_error(self) -> None:
        """Not every failure is a timeout - and nothing else is reported as one"""
        collection = MagicMock(name='collection')
        failure = RuntimeError('bad stage')
        collection.aggregate.side_effect = failure

        with pytest.raises(DocumentAggregationError) as exc_info:
            _manager(collection).aggregate_within_time_limit(COLLECTION, DATABASE_NAME, PIPELINE, BUDGET_MS)

        assert not isinstance(exc_info.value, DocumentQueryTimeLimitError)
        assert exc_info.value.__cause__ is failure


class TestTheTypedError:
    """DocumentQueryTimeLimitError."""

    def test_it_is_an_aggregation_error(self) -> None:
        """Every caller that catches an aggregation failure still catches it"""
        assert issubclass(DocumentQueryTimeLimitError, DocumentAggregationError)

    def test_it_carries_the_error_and_the_budget(self) -> None:
        """args[0] is the wrapped error, the budget is an attribute"""
        timeout = _timeout()
        error = DocumentQueryTimeLimitError(timeout, BUDGET_MS)

        assert error.args[0] is timeout
        assert error.time_limit_ms == BUDGET_MS


class TestTheConstants:
    """How the budgets relate to each other and to the socket."""

    def test_a_client_shaped_query_gets_less_than_a_long_read(self) -> None:
        """A list page is held tighter than the export and the reports"""
        assert QUERY_TIME_LIMIT_MS < LONG_QUERY_TIME_LIMIT_MS

    def test_the_long_budget_ends_before_the_socket_times_out(self) -> None:
        """So the server's 'time limit exceeded' arrives before the driver reports a network failure"""
        assert LONG_QUERY_TIME_LIMIT_MS < MONGO_SOCKET_TIMEOUT_MS

    def test_the_client_uses_the_named_socket_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The constant the budgets are measured against is the one the client is built with"""
        monkeypatch.setattr(mongo_database_manager_module, 'MongoConnector', MagicMock())
        monkeypatch.setattr(MongoDatabaseManager, '_start_keepalive', lambda self: None)

        manager = MongoDatabaseManager('localhost', 27017, DATABASE_NAME)

        assert manager.client_options['socketTimeoutMS'] == MONGO_SOCKET_TIMEOUT_MS
