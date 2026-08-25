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
Unit tests for cmdb.database.mongo_database_manager.MongoDatabaseManager

Pure tests (no MongoDB): the manager is built via __new__ (skipping the real connector + keepalive
thread) and its collection/connector calls are mocked. Covers the happy paths of the create/counter
helpers and, for every wrapper, the ``except -> raise <typed error>`` mapping. Error paths raise a
plain Exception (not a PyMongoError) so the @retry_operation decorator does not retry + sleep.
"""
from unittest.mock import MagicMock

import pytest
from pymongo.errors import (
    CollectionInvalid,
    DuplicateKeyError,
    OperationFailure,
    ExecutionTimeout,
    NetworkTimeout,
)
from pymongo.database import Database

import cmdb.database.mongo_database_manager as mdm
from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.database_constants import (
    MAX_DUPLICATE_KEY_RETRIES,
    MONGO_LOCK_TIMEOUT_ERROR_CODE,
)
from cmdb.errors.database import (
    CollectionAlreadyExistsError,
    CreateIndexesError,
    GetIndexesError,
    DropIndexError,
    DatabaseConnectionError,
    DatabaseAlreadyExistsError,
    DatabaseNotFoundError,
    DeleteCollectionError,
    DocumentDeleteError,
    DocumentInsertError,
    DocumentUpdateError,
    DocumentGetError,
    DocumentAggregationError,
    GetCollectionError,
    PublicIdCounterInitError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB: str = 'testdb'
COLL: str = 'framework.objects'


@pytest.fixture(name='mgr')
def _mgr() -> MongoDatabaseManager:
    """Builds a MongoDatabaseManager without its real __init__ (no connector / keepalive thread)."""
    manager = MongoDatabaseManager.__new__(MongoDatabaseManager)
    manager.db_name = DB
    manager.host = 'localhost'
    manager.port = 27017
    manager.client_options = {}
    manager.connector = MagicMock(name='connector')
    manager._keepalive_thread = None  # pylint: disable=protected-access
    return manager


def _stub_collection(mgr: MongoDatabaseManager) -> MagicMock:
    """Replaces mgr.get_collection with one returning a single mock collection, and returns it."""
    collection = MagicMock(name='collection')
    mgr.get_collection = MagicMock(return_value=collection)
    return collection


class TestTargetDatabaseAndContext:
    """target_database and the context-manager entry."""

    def test_target_database_uses_given(self, mgr: MongoDatabaseManager) -> None:
        """An explicit db_name is returned as-is."""
        assert mgr.target_database('other') == 'other'

    def test_target_database_falls_back_to_default(self, mgr: MongoDatabaseManager) -> None:
        """An empty db_name falls back to the manager default."""
        assert mgr.target_database('') == DB

    def test_enter_returns_self(self, mgr: MongoDatabaseManager) -> None:
        """__enter__ returns the manager (the class defines no __exit__, so call it directly)."""
        assert mgr.__enter__() is mgr  # pylint: disable=unnecessary-dunder-call


class TestDatabaseOperations:
    """check/create/drop database + collection management wrap failures as typed errors."""

    def test_check_database_exists_true(self, mgr: MongoDatabaseManager) -> None:
        """A present database name is reported as existing."""
        mgr.connector.client.list_database_names.return_value = [DB, 'other']

        assert mgr.check_database_exists(DB) is True

    def test_check_database_exists_error(self, mgr: MongoDatabaseManager) -> None:
        """A listing failure surfaces as DatabaseConnectionError."""
        mgr.connector.client.list_database_names.side_effect = RuntimeError('boom')

        with pytest.raises(DatabaseConnectionError):
            mgr.check_database_exists(DB)

    def test_create_database_returns_handle(self, mgr: MongoDatabaseManager) -> None:
        """Creating a not-yet-existing database returns its client handle."""
        mgr.connector.client.list_database_names.return_value = ['other']
        mgr.connector.client.__getitem__.return_value = 'db-handle'

        assert mgr.create_database('new') == 'db-handle'

    def test_create_database_already_exists(self, mgr: MongoDatabaseManager) -> None:
        """Creating an existing database raises DatabaseAlreadyExistsError."""
        mgr.connector.client.list_database_names.return_value = [DB]

        with pytest.raises(DatabaseAlreadyExistsError):
            mgr.create_database(DB)

    def test_create_database_connection_error(self, mgr: MongoDatabaseManager) -> None:
        """An unexpected failure surfaces as DatabaseConnectionError."""
        mgr.connector.client.list_database_names.side_effect = RuntimeError('boom')

        with pytest.raises(DatabaseConnectionError):
            mgr.create_database('new')

    def test_drop_database_by_name(self, mgr: MongoDatabaseManager) -> None:
        """An existing database is dropped by name."""
        mgr.connector.client.list_database_names.return_value = [DB]

        mgr.drop_database(DB)

        mgr.connector.client.drop_database.assert_called_once_with(DB)

    def test_drop_database_by_instance(self, mgr: MongoDatabaseManager) -> None:
        """A Database instance is resolved to its name before dropping."""
        database = MagicMock(spec=Database)
        database.name = DB
        mgr.connector.client.list_database_names.return_value = [DB]

        mgr.drop_database(database)

        mgr.connector.client.drop_database.assert_called_once_with(DB)

    def test_drop_database_not_found(self, mgr: MongoDatabaseManager) -> None:
        """Dropping a missing database raises DatabaseNotFoundError."""
        mgr.connector.client.list_database_names.return_value = ['other']

        with pytest.raises(DatabaseNotFoundError):
            mgr.drop_database('missing')

    def test_drop_database_connection_error(self, mgr: MongoDatabaseManager) -> None:
        """An unexpected failure surfaces as DatabaseConnectionError."""
        mgr.connector.client.list_database_names.side_effect = RuntimeError('boom')

        with pytest.raises(DatabaseConnectionError):
            mgr.drop_database(DB)

    def test_create_collection_creates_when_absent(self, mgr: MongoDatabaseManager) -> None:
        """A not-yet-existing collection is created and its name returned."""
        database = mgr.connector.get_database.return_value
        database.list_collection_names.return_value = []

        assert mgr.create_collection(COLL, DB) == COLL
        database.create_collection.assert_called_once_with(COLL)

    def test_create_collection_skips_when_present(self, mgr: MongoDatabaseManager) -> None:
        """An existing collection is not re-created."""
        database = mgr.connector.get_database.return_value
        database.list_collection_names.return_value = [COLL]

        assert mgr.create_collection(COLL, DB) == COLL
        database.create_collection.assert_not_called()

    def test_create_collection_invalid_maps_to_already_exists(self, mgr: MongoDatabaseManager) -> None:
        """A CollectionInvalid failure surfaces as CollectionAlreadyExistsError."""
        database = mgr.connector.get_database.return_value
        database.list_collection_names.return_value = []
        database.create_collection.side_effect = CollectionInvalid('exists')

        with pytest.raises(CollectionAlreadyExistsError):
            mgr.create_collection(COLL, DB)

    def test_create_collection_other_error(self, mgr: MongoDatabaseManager) -> None:
        """Any other failure surfaces as DatabaseConnectionError."""
        mgr.connector.get_database.side_effect = RuntimeError('boom')

        with pytest.raises(DatabaseConnectionError):
            mgr.create_collection(COLL, DB)

    def test_get_collection_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure resolving a collection surfaces as GetCollectionError."""
        mgr.connector.get_database.side_effect = RuntimeError('boom')

        with pytest.raises(GetCollectionError):
            mgr.get_collection(COLL, DB)

    def test_delete_collection_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure dropping a collection surfaces as DeleteCollectionError."""
        mgr.connector.get_database.return_value.drop_collection.side_effect = RuntimeError('boom')

        with pytest.raises(DeleteCollectionError):
            mgr.delete_collection(COLL, DB)

    def test_create_indexes_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure creating indexes surfaces as CreateIndexesError."""
        _stub_collection(mgr).create_indexes.side_effect = RuntimeError('boom')

        with pytest.raises(CreateIndexesError):
            mgr.create_indexes(COLL, DB, [])

    def test_get_index_info_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure reading index info surfaces as GetIndexesError."""
        _stub_collection(mgr).index_information.side_effect = RuntimeError('boom')

        with pytest.raises(GetIndexesError):
            mgr.get_index_info(COLL, DB)

    def test_drop_index_drops_an_existing_index(self, mgr: MongoDatabaseManager) -> None:
        """A present index is dropped and reported as dropped."""
        collection = _stub_collection(mgr)
        collection.index_information.return_value = {'object_id': {'key': [('object_id', 1)]}}

        assert mgr.drop_index(COLL, DB, 'object_id') is True
        collection.drop_index.assert_called_once_with('object_id')

    def test_drop_index_is_a_no_op_for_a_missing_index(self, mgr: MongoDatabaseManager) -> None:
        """An absent index is not an error - it reports False so a migration re-run stays safe."""
        collection = _stub_collection(mgr)
        collection.index_information.return_value = {'public_id': {'key': [('public_id', 1)]}}

        assert mgr.drop_index(COLL, DB, 'object_id') is False
        collection.drop_index.assert_not_called()

    def test_drop_index_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure dropping an existing index surfaces as DropIndexError."""
        collection = _stub_collection(mgr)
        collection.index_information.return_value = {'object_id': {'key': [('object_id', 1)]}}
        collection.drop_index.side_effect = RuntimeError('boom')

        with pytest.raises(DropIndexError):
            mgr.drop_index(COLL, DB, 'object_id')


