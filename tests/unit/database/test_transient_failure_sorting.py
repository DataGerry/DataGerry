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
Unit tests for how a failed read, update or delete is told apart from a failed server

Pure tests on constructed errors. Pinned:

  - ``typed_transient_failure`` finds a lost connection or a lock timeout anywhere in the cause chain and answers
    the transient error; every other failure keeps the operation's own error (None)
  - an error that is already typed - transient or the connector's own - is never wrapped again
  - ``raise_final_failure`` raises the transient error from the original, or the original itself
"""
import pytest
from pymongo.errors import (
    AutoReconnect,
    ExecutionTimeout,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from cmdb.database.database_constants import MONGO_LOCK_TIMEOUT_ERROR_CODE
from cmdb.database.mongo_error_helper import typed_transient_failure
from cmdb.database.retry import raise_final_failure
from cmdb.errors.database import (
    DatabaseConnectionError,
    DocumentAggregationError,
    DocumentDeleteError,
    DocumentGetError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    DocumentUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# An OperationFailure code that is neither a lock timeout nor anything else the sorting knows
UNRELATED_ERROR_CODE: int = 2


def _wrapped(error: Exception, cause: BaseException) -> Exception:
    """The operation's typed error raised from the driver's, as the database manager does"""
    error.__cause__ = cause

    return error


class TestTypedTransientFailure:
    """A failure is the server's when a lost connection or a lock timeout is anywhere in its cause chain"""

    @pytest.mark.parametrize('wrapper', [
        DocumentGetError('read'), DocumentUpdateError('update'), DocumentDeleteError('delete'),
        DocumentAggregationError('aggregate'),
    ])
    @pytest.mark.parametrize('cause', [
        AutoReconnect('reconnect'), NetworkTimeout('timeout'), ServerSelectionTimeoutError('no server'),
    ])
    def test_a_lost_connection_is_the_network_error(self, wrapper: Exception, cause: BaseException) -> None:
        """Every operation's error, every kind of lost connection"""
        error = _wrapped(wrapper, cause)

        transient = typed_transient_failure(error)

        assert isinstance(transient, DocumentNetworkError)
        assert transient.args[0] is error

    def test_a_raw_lost_connection_is_the_network_error(self) -> None:
        """A driver error that escaped unwrapped is sorted the same"""
        assert isinstance(typed_transient_failure(AutoReconnect('lost')), DocumentNetworkError)

    def test_a_lock_timeout_is_the_lock_error(self) -> None:
        """Code 24 is the lock timeout"""
        error = _wrapped(DocumentUpdateError('update'), OperationFailure('lock', code=MONGO_LOCK_TIMEOUT_ERROR_CODE))

        assert isinstance(typed_transient_failure(error), DocumentLockTimeoutError)

    def test_a_cause_deeper_in_the_chain_counts(self) -> None:
        """Two layers of wrapping still find the lost connection"""
        inner = _wrapped(DocumentGetError('inner'), NetworkTimeout('timeout'))
        outer = _wrapped(DocumentUpdateError('outer'), inner)

        assert isinstance(typed_transient_failure(outer), DocumentNetworkError)

    @pytest.mark.parametrize('cause', [
        OperationFailure('refused', code=UNRELATED_ERROR_CODE),
        ExecutionTimeout('time limit'),
        ValueError('not the driver'),
    ])
    def test_any_other_failure_keeps_its_own_error(self, cause: BaseException) -> None:
        """A refusal or the query time budget is the operation's answer, not an outage"""
        assert typed_transient_failure(_wrapped(DocumentGetError('read'), cause)) is None

    def test_an_error_without_a_cause_keeps_its_own_error(self) -> None:
        """Nothing in the chain, nothing to sort"""
        assert typed_transient_failure(DocumentGetError('read')) is None

    @pytest.mark.parametrize('typed', [
        DocumentNetworkError('typed'), DocumentLockTimeoutError('typed'), DatabaseConnectionError('typed'),
    ])
    def test_an_already_typed_error_is_not_wrapped_again(self, typed: Exception) -> None:
        """The transient errors and the connector's own error stand as they are"""
        assert typed_transient_failure(_wrapped(typed, AutoReconnect('lost'))) is None


class TestRaiseFinalFailure:
    """The error the retry wrapper finally raises"""

    def test_a_server_failure_is_raised_as_the_transient_error_from_the_original(self) -> None:
        """The operation's error stays reachable as the cause"""
        error = _wrapped(DocumentGetError('read'), AutoReconnect('lost'))

        with pytest.raises(DocumentNetworkError) as raised:
            raise_final_failure(error)

        assert raised.value.__cause__ is error

    def test_any_other_failure_is_raised_unchanged(self) -> None:
        """The very same error object, not a copy"""
        error = _wrapped(DocumentGetError('read'), OperationFailure('refused', code=UNRELATED_ERROR_CODE))

        with pytest.raises(DocumentGetError) as raised:
            raise_final_failure(error)

        assert raised.value is error
