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
Unit tests for cmdb.database.retry

Pure tests: no Mongo. What is pinned here is the **policy**, because the decorator's whole value is
which failures it repeats and which it does not (discussion-backlog #142: until 2026-09-09 it caught
only raw pymongo errors, which the decorated methods convert into typed `cmdb.errors.database` errors
before they can escape - so 34 of the 36 decorators in the layer never retried anything).

Three groups:

  - `is_retryable`, exhaustively: a server-selection failure is retryable for any operation (the
    command never left the driver), any other connection failure only for a read, and a deterministic
    failure - a duplicate key, a validation error, a lock timeout - never
  - the wrapper's behaviour: the attempt count, the doubling delay, the re-raise of the original
    error, and that it stays transparent to `self`, the arguments and `functools.wraps`
  - the **time budget**, which is what makes the retries affordable: a retry that would not finish
    inside RETRY_TIME_BUDGET is not started, so an unreachable database (10s of server selection per
    attempt) is reported after the first one instead of three times over
"""
from typing import Any

import pytest
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from cmdb.database import retry as retry_module
from cmdb.database.retry import (
    RETRY_MAX_ATTEMPTS,
    is_retryable,
    retry_operation,
)
from cmdb.errors.database import (
    DatabaseConnectionError,
    DocumentAggregationError,
    DocumentDeleteError,
    DocumentGetError,
    DocumentInsertError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    DocumentUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

SENTINEL: str = 'ok'


def _wrapped(error: BaseException, cause: BaseException | None = None) -> BaseException:
    """Builds the typed error the way the decorated methods raise it - with its cause attached."""
    if cause is not None:
        error.__cause__ = cause

    return error


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    is_retryable                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestARequestThatNeverLeftTheDriver:
    """A server-selection failure is safe to repeat for reads AND writes."""

    @pytest.mark.parametrize('error_type', [
        DocumentGetError, DocumentInsertError, DocumentUpdateError, DocumentDeleteError,
        DocumentNetworkError, DocumentAggregationError, DatabaseConnectionError,
    ])
    def test_any_operation_may_be_retried(self, error_type: type[BaseException]) -> None:
        """No server was found, so not even a write can have been applied"""
        assert is_retryable(_wrapped(error_type('down'), ServerSelectionTimeoutError('no server'))) is True

    def test_a_raw_server_selection_failure_is_retryable(self) -> None:
        """The methods that do not wrap (status, is_connected) raise it unchanged"""
        assert is_retryable(ServerSelectionTimeoutError('no server')) is True


class TestAConnectionThatDroppedMidCommand:
    """Any other connection failure: reads may be repeated, writes may not."""

    @pytest.mark.parametrize('error_type', [DocumentGetError, DocumentAggregationError,
                                            DatabaseConnectionError])
    def test_a_read_may_be_retried(self, error_type: type[BaseException]) -> None:
        """Repeating a read has no side effect"""
        assert is_retryable(_wrapped(error_type('lost'), AutoReconnect('connection lost'))) is True

    @pytest.mark.parametrize('error_type', [DocumentInsertError, DocumentUpdateError,
                                            DocumentDeleteError, DocumentNetworkError])
    def test_a_write_is_not_retried(self, error_type: type[BaseException]) -> None:
        """
        The write may have been applied before the acknowledgement was lost

        There are no retryable writes to fall back on either - a standalone mongod is the norm
        on-premise - so repeating it could insert twice.
        """
        assert is_retryable(_wrapped(error_type('lost'), NetworkTimeout('timeout'))) is False

    def test_a_raw_connection_failure_is_retryable(self) -> None:
        """Only the non-writing methods leave a pymongo error unwrapped"""
        assert is_retryable(ConnectionFailure('lost')) is True


class TestADeterministicFailure:
    """A failure that will fail again is reported immediately, however it is spelled."""

    @pytest.mark.parametrize('error, cause', [
        (DocumentInsertError('dup'), DuplicateKeyError('E11000 duplicate key')),
        (DocumentUpdateError('validation'), OperationFailure('document failed validation')),
        (DocumentLockTimeoutError('lock'), ExecutionTimeout('exceeded time limit')),
        (DocumentGetError('bad pipeline'), OperationFailure('unknown operator')),
        (DocumentInsertError('no cause'), None),
    ], ids=['duplicate-key', 'validation', 'lock-timeout', 'bad-pipeline', 'no-cause'])
    def test_it_is_not_retried(self, error: BaseException, cause: BaseException | None) -> None:
        """Retrying one only spends the caller's time - a duplicate key used to cost ~15s of sleep"""
        assert is_retryable(_wrapped(error, cause)) is False

    def test_a_bare_pymongo_error_is_not_retried(self) -> None:
        """PyMongoError is the base of every pymongo failure, duplicate keys included"""
        assert is_retryable(PyMongoError('anything')) is False

    def test_an_unrelated_exception_is_not_retried(self) -> None:
        """A bug in the wrapped method is not a transient condition"""
        assert is_retryable(ValueError('boom')) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the wrapper itself                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class _Recorder:
    """A subject whose decorated operations count their calls."""

    def __init__(self, failures: int = 0, error: BaseException | None = None) -> None:
        self.calls: int = 0
        self.failures: int = failures
        self.error: BaseException = error or _wrapped(
            DocumentGetError('lost'), AutoReconnect('connection lost'),
        )

    @retry_operation
    def read(self, *args: Any, **kwargs: Any) -> Any:
        """Fails the configured number of times, then answers with what it was given."""
        self.calls += 1

        if self.calls <= self.failures:
            raise self.error

        return kwargs or args or SENTINEL