class TestInsert:
    """insert covers skip-public, the duplicate-key retry loop and the typed-error mapping."""

    def test_skip_public_inserts_as_is(self, mgr: MongoDatabaseManager) -> None:
        """With skip_public the document is inserted unchanged and its public_id (if any) returned."""
        collection = _stub_collection(mgr)

        assert mgr.insert(COLL, DB, {'public_id': 7, '_id': 'x'}, skip_public=True) == 7
        collection.insert_one.assert_called_once()

    def test_assigns_public_id_and_inserts(self, mgr: MongoDatabaseManager) -> None:
        """A document without a public_id is assigned the next id and inserted."""
        _stub_collection(mgr)
        mgr.get_next_public_id = MagicMock(return_value=42)

        assert mgr.insert(COLL, DB, {'name': 'x'}) == 42

    def test_retries_on_duplicate_then_succeeds(self, mgr: MongoDatabaseManager) -> None:
        """A duplicate public_id is retried with a fresh id until the insert succeeds."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = [DuplicateKeyError('dup'), None]
        mgr.get_next_public_id = MagicMock(side_effect=[5, 6])

        assert mgr.insert(COLL, DB, {'name': 'x'}) == 6

    def test_exhausts_duplicate_retries(self, mgr: MongoDatabaseManager) -> None:
        """Persistent duplicate keys exhaust the retries and raise DocumentInsertError."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = DuplicateKeyError('dup')
        mgr.get_next_public_id = MagicMock(side_effect=range(1, MAX_DUPLICATE_KEY_RETRIES + 5))

        with pytest.raises(DocumentInsertError):
            mgr.insert(COLL, DB, {'name': 'x'})

    def test_execution_timeout_maps_to_lock_timeout(self, mgr: MongoDatabaseManager) -> None:
        """An ExecutionTimeout surfaces as DocumentLockTimeoutError (not re-wrapped as InsertError)."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = ExecutionTimeout('slow')
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentLockTimeoutError):
            mgr.insert(COLL, DB, {'name': 'x'})

    def test_operation_failure_lock_code_maps_to_lock_timeout(self, mgr: MongoDatabaseManager) -> None:
        """An OperationFailure carrying the lock-timeout code surfaces as DocumentLockTimeoutError."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = OperationFailure('lock', code=MONGO_LOCK_TIMEOUT_ERROR_CODE)
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentLockTimeoutError):
            mgr.insert(COLL, DB, {'name': 'x'})

    def test_operation_failure_other_code_maps_to_insert_error(self, mgr: MongoDatabaseManager) -> None:
        """An OperationFailure with any other code surfaces as DocumentInsertError."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = OperationFailure('nope', code=1)
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentInsertError):
            mgr.insert(COLL, DB, {'name': 'x'})

    def test_network_error_maps_to_network_error(self, mgr: MongoDatabaseManager) -> None:
        """A network/timeout error surfaces as DocumentNetworkError."""
        collection = _stub_collection(mgr)
        collection.insert_one.side_effect = NetworkTimeout('net')
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentNetworkError):
            mgr.insert(COLL, DB, {'name': 'x'})


class TestInsertManyAndBulk:
    """insert_many / bulk_write happy and error paths."""

    def test_insert_many_empty(self, mgr: MongoDatabaseManager) -> None:
        """An empty payload short-circuits to an empty id list."""
        assert mgr.insert_many(COLL, DB, []) == []

    def test_insert_many_assigns_ids(self, mgr: MongoDatabaseManager) -> None:
        """Documents without public_ids are assigned and returned."""
        _stub_collection(mgr)
        mgr.get_next_public_id = MagicMock(side_effect=[10, 11])

        assert mgr.insert_many(COLL, DB, [{'name': 'a'}, {'name': 'b'}]) == [10, 11]

    def test_insert_many_duplicate_error(self, mgr: MongoDatabaseManager) -> None:
        """A duplicate key surfaces as DocumentInsertError."""
        _stub_collection(mgr).insert_many.side_effect = DuplicateKeyError('dup')

        with pytest.raises(DocumentInsertError):
            mgr.insert_many(COLL, DB, [{'public_id': 1}], skip_public=True)

    def test_insert_many_network_error(self, mgr: MongoDatabaseManager) -> None:
        """A network/timeout error surfaces as DocumentNetworkError."""
        _stub_collection(mgr).insert_many.side_effect = NetworkTimeout('net')

        with pytest.raises(DocumentNetworkError):
            mgr.insert_many(COLL, DB, [{'public_id': 1}], skip_public=True)

    def test_insert_many_generic_error(self, mgr: MongoDatabaseManager) -> None:
        """An unexpected error surfaces as DocumentInsertError."""
        _stub_collection(mgr).insert_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentInsertError):
            mgr.insert_many(COLL, DB, [{'public_id': 1}], skip_public=True)

    def test_bulk_write_batches(self, mgr: MongoDatabaseManager) -> None:
        """bulk_write forwards the operations to the collection."""
        collection = _stub_collection(mgr)

        mgr.bulk_write(COLL, DB, [MagicMock(), MagicMock()])

        collection.bulk_write.assert_called_once()

    def test_bulk_write_error(self, mgr: MongoDatabaseManager) -> None:
        """A bulk-write failure surfaces as DocumentInsertError."""
        _stub_collection(mgr).bulk_write.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentInsertError):
            mgr.bulk_write(COLL, DB, [MagicMock()])


class TestPublicIdCounters:
    """The public_id counter helpers cover their peek/reserve/init/update branches."""

    def test_init_counter_seeds_from_highest(self, mgr: MongoDatabaseManager) -> None:
        """init_public_id_counter seeds the counter from the collection's highest id."""
        mgr.get_highest_id = MagicMock(return_value=17)
        _stub_collection(mgr)

        assert mgr.init_public_id_counter(COLL, DB) == 17

    def test_init_counter_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure seeding the counter surfaces as PublicIdCounterInitError."""
        mgr.get_highest_id = MagicMock(side_effect=RuntimeError('boom'))

        with pytest.raises(PublicIdCounterInitError):
            mgr.init_public_id_counter(COLL, DB)

    def test_get_next_public_id_peek_existing(self, mgr: MongoDatabaseManager) -> None:
        """Peeking returns counter + 1 when a counter document exists."""
        _stub_collection(mgr).find_one.return_value = {'counter': 4}

        assert mgr.get_next_public_id(COLL, DB) == 5

    def test_get_next_public_id_peek_missing(self, mgr: MongoDatabaseManager) -> None:
        """Peeking returns 1 when no counter document exists."""
        _stub_collection(mgr).find_one.return_value = None

        assert mgr.get_next_public_id(COLL, DB) == 1

    def test_get_next_public_id_reserve(self, mgr: MongoDatabaseManager) -> None:
        """With inc_id the next id is reserved via reserve_public_ids."""
        mgr.reserve_public_ids = MagicMock(return_value=[9])

        assert mgr.get_next_public_id(COLL, DB, inc_id=True) == 9

    def test_get_next_public_id_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure surfaces as DocumentGetError."""
        _stub_collection(mgr).find_one.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.get_next_public_id(COLL, DB)

    def test_reserve_public_ids_range(self, mgr: MongoDatabaseManager) -> None:
        """reserve_public_ids returns the contiguous reserved range."""
        _stub_collection(mgr).find_one_and_update.return_value = {'counter': 12}

        assert mgr.reserve_public_ids(COLL, DB, 3) == [10, 11, 12]

    def test_reserve_public_ids_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure reserving ids surfaces as DocumentGetError."""
        _stub_collection(mgr).find_one_and_update.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.reserve_public_ids(COLL, DB, 2)

    def test_update_counter_increment_existing(self, mgr: MongoDatabaseManager) -> None:
        """Incrementing an existing counter issues a single $inc."""
        collection = _stub_collection(mgr)
        collection.update_one.return_value = MagicMock(matched_count=1)

        mgr.update_public_id_counter(COLL, DB, increment=True)

        collection.update_one.assert_called_once()
        collection.insert_one.assert_not_called()

    def test_update_counter_increment_creates_when_missing(self, mgr: MongoDatabaseManager) -> None:
        """Incrementing a missing counter creates it starting at 1."""
        collection = _stub_collection(mgr)
        collection.update_one.return_value = MagicMock(matched_count=0)

        mgr.update_public_id_counter(COLL, DB, increment=True)

        collection.insert_one.assert_called_once()

    def test_update_counter_set_creates_when_missing(self, mgr: MongoDatabaseManager) -> None:
        """Setting a value on a missing counter creates it (clamped to >= 1)."""
        collection = _stub_collection(mgr)
        collection.find_one.return_value = None

        mgr.update_public_id_counter(COLL, DB, value=5)

        collection.insert_one.assert_called_once()

    def test_update_counter_set_higher(self, mgr: MongoDatabaseManager) -> None:
        """Setting a higher value updates the existing counter."""
        collection = _stub_collection(mgr)
        collection.find_one.return_value = {'counter': 2}

        mgr.update_public_id_counter(COLL, DB, value=9)

        collection.update_one.assert_called_once()

    def test_update_counter_set_lower_is_noop(self, mgr: MongoDatabaseManager) -> None:
        """Setting a value not greater than the current counter changes nothing."""
        collection = _stub_collection(mgr)
        collection.find_one.return_value = {'counter': 20}

        mgr.update_public_id_counter(COLL, DB, value=9)

        collection.update_one.assert_not_called()

    def test_update_counter_no_operation(self, mgr: MongoDatabaseManager) -> None:
        """Neither increment nor value raises DocumentUpdateError."""
        _stub_collection(mgr)

        with pytest.raises(DocumentUpdateError):
            mgr.update_public_id_counter(COLL, DB)

    def test_update_counter_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure surfaces as DocumentUpdateError."""
        mgr.get_collection = MagicMock(side_effect=RuntimeError('boom'))

        with pytest.raises(DocumentUpdateError):
            mgr.update_public_id_counter(COLL, DB, increment=True)


