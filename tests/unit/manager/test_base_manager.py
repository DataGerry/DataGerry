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
Unit tests for cmdb.manager.base_manager.BaseManager

Pure tests: no Mongo. Each method is invoked unbound with a MagicMock standing in for the manager
instance, so self.dbm / self.query_builder / self.aggregate are stubbed and only the method's own
logic (id assignment, total extraction, criteria defaulting, the col / collection branches, the
delete boolean and the exception mapping) is exercised. The logic-bearing methods get dedicated
tests; the thin dbm delegations are covered by the parametrized error-mapping table at the bottom,
which pins that each one rewraps its database error as the matching BaseManager* error
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.base_manager import BaseManager
from cmdb.errors.database import (
    DocumentInsertError,
    DocumentGetError,
    DocumentUpdateError,
    DocumentDeleteError,
    DocumentAggregationError,
)
from cmdb.errors.manager import (
    BaseManagerInitError,
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'framework.stub'
DB_NAME: str = 'test-db'


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a BaseManager, wired with a collection + database name."""
    mgr = MagicMock()
    mgr.collection = COLLECTION
    mgr.db_name = DB_NAME
    return mgr


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   insert_many                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_insert_many_skip_public_delegates_without_id_generation() -> None:
    """skip_public=True inserts the documents as-is and never generates a public_id"""
    mgr = _mock_manager()
    docs = [{'public_id': 1}, {'public_id': 2}]

    BaseManager.insert_many(mgr, docs, skip_public=True)

    mgr.dbm.insert_many.assert_called_once_with(COLLECTION, DB_NAME, docs, True)
    mgr.dbm.get_next_public_id.assert_not_called()


def test_insert_many_assigns_public_id_to_documents_missing_one() -> None:
    """With skip_public=False, every document without a public_id gets the next generated one"""
    mgr = _mock_manager()
    mgr.dbm.get_next_public_id.side_effect = [10, 11]
    docs = [{'name': 'a'}, {'name': 'b'}]

    BaseManager.insert_many(mgr, docs)

    assert docs[0]['public_id'] == 10
    assert docs[1]['public_id'] == 11
    mgr.dbm.insert_many.assert_called_once_with(COLLECTION, DB_NAME, docs)


def test_insert_many_preserves_existing_public_id() -> None:
    """A document that already carries a public_id is left untouched; only missing ones are filled"""
    mgr = _mock_manager()
    mgr.dbm.get_next_public_id.side_effect = [10]
    docs = [{'public_id': 99}, {'name': 'b'}]

    BaseManager.insert_many(mgr, docs)

    assert docs[0]['public_id'] == 99
    assert docs[1]['public_id'] == 10
    mgr.dbm.get_next_public_id.assert_called_once_with(COLLECTION, DB_NAME, inc_id=True)


def test_insert_many_wraps_failure() -> None:
    """Any failure during a bulk insert is wrapped in BaseManagerInsertError"""
    mgr = _mock_manager()
    mgr.dbm.insert_many.side_effect = RuntimeError('boom')

    with pytest.raises(BaseManagerInsertError):
        BaseManager.insert_many(mgr, [{'public_id': 1}], skip_public=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_from_other_collection                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_count_from_other_collection_delegates_to_other_collection() -> None:
    """Counts against the GIVEN collection (not the manager's own) with the manager's db + criteria"""
    mgr = _mock_manager()
    mgr.dbm.count.return_value = 3
    criteria = {'report_category_id': 5}

    result = BaseManager.count_from_other_collection(mgr, 'framework.reports', criteria)

    assert result == 3
    mgr.dbm.count.assert_called_once_with('framework.reports', DB_NAME, criteria)


def test_count_from_other_collection_wraps_failure() -> None:
    """A DocumentGetError from the count is wrapped in BaseManagerGetError"""
    mgr = _mock_manager()
    mgr.dbm.count.side_effect = DocumentGetError('boom')

    with pytest.raises(BaseManagerGetError):
        BaseManager.count_from_other_collection(mgr, 'framework.reports', {'x': 1})


def test_delete_many_from_other_collection_delegates_to_other_collection() -> None:
    """Deletes against the GIVEN collection (not the manager's own) with the manager's db + raw filter"""
    mgr = _mock_manager()
    mgr.dbm.delete_many_raw.return_value = 'delete-result'
    filter_query = {'risk_assessment_id': {'$in': [1, 2]}}

    result = BaseManager.delete_many_from_other_collection(mgr, 'isms.controlMeasureAssignment', filter_query)

    assert result == 'delete-result'
    mgr.dbm.delete_many_raw.assert_called_once_with(
        collection='isms.controlMeasureAssignment', db_name=DB_NAME, filter_query=filter_query
    )


def test_delete_many_from_other_collection_wraps_failure() -> None:
    """A DocumentDeleteError from the delete is wrapped in BaseManagerDeleteError"""
    mgr = _mock_manager()
    mgr.dbm.delete_many_raw.side_effect = DocumentDeleteError('boom')

    with pytest.raises(BaseManagerDeleteError):
        BaseManager.delete_many_from_other_collection(mgr, 'isms.controlMeasureAssignment', {'x': 1})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  aggregate_query                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_aggregate_query_returns_the_aggregated_documents() -> None:
    """The built data pipeline is aggregated and its rows returned as a list"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    docs = [{'public_id': 1}, {'public_id': 2}]
    mgr.aggregate.return_value = iter(docs)
    params = MagicMock()

    result = BaseManager.aggregate_query(mgr, params)

    assert result == docs
    mgr.query_builder.build.assert_called_once_with(params, None, None)
    mgr.aggregate.assert_called_once_with(['QUERY'])


def test_aggregate_query_runs_no_count_pipeline() -> None:
    """The whole point of the method: exactly one aggregation, and no count query is built"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    mgr.aggregate.return_value = iter([])

    BaseManager.aggregate_query(mgr, MagicMock())

    mgr.query_builder.count.assert_not_called()
    assert mgr.aggregate.call_count == 1


def test_aggregate_query_forwards_user_and_permission() -> None:
    """The ACL arguments reach the query builder unchanged"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = []
    mgr.aggregate.return_value = iter([])
    params, user, permission = MagicMock(), MagicMock(), MagicMock()

    BaseManager.aggregate_query(mgr, params, user, permission)

    mgr.query_builder.build.assert_called_once_with(params, user, permission)


def test_aggregate_query_wraps_failure() -> None:
    """A failure while building/aggregating is wrapped in BaseManagerIterationError"""
    mgr = _mock_manager()
    mgr.query_builder.build.side_effect = RuntimeError('boom')

    with pytest.raises(BaseManagerIterationError):
        BaseManager.aggregate_query(mgr, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  iterate_query                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iterate_query_returns_results_and_total() -> None:
    """Returns the rows from aggregate_query plus the total pulled from the count pipeline"""
    mgr = _mock_manager()
    docs = [{'public_id': 1}, {'public_id': 2}]
    mgr.aggregate_query.return_value = docs
    mgr.query_builder.count.return_value = ['COUNT']
    mgr.aggregate.return_value = iter([{'total': 7}])
    params = MagicMock()

    result = BaseManager.iterate_query(mgr, params)

    assert result == (docs, 7)


def test_iterate_query_delegates_the_data_half_to_aggregate_query() -> None:
    """The data pipeline is not rebuilt here - iterate_query is aggregate_query plus a count"""
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate.return_value = iter([])
    params, user, permission = MagicMock(), MagicMock(), MagicMock()

    BaseManager.iterate_query(mgr, params, user, permission)

    mgr.aggregate_query.assert_called_once_with(params, user, permission)
    # Only the count pipeline is aggregated directly; the data half went through aggregate_query
    assert mgr.aggregate.call_count == 1


def test_iterate_query_total_defaults_to_zero_when_count_empty() -> None:
    """An empty count cursor yields a total of 0 rather than raising"""
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate.return_value = iter([])

    result = BaseManager.iterate_query(mgr, MagicMock())

    assert result == ([], 0)


def test_iterate_query_wraps_failure() -> None:
    """A failure while aggregating the data half or the count is wrapped in BaseManagerIterationError"""
    mgr = _mock_manager()
    mgr.aggregate_query.side_effect = RuntimeError('boom')

    with pytest.raises(BaseManagerIterationError):
        BaseManager.iterate_query(mgr, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      find                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_defaults_criteria_to_empty_dict_when_none() -> None:
    """A None criteria becomes an empty filter"""
    mgr = _mock_manager()
    mgr.dbm.find.return_value = []

    BaseManager.find(mgr)

    mgr.dbm.find.assert_called_once_with(COLLECTION, DB_NAME, filter={})


def test_find_passes_given_criteria_and_returns_list() -> None:
    """The given criteria is forwarded as the filter and the cursor is materialised into a list"""
    mgr = _mock_manager()
    docs = [{'public_id': 1}]
    mgr.dbm.find.return_value = iter(docs)

    result = BaseManager.find(mgr, criteria={'type_id': 5})

    mgr.dbm.find.assert_called_once_with(COLLECTION, DB_NAME, filter={'type_id': 5})
    assert result == docs


def test_find_wraps_document_get_error() -> None:
    """A DocumentGetError from the database layer is wrapped in BaseManagerGetError"""
    mgr = _mock_manager()
    mgr.dbm.find.side_effect = DocumentGetError('boom')

    with pytest.raises(BaseManagerGetError):
        BaseManager.find(mgr, criteria={})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     update                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_uses_manager_collection_by_default() -> None:
    """Without col, the update targets this manager's own collection.

    add_to_set/plain are forwarded as KEYWORDS, never as trailing positionals - otherwise they
    would land in dbm.update's *args and reach update_one() as upsert=True (a silent-upsert bug)
    """
    mgr = _mock_manager()

    BaseManager.update(mgr, {'public_id': 1}, {'name': 'x'})

    mgr.dbm.update.assert_called_once_with(
        COLLECTION, DB_NAME, {'public_id': 1}, {'name': 'x'}, add_to_set=True, plain=False
    )


def test_update_uses_given_collection_when_collection_set() -> None:
    """A collection argument overrides the target collection"""
    mgr = _mock_manager()

    BaseManager.update(mgr, {'public_id': 1}, {'name': 'x'}, collection='other.collection')

    assert mgr.dbm.update.call_args.args[0] == 'other.collection'


def test_update_wraps_document_update_error() -> None:
    """A DocumentUpdateError is wrapped in BaseManagerUpdateError"""
    mgr = _mock_manager()
    mgr.dbm.update.side_effect = DocumentUpdateError('boom')

    with pytest.raises(BaseManagerUpdateError):
        BaseManager.update(mgr, {}, {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     upsert                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_upsert_uses_manager_collection_by_default() -> None:
    """Without a collection arg, the upsert targets this manager's own collection"""
    mgr = _mock_manager()

    BaseManager.upsert(mgr, {'_id': 'active'}, {'blob': 'x'})

    mgr.dbm.upsert.assert_called_once_with(COLLECTION, DB_NAME, {'_id': 'active'}, {'blob': 'x'})


def test_upsert_uses_given_collection_when_set() -> None:
    """A collection argument overrides the target collection"""
    mgr = _mock_manager()

    BaseManager.upsert(mgr, {'_id': 'active'}, {'blob': 'x'}, collection='other.collection')

    assert mgr.dbm.upsert.call_args.args[0] == 'other.collection'


def test_upsert_wraps_document_update_error() -> None:
    """A DocumentUpdateError is wrapped in BaseManagerUpdateError"""
    mgr = _mock_manager()
    mgr.dbm.upsert.side_effect = DocumentUpdateError('boom')

    with pytest.raises(BaseManagerUpdateError):
        BaseManager.upsert(mgr, {'_id': 'active'}, {'blob': 'x'})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     delete                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('acknowledged,deleted_count,expected', [
    (True, 1, True),
    (True, 0, False),
    (False, 2, False),
])
def test_delete_true_only_when_acknowledged_and_count_positive(
    acknowledged: bool, deleted_count: int, expected: bool,
) -> None:
    """delete() is True only when the result is acknowledged and at least one document was removed"""
    mgr = _mock_manager()
    mgr.dbm.delete.return_value = MagicMock(acknowledged=acknowledged, deleted_count=deleted_count)

    assert BaseManager.delete(mgr, {'public_id': 1}) is expected


def test_delete_uses_given_collection_when_set() -> None:
    """A collection argument overrides the target collection"""
    mgr = _mock_manager()
    mgr.dbm.delete.return_value = MagicMock(acknowledged=True, deleted_count=1)

    BaseManager.delete(mgr, {'public_id': 1}, collection='other.collection')

    assert mgr.dbm.delete.call_args.args[0] == 'other.collection'


def test_delete_wraps_document_delete_error() -> None:
    """A DocumentDeleteError is wrapped in BaseManagerDeleteError"""
    mgr = _mock_manager()
    mgr.dbm.delete.side_effect = DocumentDeleteError('boom')

    with pytest.raises(BaseManagerDeleteError):
        BaseManager.delete(mgr, {'public_id': 1})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   delete_many                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_many_spreads_filter_query_as_kwargs() -> None:
    """delete_many forwards the filter_query entries as keyword arguments (current behaviour)"""
    mgr = _mock_manager()

    BaseManager.delete_many(mgr, {'public_id': 5, 'active': True})

    mgr.dbm.delete_many.assert_called_once_with(collection=COLLECTION, db_name=DB_NAME, public_id=5, active=True)


def test_delete_many_wraps_document_delete_error() -> None:
    """A DocumentDeleteError is wrapped in BaseManagerDeleteError"""
    mgr = _mock_manager()
    mgr.dbm.delete_many.side_effect = DocumentDeleteError('boom')

    with pytest.raises(BaseManagerDeleteError):
        BaseManager.delete_many(mgr, {'public_id': 5})


# -------------------------------------------------------------------------------------------------------------------- #
#                                       __init__ + fully-uncovered delegations                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_wraps_failure_as_base_manager_init_error() -> None:
    """A failure while wiring the manager (here: a None dbm with no db_name) becomes BaseManagerInitError"""
    with pytest.raises(BaseManagerInitError):
        BaseManager(COLLECTION, None, None)


def test_get_distinct_delegates_and_returns_values() -> None:
    """get_distinct forwards the key + criteria to the dbm layer and returns the distinct values"""
    mgr = _mock_manager()
    mgr.dbm.get_distinct.return_value = ['a', 'b']

    result = BaseManager.get_distinct(mgr, 'type_id', {'active': True})

    mgr.dbm.get_distinct.assert_called_once_with(COLLECTION, DB_NAME, 'type_id', {'active': True})
    assert result == ['a', 'b']


def test_count_documents_forwards_the_limit() -> None:
    """count_documents passes the limit through, so an existence probe can stop at the first match"""
    mgr = _mock_manager()
    mgr.dbm.count.return_value = 1

    result = BaseManager.count_documents(mgr, {'relation_id': 5}, limit=1)

    mgr.dbm.count.assert_called_once_with(COLLECTION, DB_NAME, {'relation_id': 5}, 1)
    assert result == 1


def test_count_documents_defaults_to_no_limit() -> None:
    """Without a limit the delegation passes None, which counts every match"""
    mgr = _mock_manager()

    BaseManager.count_documents(mgr, {'relation_id': 5})

    mgr.dbm.count.assert_called_once_with(COLLECTION, DB_NAME, {'relation_id': 5}, None)


def test_delete_many_raw_delegates_with_filter_query() -> None:
    """delete_many_raw forwards the raw filter as filter_query and returns the delete result"""
    mgr = _mock_manager()
    sentinel = MagicMock(name='delete_result')
    mgr.dbm.delete_many_raw.return_value = sentinel

    result = BaseManager.delete_many_raw(mgr, {'public_id': {'$in': [1, 2]}})

    mgr.dbm.delete_many_raw.assert_called_once_with(
        collection=COLLECTION, db_name=DB_NAME, filter_query={'public_id': {'$in': [1, 2]}}
    )
    assert result is sentinel


# -------------------------------------------------------------------------------------------------------------------- #
#                                   delegation error-mapping (database -> manager)                                    #
# -------------------------------------------------------------------------------------------------------------------- #
# (method, args, dbm_attribute, raised database error, expected manager error)
_ERROR_MAPPING_CASES = [
    ('insert', ({},), 'insert', DocumentInsertError, BaseManagerInsertError),
    ('get_distinct', ('k', {}), 'get_distinct', DocumentGetError, BaseManagerGetError),
    ('get_one', (), 'find_one', DocumentGetError, BaseManagerGetError),
    ('get_one_from_other_collection', ('other', 5), 'find_one', DocumentGetError, BaseManagerGetError),
    ('get_many_from_other_collection', ('other',), 'find_all', DocumentGetError, BaseManagerGetError),
    ('get', (), 'find', DocumentGetError, BaseManagerGetError),
    ('get_one_by', ({'x': 1},), 'find_one_by', DocumentGetError, BaseManagerGetError),
    ('get_many', (), 'find_all', DocumentGetError, BaseManagerGetError),
    ('aggregate', ([],), 'aggregate', DocumentAggregationError, BaseManagerIterationError),
    ('aggregate_from_other_collection', ('other', []), 'aggregate',
     DocumentAggregationError, BaseManagerIterationError),
    ('get_next_public_id', (), 'get_next_public_id', DocumentGetError, BaseManagerGetError),
    ('reserve_public_ids', (5,), 'reserve_public_ids', DocumentGetError, BaseManagerGetError),
    ('count_documents', (), 'count', DocumentGetError, BaseManagerGetError),
    ('update_many', ({'x': 1}, {'y': 2}), 'update_many', DocumentUpdateError, BaseManagerUpdateError),
    ('update_many_pull', ({'x': 1}, {'$pull': {}}), 'update_many_pull', DocumentUpdateError, BaseManagerUpdateError),
    ('update_many_raw', ({'x': 1}, {'$set': {}}), 'update_many_raw', DocumentUpdateError, BaseManagerUpdateError),
    ('bulk_write', ([],), 'bulk_write', DocumentInsertError, BaseManagerUpdateError),
    ('delete_many_raw', ({'x': 1},), 'delete_many_raw', DocumentDeleteError, BaseManagerDeleteError),
]


@pytest.mark.parametrize(
    'method, args, dbm_attr, db_error, expected_error',
    _ERROR_MAPPING_CASES,
    ids=[case[0] for case in _ERROR_MAPPING_CASES],
)
def test_delegation_wraps_database_error(method, args, dbm_attr, db_error, expected_error) -> None:
    """Each thin delegation rewraps its database-layer error as the matching BaseManager* error"""
    mgr = _mock_manager()
    getattr(mgr.dbm, dbm_attr).side_effect = db_error('boom')

    with pytest.raises(expected_error):
        getattr(BaseManager, method)(mgr, *args)