@pytest.fixture(name='instant_backoff', autouse=True)
def fixture_instant_backoff(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Records the sleeps instead of performing them, and removes the jitter."""
    slept: list[float] = []

    monkeypatch.setattr(retry_module.time, 'sleep', slept.append)
    monkeypatch.setattr(retry_module.random, 'uniform', lambda *_args: 0.0)

    return slept


class TestTheWrapper:
    """The attempt count, the delays, and that the caller cannot tell the wrapper is there."""

    def test_a_successful_operation_runs_once(self) -> None:
        """Nothing is retried when nothing failed"""
        recorder = _Recorder()

        assert recorder.read() == SENTINEL
        assert recorder.calls == 1

    def test_a_transient_failure_is_retried_until_it_succeeds(self) -> None:
        """The point of the decorator, and what #142 had made impossible"""
        recorder = _Recorder(failures=2)

        assert recorder.read() == SENTINEL
        assert recorder.calls == RETRY_MAX_ATTEMPTS

    def test_the_delay_doubles_between_attempts(self, instant_backoff: list[float]) -> None:
        """0.2s then 0.4s - sub-second in total, where the old settings slept up to 19s"""
        _Recorder(failures=2).read()

        assert instant_backoff == [pytest.approx(0.2), pytest.approx(0.4)]

    def test_the_original_error_is_raised_after_the_last_attempt(self) -> None:
        """The caller's error type never depends on how many attempts it took"""
        recorder = _Recorder(failures=RETRY_MAX_ATTEMPTS)

        with pytest.raises(DocumentGetError):
            recorder.read()

        assert recorder.calls == RETRY_MAX_ATTEMPTS

    def test_a_deterministic_failure_is_raised_on_the_first_attempt(self, instant_backoff) -> None:
        """No retry, no sleep - a duplicate key is an answer, not an outage"""
        recorder = _Recorder(
            failures=RETRY_MAX_ATTEMPTS,
            error=_wrapped(DocumentInsertError('dup'), DuplicateKeyError('E11000')),
        )

        with pytest.raises(DocumentInsertError):
            recorder.read()

        assert (recorder.calls, instant_backoff) == (1, [])

    def test_arguments_reach_the_operation(self) -> None:
        """The wrapper is transparent to self, args and kwargs"""
        recorder = _Recorder()

        assert recorder.read(public_id=7) == {'public_id': 7}
        assert recorder.read('positional') == ('positional',)

    def test_the_wrapper_keeps_the_operations_identity(self) -> None:
        """functools.wraps, so a log line names the operation and not 'wrapper'"""
        assert _Recorder.read.__name__ == 'read'
        assert 'Fails the configured number of times' in _Recorder.read.__doc__


class TestTheTimeBudget:
    """A retry is only started when the whole call still fits inside the budget."""

    def test_a_slow_attempt_spends_the_budget_and_is_not_retried(
            self, monkeypatch: pytest.MonkeyPatch, instant_backoff: list[float],
    ) -> None:
        """
        The 'database is unreachable' case

        A single attempt costs the driver's serverSelectionTimeoutMS (10s), so retrying it three
        times would turn a 10s failure into a 30s one. The budget is what prevents that.
        """
        clock = iter([0.0, retry_module.RETRY_TIME_BUDGET + 1.0])
        monkeypatch.setattr(retry_module.time, 'monotonic', lambda: next(clock))

        recorder = _Recorder(failures=RETRY_MAX_ATTEMPTS)

        with pytest.raises(DocumentGetError):
            recorder.read()

        assert (recorder.calls, instant_backoff) == (1, [])

    def test_a_fast_failure_still_gets_its_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dropped socket fails in milliseconds, which leaves the budget intact"""
        monkeypatch.setattr(retry_module.time, 'monotonic', lambda: 0.0)

        recorder = _Recorder(failures=1)

        assert recorder.read() == SENTINEL
        assert recorder.calls == 2