class TestReadHelpers:
    """The read wrappers map failures to typed errors and handle the highest-id edges."""

    def test_get_distinct_error(self, mgr: MongoDatabaseManager) -> None:
        """A distinct failure surfaces as DocumentGetError."""
        _stub_collection(mgr).distinct.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.get_distinct(COLL, DB, 'field', {})

    def test_find_all_error(self, mgr: MongoDatabaseManager) -> None:
        """A find_all failure surfaces as DocumentGetError."""
        _stub_collection(mgr).find.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.find_all(COLL, DB)

    def test_find_error(self, mgr: MongoDatabaseManager) -> None:
        """A find failure surfaces as DocumentGetError."""
        _stub_collection(mgr).find.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.find(COLL, DB)

    def test_find_one_by_error(self, mgr: MongoDatabaseManager) -> None:
        """A find_one_by failure surfaces as DocumentGetError."""
        _stub_collection(mgr).find.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.find_one_by(COLL, DB)

    def test_count_error(self, mgr: MongoDatabaseManager) -> None:
        """A count failure surfaces as DocumentGetError."""
        _stub_collection(mgr).count_documents.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentGetError):
            mgr.count(COLL, DB)

    def test_count_without_limit_counts_every_match(self, mgr: MongoDatabaseManager) -> None:
        """Without a limit the driver is called with the criteria alone (no limit keyword)."""
        collection = _stub_collection(mgr)
        collection.count_documents.return_value = 7

        assert mgr.count(COLL, DB, {'public_id': 1}) == 7
        collection.count_documents.assert_called_once_with({'public_id': 1})

    def test_count_passes_the_limit_to_the_driver(self, mgr: MongoDatabaseManager) -> None:
        """A limit is forwarded so the server can stop counting (the existence-probe case)."""
        collection = _stub_collection(mgr)
        collection.count_documents.return_value = 1

        assert mgr.count(COLL, DB, {'public_id': 1}, limit=1) == 1
        collection.count_documents.assert_called_once_with({'public_id': 1}, limit=1)

    def test_get_highest_id_found(self, mgr: MongoDatabaseManager) -> None:
        """The highest public_id is returned from the top-sorted document."""
        mgr.find_one_by = MagicMock(return_value={'public_id': 88})

        assert mgr.get_highest_id(COLL, DB) == 88

    def test_get_highest_id_none(self, mgr: MongoDatabaseManager) -> None:
        """An empty collection yields a highest id of 0."""
        mgr.find_one_by = MagicMock(return_value=None)

        assert mgr.get_highest_id(COLL, DB) == 0

    def test_get_highest_id_error(self, mgr: MongoDatabaseManager) -> None:
        """A failure surfaces as DocumentGetError."""
        mgr.find_one_by = MagicMock(side_effect=RuntimeError('boom'))

        with pytest.raises(DocumentGetError):
            mgr.get_highest_id(COLL, DB)


