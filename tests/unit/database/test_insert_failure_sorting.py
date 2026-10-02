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
Unit tests for how MongoDatabaseManager.insert sorts a failed write, on both of its paths

Pure tests: the collection is a stub. Pinned:

  - ``typed_insert_failure`` sorts each failure into its own error, and only a lost connection is a network error
    - every other ``PyMongoError`` is a plain insert error, never one the layers above would retry
  - the ``skip_public`` path sorts exactly like the retry loop, and a public_id clash there is a genuine duplicate
  - a caller-supplied id that is stored stays stored even when its counter cannot be raised: the id is returned
  - a counter that cannot hand out an id fails the insert as an insert error
"""
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from pymongo.errors import (
    AutoReconnect,
    ConfigurationError,
    ConnectionFailure,
    DocumentTooLarge,
    DuplicateKeyError,
    ExecutionTimeout,
    InvalidOperation,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
    WriteError,
)

from cmdb.database.mongo_database_manager import MongoDatabaseManager, typed_insert_failure
from cmdb.errors.database import (
    DocumentDuplicateKeyError,
    DocumentGetError,
    DocumentInsertDuplicateKeyError,
    DocumentInsertError,
    DocumentInsertTooLargeError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    DocumentUpdateError,
    TRANSIENT_DATABASE_ERRORS,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB: str = 'testdb'
COLLECTION: str = 'framework.objects'
SUPPLIED_ID: int = 42
LOCK_TIMEOUT_CODE: int = 24
VALIDATION_FAILURE_CODE: int = 121
UNAUTHORIZED_CODE: int = 13
BSON_OBJECT_TOO_LARGE: int = 10334
DUPLICATE_DETAILS: dict[str, Any] = {'keyPattern': {'name': 1}, 'keyValue': {'name': 'taken'}}
PUBLIC_ID_DUPLICATE_DETAILS: dict[str, Any] = {'keyPattern': {'public_id': 1}, 'keyValue': {'public_id': SUPPLIED_ID}}

SORTED_FAILURES: list[Any] = [
    pytest.param(DuplicateKeyError('dup', details=DUPLICATE_DETAILS), DocumentInsertDuplicateKeyError, id='duplicate'),
    pytest.param(ExecutionTimeout('slow'), DocumentLockTimeoutError, id='time-limit'),
    pytest.param(OperationFailure('locked', code=LOCK_TIMEOUT_CODE), DocumentLockTimeoutError, id='lock-timeout'),
    pytest.param(DocumentTooLarge('too large'), DocumentInsertTooLargeError, id='too-large-driver'),
    pytest.param(WriteError('too large', code=BSON_OBJECT_TOO_LARGE), DocumentInsertTooLargeError,
                 id='too-large-server'),
    pytest.param(AutoReconnect('lost'), DocumentNetworkError, id='auto-reconnect'),
    pytest.param(NetworkTimeout('slow net'), DocumentNetworkError, id='network-timeout'),
    pytest.param(ServerSelectionTimeoutError('no server'), DocumentNetworkError, id='no-server'),
    pytest.param(ConnectionFailure('refused'), DocumentNetworkError, id='connection-failure'),
    pytest.param(WriteError('validation', code=VALIDATION_FAILURE_CODE), DocumentInsertError, id='validation'),
    pytest.param(OperationFailure('unauthorized', code=UNAUTHORIZED_CODE), DocumentInsertError, id='unauthorized'),
    pytest.param(InvalidOperation('closed client'), DocumentInsertError, id='invalid-operation'),
    pytest.param(ConfigurationError('bad config'), DocumentInsertError, id='configuration'),
    pytest.param(RuntimeError('boom'), DocumentInsertError, id='not-a-mongo-error'),
]
# The refusals and failures no retry can fix
NOT_TRANSIENT: list[Any] = [failure for failure in SORTED_FAILURES
                            if failure.values[1] not in (DocumentLockTimeoutError, DocumentNetworkError)]


@pytest.fixture(name='mgr')
def fixture_mgr() -> MongoDatabaseManager:
    """A MongoDatabaseManager without its real __init__ (no connector, no keepalive thread)"""
    manager = MongoDatabaseManager.__new__(MongoDatabaseManager)
    manager.db_name = DB
    manager.connector = MagicMock(name='connector')
    manager._keepalive_thread = None  # pylint: disable=protected-access
    manager.get_next_public_id = MagicMock(return_value=1)
    manager.update_public_id_counter = MagicMock()

    return manager


def _collection(mgr: MongoDatabaseManager, error: Exception | None = None) -> MagicMock:
    """The stub collection; its insert_one raises the given error"""
    collection = MagicMock(name='collection')
    collection.insert_one.side_effect = error
    mgr.get_collection = MagicMock(return_value=collection)

    return collection


@pytest.mark.parametrize('error, expected', SORTED_FAILURES)
def test_each_failure_is_sorted_into_its_own_error(error: Exception, expected: type) -> None:
    """The exact class - a network error is not an insert error, and an insert error is not a network error"""
    assert type(typed_insert_failure(error, COLLECTION)) is expected


@pytest.mark.parametrize('error, expected', NOT_TRANSIENT)
def test_a_refusal_is_never_transient(error: Exception, expected: type) -> None:
    """The layers above let a transient error through as "retry"; a refusal must not be one"""
    assert not isinstance(typed_insert_failure(error, COLLECTION), TRANSIENT_DATABASE_ERRORS)


def test_the_duplicate_names_the_index_and_the_value() -> None:
    """What a route reads off the typed refusal"""
    failure = typed_insert_failure(DuplicateKeyError('dup', details=DUPLICATE_DETAILS), COLLECTION)

    assert (failure.key_pattern, failure.key_value) == (DUPLICATE_DETAILS['keyPattern'], DUPLICATE_DETAILS['keyValue'])


class TestTheSkipPublicPath:
    """Sorted like the retry loop"""

    @pytest.mark.parametrize('error, expected', SORTED_FAILURES)
    def test_each_failure_raises_its_sorted_error(self, mgr: MongoDatabaseManager, error: Exception,
                                                  expected: type) -> None:
        """The original error is the cause"""
        _collection(mgr, error)

        with pytest.raises(expected) as caught:
            mgr.insert(COLLECTION, DB, {'public_id': SUPPLIED_ID}, skip_public=True)

        assert type(caught.value) is expected
        assert caught.value.__cause__ is error

    def test_a_public_id_clash_is_a_duplicate_and_not_retried(self, mgr: MongoDatabaseManager) -> None:
        """The caller chose the id, so there is nothing to draw instead"""
        collection = _collection(mgr, DuplicateKeyError('dup', details=PUBLIC_ID_DUPLICATE_DETAILS))

        with pytest.raises(DocumentDuplicateKeyError):
            mgr.insert(COLLECTION, DB, {'public_id': SUPPLIED_ID}, skip_public=True)

        assert collection.insert_one.call_count == 1
        mgr.get_next_public_id.assert_not_called()


class TestTheRetryLoop:
    """The counter path"""

    @pytest.mark.parametrize('error, expected', SORTED_FAILURES[1:])
    def test_each_failure_but_a_duplicate_raises_its_sorted_error(self, mgr: MongoDatabaseManager,
                                                                  error: Exception, expected: type) -> None:
        """The same sorting as the skip_public path"""
        _collection(mgr, error)

        with pytest.raises(expected) as caught:
            mgr.insert(COLLECTION, DB, {'name': 'n'})

        assert type(caught.value) is expected

    def test_a_counter_that_cannot_hand_out_an_id_fails_the_insert(self, mgr: MongoDatabaseManager) -> None:
        """An insert error, with the counter's error as the cause"""
        _collection(mgr)
        counter_error = DocumentGetError('counter unreachable')
        mgr.get_next_public_id.side_effect = counter_error

        with pytest.raises(DocumentInsertError) as caught:
            mgr.insert(COLLECTION, DB, {'name': 'n'})

        assert caught.value.__cause__ is counter_error

    def test_a_stored_supplied_id_survives_a_failing_counter(self, mgr: MongoDatabaseManager,
                                                             caplog: pytest.LogCaptureFixture) -> None:
        """The document exists, so the insert answers its id and logs the counter"""
        collection = _collection(mgr)
        mgr.update_public_id_counter.side_effect = DocumentUpdateError('counter unreachable')

        with caplog.at_level(logging.ERROR):
            assert mgr.insert(COLLECTION, DB, {'public_id': SUPPLIED_ID}) == SUPPLIED_ID

        collection.insert_one.assert_called_once()
        assert str(SUPPLIED_ID) in caplog.text

    def test_a_supplied_id_raises_the_counter(self, mgr: MongoDatabaseManager) -> None:
        """The reconciliation itself"""
        _collection(mgr)

        mgr.insert(COLLECTION, DB, {'public_id': SUPPLIED_ID})

        mgr.update_public_id_counter.assert_called_once_with(COLLECTION, DB, value=SUPPLIED_ID)
