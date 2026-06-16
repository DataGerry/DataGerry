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
delete boolean and the exception mapping) is exercised. Only the logic-bearing methods are covered;
the thin one-line dbm delegations are intentionally left out
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.base_manager import BaseManager
from cmdb.errors.database import DocumentGetError, DocumentUpdateError, DocumentDeleteError
from cmdb.errors.manager import (
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
#                                                  iterate_query                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iterate_query_returns_results_and_total() -> None:
    """Returns the aggregated documents plus the total pulled from the count pipeline"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    mgr.query_builder.count.return_value = ['COUNT']
    docs = [{'public_id': 1}, {'public_id': 2}]
    mgr.aggregate.side_effect = [iter(docs), iter([{'total': 7}])]
    params = MagicMock()

    result = BaseManager.iterate_query(mgr, params)

    assert result == (docs, 7)
    mgr.query_builder.build.assert_called_once_with(params, None, None)


def test_iterate_query_total_defaults_to_zero_when_count_empty() -> None:
    """An empty count cursor yields a total of 0 rather than raising"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate.side_effect = [iter([]), iter([])]

    result = BaseManager.iterate_query(mgr, MagicMock())

    assert result == ([], 0)


def test_iterate_query_wraps_failure() -> None:
    """A failure while building/aggregating is wrapped in BaseManagerIterationError"""
    mgr = _mock_manager()
    mgr.query_builder.build.side_effect = RuntimeError('boom')

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

    mgr.dbm.find.assert_called_once_with(collection=COLLECTION, db_name=DB_NAME, filter={})


def test_find_passes_given_criteria_and_returns_list() -> None:
    """The given criteria is forwarded as the filter and the cursor is materialised into a list"""
    mgr = _mock_manager()
    docs = [{'public_id': 1}]
    mgr.dbm.find.return_value = iter(docs)

    result = BaseManager.find(mgr, criteria={'type_id': 5})

    mgr.dbm.find.assert_called_once_with(collection=COLLECTION, db_name=DB_NAME, filter={'type_id': 5})
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
    """Without col, the update targets this manager's own collection"""
    mgr = _mock_manager()

    BaseManager.update(mgr, {'public_id': 1}, {'name': 'x'})

    mgr.dbm.update.assert_called_once_with(COLLECTION, DB_NAME, {'public_id': 1}, {'name': 'x'}, True, False)


def test_update_uses_given_collection_when_col_set() -> None:
    """A col argument overrides the target collection"""
    mgr = _mock_manager()

    BaseManager.update(mgr, {'public_id': 1}, {'name': 'x'}, col='other.collection')

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