class TestUpdateAndDeleteErrors:
    """The update/delete wrappers map failures to typed errors."""

    def test_update_error(self, mgr: MongoDatabaseManager) -> None:
        """An update failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_one.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.update(COLL, DB, {'public_id': 1}, {'x': 1})

    def test_update_many_error(self, mgr: MongoDatabaseManager) -> None:
        """An update_many failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.update_many(COLL, DB, {}, {'x': 1})

    def test_update_many_raw_error(self, mgr: MongoDatabaseManager) -> None:
        """An update_many_raw failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.update_many_raw(COLL, DB, {}, {'$set': {'x': 1}})

    def test_delete_error(self, mgr: MongoDatabaseManager) -> None:
        """A delete failure surfaces as DocumentDeleteError."""
        _stub_collection(mgr).delete_one.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentDeleteError):
            mgr.delete(COLL, DB, {'public_id': 1})

    def test_delete_many_error(self, mgr: MongoDatabaseManager) -> None:
        """A delete_many failure surfaces as DocumentDeleteError."""
        _stub_collection(mgr).delete_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentDeleteError):
            mgr.delete_many(COLL, DB, public_id=1)

    def test_delete_many_raw_error(self, mgr: MongoDatabaseManager) -> None:
        """A delete_many_raw failure surfaces as DocumentDeleteError."""
        _stub_collection(mgr).delete_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentDeleteError):
            mgr.delete_many_raw(COLL, DB, {'public_id': 1})


class TestUpsertAndMoreWrappers:
    """status, upsert(_set), unset_update_many, update_many_pull, aggregate and find_one paths."""

    def test_status_delegates(self, mgr: MongoDatabaseManager) -> None:
        """status reports the connector's connection state."""
        mgr.connector.is_connected.return_value = True

        assert mgr.status() is True

    def test_upsert_set_bumps_counter_on_insert(self, mgr: MongoDatabaseManager) -> None:
        """When upsert_set inserts a new document it bumps the public_id counter."""
        collection = _stub_collection(mgr)
        collection.update_one.return_value = MagicMock(upserted_id='new')
        mgr.update_public_id_counter = MagicMock()

        mgr.upsert_set(COLL, DB, {'public_id': 3})

        mgr.update_public_id_counter.assert_called_once()

    def test_upsert_set_no_counter_on_update(self, mgr: MongoDatabaseManager) -> None:
        """An in-place update (no upsert) does not touch the counter."""
        collection = _stub_collection(mgr)
        collection.update_one.return_value = MagicMock(upserted_id=None)
        mgr.update_public_id_counter = MagicMock()

        mgr.upsert_set(COLL, DB, {'public_id': 3})

        mgr.update_public_id_counter.assert_not_called()

    def test_upsert_set_error(self, mgr: MongoDatabaseManager) -> None:
        """An upsert_set failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_one.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.upsert_set(COLL, DB, {'public_id': 3})

    def test_upsert_delegates(self, mgr: MongoDatabaseManager) -> None:
        """upsert issues an update_one with upsert=True."""
        collection = _stub_collection(mgr)

        mgr.upsert(COLL, DB, {'_id': 'x'}, {'a': 1})

        collection.update_one.assert_called_once()

    def test_upsert_error(self, mgr: MongoDatabaseManager) -> None:
        """An upsert failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_one.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.upsert(COLL, DB, {'_id': 'x'}, {'a': 1})

    def test_unset_update_many_delegates(self, mgr: MongoDatabaseManager) -> None:
        """unset_update_many removes a field across matching documents."""
        collection = _stub_collection(mgr)

        mgr.unset_update_many(COLL, DB, {}, 'stale')

        collection.update_many.assert_called_once()

    def test_unset_update_many_error(self, mgr: MongoDatabaseManager) -> None:
        """An unset failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.unset_update_many(COLL, DB, {}, 'stale')

    def test_update_many_pull_error(self, mgr: MongoDatabaseManager) -> None:
        """An update_many_pull failure surfaces as DocumentUpdateError."""
        _stub_collection(mgr).update_many.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentUpdateError):
            mgr.update_many_pull(COLL, DB, {}, {'field': 1})

    def test_aggregate_delegates(self, mgr: MongoDatabaseManager) -> None:
        """aggregate forwards the pipeline to the collection."""
        collection = _stub_collection(mgr)

        mgr.aggregate(COLL, DB, [{'$match': {}}])

        collection.aggregate.assert_called_once()

    def test_aggregate_error(self, mgr: MongoDatabaseManager) -> None:
        """An aggregation failure surfaces as DocumentAggregationError."""
        _stub_collection(mgr).aggregate.side_effect = RuntimeError('boom')

        with pytest.raises(DocumentAggregationError):
            mgr.aggregate(COLL, DB, [{'$match': {}}])

    def test_find_one_error(self, mgr: MongoDatabaseManager) -> None:
        """A find_one failure surfaces as DocumentGetError."""
        mgr.find = MagicMock(side_effect=RuntimeError('boom'))

        with pytest.raises(DocumentGetError):
            mgr.find_one(COLL, DB, 1)


class TestWriteHappyPaths:
    """The update/delete wrappers forward to pymongo on the happy path."""

    def test_update_delegates(self, mgr: MongoDatabaseManager) -> None:
        """update wraps the data in $set and calls update_one."""
        collection = _stub_collection(mgr)

        mgr.update(COLL, DB, {'public_id': 1}, {'x': 1})

        collection.update_one.assert_called_once()

    def test_update_many_delegates(self, mgr: MongoDatabaseManager) -> None:
        """update_many calls update_many on the collection."""
        collection = _stub_collection(mgr)

        mgr.update_many(COLL, DB, {}, {'x': 1})

        collection.update_many.assert_called_once()

    def test_delete_delegates(self, mgr: MongoDatabaseManager) -> None:
        """delete calls delete_one on the collection."""
        collection = _stub_collection(mgr)

        mgr.delete(COLL, DB, {'public_id': 1})

        collection.delete_one.assert_called_once()

    def test_delete_many_delegates(self, mgr: MongoDatabaseManager) -> None:
        """delete_many calls delete_many on the collection."""
        collection = _stub_collection(mgr)

        mgr.delete_many(COLL, DB, public_id=1)

        collection.delete_many.assert_called_once()


class TestUpdateVariantBranches:
    """The update/read wrappers cover their plain / add_to_set / array-filter / projection branches."""

    def test_update_plain_passes_data_verbatim(self, mgr: MongoDatabaseManager) -> None:
        """plain=True passes the update document through without a $set wrapper."""
        collection = _stub_collection(mgr)

        mgr.update(COLL, DB, {'public_id': 1}, {'$inc': {'n': 1}}, plain=True)

        assert collection.update_one.call_args.args[1] == {'$inc': {'n': 1}}

    def test_update_many_add_to_set_branch(self, mgr: MongoDatabaseManager) -> None:
        """add_to_set=True wraps the update in $addToSet."""
        collection = _stub_collection(mgr)

        mgr.update_many(COLL, DB, {}, {'tags': 'x'}, add_to_set=True)

        assert '$addToSet' in collection.update_many.call_args.args[1]

    def test_update_many_plain_branch(self, mgr: MongoDatabaseManager) -> None:
        """plain=True passes the update document through unchanged."""
        collection = _stub_collection(mgr)

        mgr.update_many(COLL, DB, {}, {'$set': {'x': 1}}, plain=True)

        assert collection.update_many.call_args.args[1] == {'$set': {'x': 1}}

    def test_update_many_pull_wraps_in_pull(self, mgr: MongoDatabaseManager) -> None:
        """update_many_pull wraps the update in a $pull operator."""
        collection = _stub_collection(mgr)

        mgr.update_many_pull(COLL, DB, {}, {'types_filter': 5})

        assert collection.update_many.call_args.args[1] == {'$pull': {'types_filter': 5}}

    def test_update_many_raw_with_array_filters(self, mgr: MongoDatabaseManager) -> None:
        """update_many_raw forwards array_filters when given."""
        collection = _stub_collection(mgr)

        mgr.update_many_raw(COLL, DB, {}, {'$set': {'x': 1}}, array_filters=[{'e.k': 1}])

        assert collection.update_many.call_args.kwargs['array_filters'] == [{'e.k': 1}]

    def test_get_distinct_returns_values(self, mgr: MongoDatabaseManager) -> None:
        """get_distinct returns the collection's distinct values."""
        _stub_collection(mgr).distinct.return_value = ['a', 'b']

        assert mgr.get_distinct(COLL, DB, 'field', {}) == ['a', 'b']

    def test_find_defaults_projection_excluding_id(self, mgr: MongoDatabaseManager) -> None:
        """find defaults to a projection excluding _id when none is given."""
        collection = _stub_collection(mgr)

        mgr.find(COLL, DB, {})

        assert collection.find.call_args.kwargs['projection'] == {'_id': 0}

    def test_find_keeps_explicit_projection(self, mgr: MongoDatabaseManager) -> None:
        """An explicit projection is preserved."""
        collection = _stub_collection(mgr)

        mgr.find(COLL, DB, {}, projection={'name': 1})

        assert collection.find.call_args.kwargs['projection'] == {'name': 1}

    def test_find_all_returns_list(self, mgr: MongoDatabaseManager) -> None:
        """find_all materialises the cursor into a list."""
        _stub_collection(mgr).find.return_value = iter([{'public_id': 1}, {'public_id': 2}])

        assert mgr.find_all(COLL, DB) == [{'public_id': 1}, {'public_id': 2}]

    def test_find_one_by_returns_first(self, mgr: MongoDatabaseManager) -> None:
        """find_one_by returns the first matching document."""
        _stub_collection(mgr).find.return_value = iter([{'public_id': 5}])

        assert mgr.find_one_by(COLL, DB) == {'public_id': 5}

    def test_find_one_by_returns_none(self, mgr: MongoDatabaseManager) -> None:
        """find_one_by returns None when nothing matches."""
        _stub_collection(mgr).find.return_value = iter([])

        assert mgr.find_one_by(COLL, DB) is None

    def test_find_one_returns_document(self, mgr: MongoDatabaseManager) -> None:
        """find_one returns the single document for the given public_id."""
        cursor = MagicMock()
        cursor.limit.return_value = iter([{'public_id': 9}])
        mgr.find = MagicMock(return_value=cursor)

        assert mgr.find_one(COLL, DB, 9) == {'public_id': 9}

    def test_insert_many_skip_public_returns_ids(self, mgr: MongoDatabaseManager) -> None:
        """With skip_public the ids are read straight off the given documents."""
        _stub_collection(mgr)

        assert mgr.insert_many(COLL, DB, [{'public_id': 1}, {'public_id': 2}], skip_public=True) == [1, 2]


class TestInitAndReset:
    """__init__ and reset_connection build the connector without the real MongoDB / keepalive thread."""

    def test_init_local_disables_ssl(self, monkeypatch) -> None:
        """Local mode builds the connector with SSL disabled."""
        monkeypatch.setattr(mdm, 'MongoConnector', MagicMock())
        monkeypatch.setattr(MongoDatabaseManager, '_start_keepalive', lambda self: None)

        manager = MongoDatabaseManager('h', 27017, DB, mode='local')

        assert manager.client_options['ssl'] is False

    def test_init_cloud_enables_ssl(self, monkeypatch) -> None:
        """Cloud mode builds the connector with SSL enabled."""
        monkeypatch.setattr(mdm, 'MongoConnector', MagicMock())
        monkeypatch.setattr(MongoDatabaseManager, '_start_keepalive', lambda self: None)

        manager = MongoDatabaseManager('h', 27017, DB, mode='cloud')

        assert manager.client_options['ssl'] is True

    def test_reset_connection_rebuilds_connector(self, mgr: MongoDatabaseManager, monkeypatch) -> None:
        """reset_connection disconnects the old connector and builds a fresh one."""
        old_connector = mgr.connector
        monkeypatch.setattr(mdm, 'MongoConnector', MagicMock(return_value='fresh'))
        monkeypatch.setattr(MongoDatabaseManager, '_start_keepalive', lambda self: None)

        mgr.reset_connection()

        old_connector.disconnect.assert_called_once()
        assert mgr.connector == 'fresh'


class TestRemainingBranches:
    """The last edge branches: insert generic error, no-match unset, empty find_one, kept ids."""

    def test_insert_generic_error(self, mgr: MongoDatabaseManager) -> None:
        """A non-pymongo error during insert surfaces as DocumentInsertError."""
        _stub_collection(mgr).insert_one.side_effect = RuntimeError('boom')
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentInsertError):
            mgr.insert(COLL, DB, {'name': 'x'})

    def test_unset_update_many_logs_when_none_matched(self, mgr: MongoDatabaseManager) -> None:
        """When no documents match, unset_update_many still returns (logging a warning)."""
        _stub_collection(mgr).update_many.return_value = MagicMock(modified_count=0)

        mgr.unset_update_many(COLL, DB, {}, 'stale')

    def test_find_one_returns_none_when_absent(self, mgr: MongoDatabaseManager) -> None:
        """find_one returns None when the cursor yields no document."""
        cursor = MagicMock()
        cursor.limit.return_value = iter([])
        mgr.find = MagicMock(return_value=cursor)

        assert mgr.find_one(COLL, DB, 1) is None

    def test_insert_many_keeps_existing_ids(self, mgr: MongoDatabaseManager) -> None:
        """Documents already carrying a public_id keep it (no reassignment) in the non-skip path."""
        _stub_collection(mgr)

        assert mgr.insert_many(COLL, DB, [{'public_id': 7, 'name': 'x'}]) == [7]
