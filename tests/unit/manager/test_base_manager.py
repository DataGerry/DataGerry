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
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.base_manager_constants import EMPTY_DELETE_FILTER_MSG
from cmdb.manager.query_builder import BuilderParameters
from cmdb.utils import find_cause
from cmdb.errors.database import (
    DocumentQueryTimeLimitError,
    DocumentInsertError,
    DocumentInsertDuplicateKeyError,
    DocumentInsertTooLargeError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
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

MODULE_PATH: str = 'cmdb.manager.base_manager'

COLLECTION: str = 'framework.stub'
DB_NAME: str = 'test-db'
TIME_LIMIT_MS: int = 1234


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a BaseManager, wired with a collection + database name."""
    mgr = MagicMock()
    mgr.collection = COLLECTION
    mgr.db_name = DB_NAME
    return mgr


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   insert_many                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _insert_manager(reserved: list[int] | None = None) -> MagicMock:
    """A stand-in manager whose id assignment is the real one, over a dbm that reserves the given block"""
    mgr = _mock_manager()
    mgr.dbm.reserve_public_ids.return_value = reserved or []
    # The stand-in is a MagicMock, so the real helper is wired in by hand
    mgr._assign_public_ids.side_effect = (  # pylint: disable=protected-access
        lambda data: BaseManager._assign_public_ids(mgr, data)  # pylint: disable=protected-access
    )
    return mgr


def test_insert_many_skip_public_delegates_without_id_generation() -> None:
    """skip_public=True inserts the documents as-is and never reserves a public_id"""
    mgr = _insert_manager()
    docs = [{'public_id': 1}, {'public_id': 2}]

    BaseManager.insert_many(mgr, docs, skip_public=True)

    mgr.dbm.insert_many.assert_called_once_with(COLLECTION, DB_NAME, docs, skip_public=True)
    mgr.dbm.reserve_public_ids.assert_not_called()


def test_insert_many_assigns_public_id_to_documents_missing_one() -> None:
    """Every document without a public_id gets one, in list order, from the reserved block"""
    mgr = _insert_manager(reserved=[10, 11])
    docs = [{'name': 'a'}, {'name': 'b'}]

    BaseManager.insert_many(mgr, docs)

    assert [doc['public_id'] for doc in docs] == [10, 11]


def test_insert_many_reserves_one_block_for_the_whole_batch() -> None:
    """One counter write for N documents, not one per document"""
    mgr = _insert_manager(reserved=[10, 11, 12])

    BaseManager.insert_many(mgr, [{'name': 'a'}, {'name': 'b'}, {'name': 'c'}])

    mgr.dbm.reserve_public_ids.assert_called_once_with(COLLECTION, DB_NAME, 3)
    mgr.dbm.get_next_public_id.assert_not_called()


def test_insert_many_tells_the_database_layer_the_ids_are_settled() -> None:
    """The database layer would otherwise run its own id loop over the same documents"""
    mgr = _insert_manager(reserved=[10])
    docs = [{'name': 'a'}]

    BaseManager.insert_many(mgr, docs)

    mgr.dbm.insert_many.assert_called_once_with(COLLECTION, DB_NAME, docs, skip_public=True)


def test_insert_many_preserves_existing_public_id() -> None:
    """A document that already carries a public_id keeps it; the block is sized for the missing ones only"""
    mgr = _insert_manager(reserved=[10])
    docs = [{'public_id': 99}, {'name': 'b'}]

    BaseManager.insert_many(mgr, docs)

    assert docs[0]['public_id'] == 99
    assert docs[1]['public_id'] == 10
    mgr.dbm.reserve_public_ids.assert_called_once_with(COLLECTION, DB_NAME, 1)


def test_insert_many_reserves_nothing_when_every_document_has_an_id() -> None:
    """No counter write at all for a batch that brings its own ids"""
    mgr = _insert_manager()

    BaseManager.insert_many(mgr, [{'public_id': 5}, {'public_id': 6}])

    mgr.dbm.reserve_public_ids.assert_not_called()


@pytest.mark.parametrize('failure', [
    DocumentInsertError('boom'),
    DocumentInsertDuplicateKeyError('duplicate'),
    DocumentInsertTooLargeError('too large'),
], ids=['insert', 'duplicate-key', 'too-large'])
def test_insert_many_wraps_an_insert_failure(failure: Exception) -> None:
    """The insert's own errors - the typed refusals among them - are wrapped, the error itself as args[0]"""
    mgr = _insert_manager()
    mgr.dbm.insert_many.side_effect = failure

    with pytest.raises(BaseManagerInsertError) as caught:
        BaseManager.insert_many(mgr, [{'public_id': 1}], skip_public=True)

    assert caught.value.args[0] is failure


def test_insert_many_wraps_a_failed_reservation() -> None:
    """The ids could not be reserved: an insert failure, and nothing is inserted"""
    mgr = _insert_manager()
    failure = DocumentGetError('counter')
    mgr.dbm.reserve_public_ids.side_effect = failure

    with pytest.raises(BaseManagerInsertError) as caught:
        BaseManager.insert_many(mgr, [{'name': 'a'}])

    assert caught.value.args[0] is failure
    mgr.dbm.insert_many.assert_not_called()


def test_insert_many_lets_a_programming_error_through() -> None:
    """A bug is not a database failure: it surfaces as itself, not as BaseManagerInsertError"""
    mgr = _insert_manager()
    mgr.dbm.insert_many.side_effect = TypeError('bug')

    with pytest.raises(TypeError):
        BaseManager.insert_many(mgr, [{'public_id': 1}], skip_public=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_from_other_collection                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_many_passes_the_criteria_and_no_projection() -> None:
    """Without a projection the database layer's own default applies (it only drops `_id`)"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []

    BaseManager.get_many(mgr, criteria={'type_id': 7})

    call = mgr.dbm.find_all.call_args
    assert call.kwargs['collection'] == COLLECTION
    assert call.kwargs['db_name'] == DB_NAME
    assert call.kwargs['filter'] == {'type_id': 7}
    assert 'projection' not in call.kwargs


def test_get_many_forwards_a_projection_and_keeps_it_out_of_the_filter() -> None:
    """A projection reaches the driver as one, not as a filter on a field named `projection`"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []
    projection = {'public_id': 1, '_id': 0}

    BaseManager.get_many(mgr, projection=projection, criteria={'type_id': 7})

    call = mgr.dbm.find_all.call_args
    assert call.kwargs['projection'] is projection
    assert call.kwargs['filter'] == {'type_id': 7}


def test_get_many_from_other_collection_passes_the_criteria_and_no_projection() -> None:
    """Without a projection the database layer's own default applies (it only drops `_id`)"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []

    BaseManager.get_many_from_other_collection(mgr, 'framework.objects', criteria={'type_id': 7})

    call = mgr.dbm.find_all.call_args
    assert call.kwargs['collection'] == 'framework.objects'
    assert call.kwargs['filter'] == {'type_id': 7}
    assert 'projection' not in call.kwargs


def test_get_many_from_other_collection_forwards_a_projection() -> None:
    """
    A caller reading a few keys of a large document does not pay for the rest

    The MDS propagation reads four keys of an object this way; a projection has to reach the driver
    for that to be true.
    """
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []
    projection = {'public_id': 1, '_id': 0}

    BaseManager.get_many_from_other_collection(
        mgr, 'framework.objects', projection=projection, criteria={'type_id': 7},
    )

    assert mgr.dbm.find_all.call_args.kwargs['projection'] is projection


def test_get_many_from_other_collection_accepts_a_dotted_filter_key() -> None:
    """The MDS narrowing is a dotted path - a plain key of the criteria dict"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []

    BaseManager.get_many_from_other_collection(
        mgr, 'framework.objects', criteria={'multi_data_sections.section_id': {'$in': ['sec-a']}},
    )

    assert mgr.dbm.find_all.call_args.kwargs['filter'] == {
        'multi_data_sections.section_id': {'$in': ['sec-a']},
    }


@pytest.mark.parametrize('option_named_field', ['sort', 'direction', 'limit', 'projection'])
def test_get_many_filters_on_a_field_named_like_an_option(option_named_field: str) -> None:
    """The criteria are one dict, so a stored `sort` key (ISMS impact categories, risk classes) is a filter field"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []

    BaseManager.get_many(mgr, criteria={option_named_field: 3})

    call = mgr.dbm.find_all.call_args
    assert call.kwargs['filter'] == {option_named_field: 3}
    assert call.kwargs['sort'] == [('public_id', -1)]
    assert call.kwargs['limit'] == 0
    assert 'projection' not in call.kwargs


def test_get_many_from_other_collection_filters_on_a_field_named_collection() -> None:
    """`collection` used to be the method's own parameter; as a criteria key it is a filter field"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []

    BaseManager.get_many_from_other_collection(mgr, 'framework.objects', criteria={'collection': 'x'})

    call = mgr.dbm.find_all.call_args
    assert call.kwargs['collection'] == 'framework.objects'
    assert call.kwargs['filter'] == {'collection': 'x'}


@pytest.mark.parametrize('method', ['get_many', 'get_many_from_other_collection'])
def test_the_reads_take_no_filter_keyword_arguments(method: str) -> None:
    """A stray keyword is a TypeError now, never a silent filter field"""
    mgr = _mock_manager()
    leading: tuple = ('framework.objects',) if method == 'get_many_from_other_collection' else ()

    with pytest.raises(TypeError):
        getattr(BaseManager, method)(mgr, *leading, type_id=7)


@pytest.mark.parametrize('method', ['get_many', 'get_many_from_other_collection'])
def test_the_reads_without_criteria_read_everything(method: str) -> None:
    """No criteria is the empty filter"""
    mgr = _mock_manager()
    mgr.dbm.find_all.return_value = []
    leading: tuple = ('framework.objects',) if method == 'get_many_from_other_collection' else ()

    getattr(BaseManager, method)(mgr, *leading)

    assert mgr.dbm.find_all.call_args.kwargs['filter'] == {}


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
    mgr.aggregate_within_time_limit.return_value = docs
    params = MagicMock()

    result = BaseManager.aggregate_query(mgr, params)

    assert result == docs
    mgr.query_builder.build.assert_called_once_with(params, None, None)
    mgr.aggregate_within_time_limit.assert_called_once_with(['QUERY'], params.time_limit_ms)


def test_aggregate_query_runs_no_count_pipeline() -> None:
    """The whole point of the method: exactly one aggregation, and no count query is built"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    mgr.aggregate_within_time_limit.return_value = []

    BaseManager.aggregate_query(mgr, MagicMock())

    mgr.query_builder.count.assert_not_called()
    assert mgr.aggregate_within_time_limit.call_count == 1


def test_aggregate_query_forwards_user_and_permission() -> None:
    """The ACL arguments reach the query builder unchanged"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = []
    mgr.aggregate_within_time_limit.return_value = []
    params, user, permission = MagicMock(), MagicMock(), MagicMock()

    BaseManager.aggregate_query(mgr, params, user, permission)

    mgr.query_builder.build.assert_called_once_with(params, user, permission)


def test_aggregate_query_passes_the_aggregation_error_on_unwrapped() -> None:
    """aggregate_within_time_limit already raised the manager error: it is not wrapped a second time"""
    mgr = _mock_manager()
    failure = BaseManagerIterationError(DocumentQueryTimeLimitError('slow', TIME_LIMIT_MS))
    mgr.aggregate_within_time_limit.side_effect = failure

    with pytest.raises(BaseManagerIterationError) as caught:
        BaseManager.aggregate_query(mgr, BuilderParameters(criteria={}, time_limit_ms=TIME_LIMIT_MS))

    assert caught.value is failure


def test_aggregate_query_lets_a_programming_error_through() -> None:
    """A bug while building the pipeline surfaces as itself"""
    mgr = _mock_manager()
    mgr.query_builder.build.side_effect = TypeError('bug')

    with pytest.raises(TypeError):
        BaseManager.aggregate_query(mgr, MagicMock())


def test_aggregate_query_runs_under_the_queries_time_budget() -> None:
    """The budget the BuilderParameters carry is the data aggregation's"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    mgr.aggregate_within_time_limit.return_value = []
    params = BuilderParameters(criteria={}, time_limit_ms=TIME_LIMIT_MS)

    BaseManager.aggregate_query(mgr, params)

    mgr.aggregate_within_time_limit.assert_called_once_with(['QUERY'], TIME_LIMIT_MS)


def test_iterate_query_counts_under_the_same_time_budget() -> None:
    """The count pipeline is the client's criteria too, so it is held to the same budget"""
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = ['COUNT']
    mgr.aggregate_within_time_limit.return_value = [{'total': 3}]
    params = BuilderParameters(criteria={}, time_limit_ms=TIME_LIMIT_MS)

    assert BaseManager.iterate_query(mgr, params) == ([], 3)
    mgr.aggregate_within_time_limit.assert_called_once_with(['COUNT'], TIME_LIMIT_MS)


def test_a_timed_out_query_keeps_the_typed_error_in_its_chain() -> None:
    """Wrapped as the manager's iteration error, with the DocumentQueryTimeLimitError a route looks for inside"""
    mgr = _mock_manager()
    mgr.query_builder.build.return_value = ['QUERY']
    timeout = DocumentQueryTimeLimitError('slow', TIME_LIMIT_MS)
    wrapped = BaseManagerIterationError(timeout)
    wrapped.__cause__ = timeout
    mgr.aggregate_within_time_limit.side_effect = wrapped

    with pytest.raises(BaseManagerIterationError) as exc_info:
        BaseManager.aggregate_query(mgr, BuilderParameters(criteria={}))

    assert find_cause(exc_info.value, DocumentQueryTimeLimitError) is timeout


# -------------------------------------------------------------------------------------------------------------------- #
#                                            aggregate_within_time_limit                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_aggregate_within_time_limit_delegates_to_the_database_layer() -> None:
    """The manager's own collection and database, the pipeline, the budget and the further options"""
    mgr = _mock_manager()
    mgr.dbm.aggregate_within_time_limit.return_value = [{'public_id': 1}]

    result = BaseManager.aggregate_within_time_limit(mgr, ['PIPE'], TIME_LIMIT_MS, allowDiskUse=True)

    assert result == [{'public_id': 1}]
    mgr.dbm.aggregate_within_time_limit.assert_called_once_with(
        COLLECTION, DB_NAME, ['PIPE'], TIME_LIMIT_MS, allowDiskUse=True,
    )


def test_aggregate_within_time_limit_wraps_the_timeout_itself() -> None:
    """A DocumentQueryTimeLimitError is an aggregation error: wrapped, and still the wrapper's args[0]"""
    mgr = _mock_manager()
    timeout = DocumentQueryTimeLimitError('slow', TIME_LIMIT_MS)
    mgr.dbm.aggregate_within_time_limit.side_effect = timeout

    with pytest.raises(BaseManagerIterationError) as exc_info:
        BaseManager.aggregate_within_time_limit(mgr, ['PIPE'], TIME_LIMIT_MS)

    assert exc_info.value.args[0] is timeout


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  iterate_query                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iterate_query_returns_results_and_total() -> None:
    """Returns the rows from aggregate_query plus the total pulled from the count pipeline"""
    mgr = _mock_manager()
    docs = [{'public_id': 1}, {'public_id': 2}]
    mgr.aggregate_query.return_value = docs
    mgr.query_builder.count.return_value = ['COUNT']
    mgr.aggregate_within_time_limit.return_value = [{'total': 7}]
    params = MagicMock()

    result = BaseManager.iterate_query(mgr, params)

    assert result == (docs, 7)


def test_iterate_query_delegates_the_data_half_to_aggregate_query() -> None:
    """The data pipeline is not rebuilt here - iterate_query is aggregate_query plus a count"""
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate_within_time_limit.return_value = []
    params, user, permission = MagicMock(), MagicMock(), MagicMock()

    BaseManager.iterate_query(mgr, params, user, permission)

    # The access control has already been put INTO params, so the data half is not given it again -
    # handing it down would restrict the rows and leave the count beside them unrestricted
    mgr.aggregate_query.assert_called_once_with(params)
    mgr.apply_acl_to_builder_params.assert_called_once_with(params, user, permission)
    # Only the count pipeline is aggregated directly; the data half went through aggregate_query
    assert mgr.aggregate_within_time_limit.call_count == 1


def test_iterate_query_counts_the_criteria_the_rows_were_read_with() -> None:
    """
    The rows and the total obey the same rule

    The count pipeline is built from the criteria, so an access rule that lived only in the data
    pipeline would leave the total counting documents the caller may not read.
    """
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate_within_time_limit.return_value = []
    params = MagicMock()

    BaseManager.iterate_query(mgr, params, MagicMock(), MagicMock())

    assert mgr.apply_acl_to_builder_params.call_args.args[0] is params
    mgr.query_builder.count.assert_called_once_with(params.get_criteria.return_value)


# ------------------------------------------- apply_acl_to_builder_params -------------------------------------------- #

def test_apply_acl_to_builder_params_without_a_user_adds_nothing() -> None:
    """Every internal caller reads unscoped, and must not pay for a denied-types query."""
    params = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids') as resolve:
        BaseManager.apply_acl_to_builder_params(params, None, MagicMock())

    resolve.assert_not_called()
    params.add_criteria.assert_not_called()


def test_apply_acl_to_builder_params_without_a_permission_adds_nothing() -> None:
    """Both halves of the pair are required, matching acl/helpers.verify_access."""
    params = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids') as resolve:
        BaseManager.apply_acl_to_builder_params(params, MagicMock(), None)

    resolve.assert_not_called()
    params.add_criteria.assert_not_called()


def test_apply_acl_to_builder_params_adds_nothing_when_no_type_is_denied() -> None:
    """The common case costs one resolve and no query change at all."""
    params = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids', return_value=[]):
        BaseManager.apply_acl_to_builder_params(params, MagicMock(), MagicMock())

    params.add_criteria.assert_not_called()


def test_apply_acl_to_builder_params_excludes_the_denied_types() -> None:
    """The denied ids become the shared exclusion condition, merged into the criteria."""
    params = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids', return_value=[3, 9]):
        BaseManager.apply_acl_to_builder_params(params, MagicMock(), MagicMock())

    params.add_criteria.assert_called_once_with({'type_id': {'$nin': [3, 9]}})


def test_apply_acl_to_builder_params_resolves_the_denied_types_once() -> None:
    """One projected read per iteration, shared by the rows and the count."""
    params = MagicMock()

    with patch(f'{MODULE_PATH}.resolve_denied_type_ids', return_value=[3]) as resolve:
        BaseManager.apply_acl_to_builder_params(params, MagicMock(), MagicMock())

    resolve.assert_called_once()


def test_iterate_query_total_defaults_to_zero_when_count_empty() -> None:
    """An empty count cursor yields a total of 0 rather than raising"""
    mgr = _mock_manager()
    mgr.aggregate_query.return_value = []
    mgr.query_builder.count.return_value = []
    mgr.aggregate_within_time_limit.return_value = []

    result = BaseManager.iterate_query(mgr, MagicMock())

    assert result == ([], 0)


@pytest.mark.parametrize('failure', [
    BaseManagerGetError('types unreadable'),
    BaseManagerInitError('no manager'),
], ids=['types-read', 'manager-wiring'])
def test_iterate_query_wraps_a_failed_access_control_read(failure: Exception) -> None:
    """The denied types could not be read: one iteration error for the caller, the read's error as args[0]"""
    mgr = _mock_manager()
    mgr.apply_acl_to_builder_params.side_effect = failure

    with pytest.raises(BaseManagerIterationError) as caught:
        BaseManager.iterate_query(mgr, MagicMock(), MagicMock(), MagicMock())

    assert caught.value.args[0] is failure
    mgr.aggregate_query.assert_not_called()


@pytest.mark.parametrize('half', ['data', 'count'])
def test_iterate_query_passes_an_aggregation_error_on_unwrapped(half: str) -> None:
    """Either aggregation already raised the manager error; the time-limit cause stays one hop down"""
    mgr = _mock_manager()
    timeout = DocumentQueryTimeLimitError('slow', TIME_LIMIT_MS)
    failure = BaseManagerIterationError(timeout)
    mgr.aggregate_query.return_value = []
    mgr.aggregate_within_time_limit.return_value = []

    if half == 'data':
        mgr.aggregate_query.side_effect = failure
    else:
        mgr.aggregate_within_time_limit.side_effect = failure

    with pytest.raises(BaseManagerIterationError) as caught:
        BaseManager.iterate_query(mgr, BuilderParameters(criteria={}, time_limit_ms=TIME_LIMIT_MS))

    assert caught.value is failure
    assert caught.value.args[0] is timeout


def test_iterate_query_lets_a_bug_in_the_access_control_step_through() -> None:
    """Only the denied-types READ is wrapped; a bug around it (a group id that is no number) surfaces as itself"""
    mgr = _mock_manager()
    mgr.apply_acl_to_builder_params.side_effect = TypeError('bug')

    with pytest.raises(TypeError):
        BaseManager.iterate_query(mgr, MagicMock(), MagicMock(), MagicMock())


def test_iterate_query_lets_a_programming_error_through() -> None:
    """A bug in the read surfaces as itself, not as BaseManagerIterationError"""
    mgr = _mock_manager()
    mgr.aggregate_query.side_effect = TypeError('bug')

    with pytest.raises(TypeError):
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
def test_update_many_pull_builds_the_pull_and_sends_it_raw() -> None:
    """The $pull is built here and sent through update_many_raw - the database layer has no pull method"""
    mgr = _mock_manager()

    BaseManager.update_many_pull(mgr, {'types_filter': 5}, {'types_filter': 5})

    mgr.dbm.update_many_raw.assert_called_once_with(
        collection=COLLECTION, db_name=DB_NAME, filter_query={'types_filter': 5}, update={'$pull': {'types_filter': 5}},
    )


@pytest.mark.parametrize('add_to_set', [False, True], ids=['set', 'add-to-set'])
def test_update_many_forwards_only_the_add_to_set_choice(add_to_set: bool) -> None:
    """No plain flag any more: field values and the $set / $addToSet choice, nothing else"""
    mgr = _mock_manager()

    BaseManager.update_many(mgr, {'x': 1}, {'tags': 'a'}, add_to_set=add_to_set)

    mgr.dbm.update_many.assert_called_once_with(COLLECTION, DB_NAME, {'x': 1}, {'tags': 'a'}, add_to_set)


def test_update_many_raw_passes_a_pipeline_through() -> None:
    """A pipeline (a list of stages) is a raw update"""
    mgr = _mock_manager()
    pipeline = [{'$set': {'x': 1}}]

    BaseManager.update_many_raw(mgr, {'relation_id': 3}, pipeline)

    mgr.dbm.update_many_raw.assert_called_once_with(
        collection=COLLECTION, db_name=DB_NAME, filter_query={'relation_id': 3}, update=pipeline, array_filters=None,
    )


def test_update_uses_manager_collection_by_default() -> None:
    """Without col, the update targets this manager's own collection, and nothing is added to the call

    No wrapping flag is forwarded: anything extra would land in dbm.update's *args / **kwargs and reach
    update_one() (a trailing True there is upsert=True - a silent upsert)
    """
    mgr = _mock_manager()

    BaseManager.update(mgr, {'public_id': 1}, {'name': 'x'})

    mgr.dbm.update.assert_called_once_with(COLLECTION, DB_NAME, {'public_id': 1}, {'name': 'x'})


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
#                                               find_one_and_delete                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_one_and_delete_answers_what_the_database_deleted() -> None:
    """Forwarded to the manager's own collection and database, the deleted document answered as is"""
    mgr = _mock_manager()
    mgr.dbm.find_one_and_delete.return_value = {'public_id': 5}

    result = BaseManager.find_one_and_delete(mgr, {'public_id': 5})

    assert result == {'public_id': 5}
    mgr.dbm.find_one_and_delete.assert_called_once_with(COLLECTION, DB_NAME, {'public_id': 5})


def test_find_one_and_delete_answers_none_when_nothing_matched() -> None:
    """Nothing deleted is None, not an error"""
    mgr = _mock_manager()
    mgr.dbm.find_one_and_delete.return_value = None

    assert BaseManager.find_one_and_delete(mgr, {'public_id': 5}) is None


def test_find_one_and_delete_wraps_failure() -> None:
    """A DocumentDeleteError is wrapped in BaseManagerDeleteError, carrying it"""
    mgr = _mock_manager()
    failure = DocumentDeleteError('boom')
    mgr.dbm.find_one_and_delete.side_effect = failure

    with pytest.raises(BaseManagerDeleteError) as exc_info:
        BaseManager.find_one_and_delete(mgr, {'public_id': 5})

    assert exc_info.value.args[0] is failure


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   delete_many                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('filter_query', [
    {'public_id': 5, 'active': True},
    {'$or': [{'public_id': 1}, {'public_id': 2}]},
    {'collection': 'x', 'db_name': 'y'},
], ids=['plain', 'top-level-operator', 'keys-named-like-parameters'])
def test_delete_many_hands_the_filter_over_as_one_dict(filter_query: dict) -> None:
    """Whatever its keys - an operator, or a field named like a parameter - the filter reaches MongoDB as it is"""
    mgr = _mock_manager()
    sentinel = MagicMock(name='delete_result')
    mgr.dbm.delete_many_raw.return_value = sentinel

    result = BaseManager.delete_many(mgr, filter_query)

    mgr.dbm.delete_many_raw.assert_called_once_with(collection=COLLECTION, db_name=DB_NAME, filter_query=filter_query)
    assert result is sentinel


def test_delete_many_refuses_an_empty_filter() -> None:
    """{} would match every document: refused before the database is asked, naming the collection"""
    mgr = _mock_manager()

    with pytest.raises(BaseManagerDeleteError) as caught:
        BaseManager.delete_many(mgr, {})

    assert caught.value.args[0] == EMPTY_DELETE_FILTER_MSG.format(collection=COLLECTION)
    mgr.dbm.delete_many_raw.assert_not_called()


def test_delete_many_wraps_document_delete_error() -> None:
    """A DocumentDeleteError is wrapped in BaseManagerDeleteError"""
    mgr = _mock_manager()
    mgr.dbm.delete_many_raw.side_effect = DocumentDeleteError('boom')

    with pytest.raises(BaseManagerDeleteError):
        BaseManager.delete_many(mgr, {'public_id': 5})


def test_base_manager_has_one_delete_many() -> None:
    """The raw twin is gone: one same-collection bulk delete, one convention"""
    assert not hasattr(BaseManager, 'delete_many_raw')


# -------------------------------------------------------------------------------------------------------------------- #
#                                       __init__ + fully-uncovered delegations                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_lets_a_programming_error_through() -> None:
    """A None dbm with no db_name is a caller's bug: it surfaces as itself, not as a manager error"""
    with pytest.raises(AttributeError):
        BaseManager(COLLECTION, None, None)


def test_init_reads_the_database_name_from_the_dbm_when_none_is_given() -> None:
    """The tenant database when one is named, the dbm's own otherwise"""
    dbm = MagicMock()
    dbm.db_name = 'default-db'

    assert BaseManager(COLLECTION, dbm, None).db_name == 'default-db'
    assert BaseManager(COLLECTION, dbm, DB_NAME).db_name == DB_NAME


def test_get_distinct_lets_a_programming_error_through() -> None:
    """Only the database layer's DocumentGetError is wrapped"""
    mgr = _mock_manager()
    mgr.dbm.get_distinct.side_effect = TypeError('bug')

    with pytest.raises(TypeError):
        BaseManager.get_distinct(mgr, 'type_id', {})


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


def test_bulk_write_answers_the_database_layers_modified_count() -> None:
    """The count reaches the caller, which is how a batch write learns whether every statement landed."""
    mgr = _mock_manager()
    mgr.dbm.bulk_write.return_value = 2
    operations = [MagicMock(), MagicMock()]

    result = BaseManager.bulk_write(mgr, operations)

    assert result == 2
    mgr.dbm.bulk_write.assert_called_once_with(COLLECTION, DB_NAME, operations)


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
    ('aggregate_within_time_limit', ([], 1), 'aggregate_within_time_limit',
     DocumentAggregationError, BaseManagerIterationError),
    ('get_next_public_id', (), 'get_next_public_id', DocumentGetError, BaseManagerGetError),
    ('reserve_public_ids', (5,), 'reserve_public_ids', DocumentGetError, BaseManagerGetError),
    ('count_documents', (), 'count', DocumentGetError, BaseManagerGetError),
    ('update_many', ({'x': 1}, {'y': 2}), 'update_many', DocumentUpdateError, BaseManagerUpdateError),
    ('update_many_pull', ({'x': 1}, {'tags': 1}), 'update_many_raw', DocumentUpdateError, BaseManagerUpdateError),
    ('update_many_raw', ({'x': 1}, {'$set': {}}), 'update_many_raw', DocumentUpdateError, BaseManagerUpdateError),
    ('bulk_write', ([],), 'bulk_write', DocumentInsertError, BaseManagerUpdateError),
    ('count_from_other_collection', ('other', {}), 'count', DocumentGetError, BaseManagerGetError),
    ('update', ({'x': 1}, {'y': 2}), 'update', DocumentUpdateError, BaseManagerUpdateError),
    ('replace', (7, {'y': 2}), 'replace', DocumentUpdateError, BaseManagerUpdateError),
    ('upsert', ({'x': 1}, {'y': 2}), 'upsert', DocumentUpdateError, BaseManagerUpdateError),
    ('delete', ({'x': 1},), 'delete', DocumentDeleteError, BaseManagerDeleteError),
    ('delete_many', ({'x': 1},), 'delete_many_raw', DocumentDeleteError, BaseManagerDeleteError),
    ('delete_many_from_other_collection', ('other', {'x': 1}), 'delete_many_raw',
     DocumentDeleteError, BaseManagerDeleteError),
]

# The one delegation whose wrapper ADDS context (the collection name) around the error, and so carries
# text rather than the error itself - the kind of message the error-wrapping tripwire leaves alone
CONTEXT_WRAPPING_METHODS: frozenset[str] = frozenset({'bulk_write'})


@pytest.mark.parametrize(
    'method, args, dbm_attr, db_error, expected_error',
    _ERROR_MAPPING_CASES,
    ids=[case[0] for case in _ERROR_MAPPING_CASES],
)
def test_delegation_wraps_database_error(method, args, dbm_attr, db_error, expected_error) -> None:
    """
    Each thin delegation rewraps its database-layer error as the matching BaseManager* error

    and hands over the error itself: args[0] is what a caller branches on, where `__cause__` would pass
    under a stringified wrap too
    """
    mgr = _mock_manager()
    failure = db_error('boom')
    getattr(mgr.dbm, dbm_attr).side_effect = failure

    with pytest.raises(expected_error) as caught:
        getattr(BaseManager, method)(mgr, *args)

    assert caught.value.__cause__ is failure

    if method not in CONTEXT_WRAPPING_METHODS:
        assert caught.value.args[0] is failure


@pytest.mark.parametrize('failure', [
    DocumentNetworkError('connection lost'),
    DocumentLockTimeoutError('lock timeout'),
], ids=['network', 'lock-timeout'])
def test_insert_many_raises_a_transient_failure_unwrapped(failure: Exception) -> None:
    """
    Like insert, which only ever wraps DocumentInsertError: a lock timeout or a lost connection says
    nothing about the documents, so it is left for the route layer to answer as a server error
    """
    mgr = _mock_manager()
    mgr.dbm.insert_many.side_effect = failure

    with pytest.raises(type(failure)) as caught:
        BaseManager.insert_many(mgr, [{'public_id': 1}], skip_public=True)

    assert caught.value is failure


def test_insert_leaves_a_transient_failure_unwrapped_too() -> None:
    """The single insert already did; pinned beside insert_many so the two cannot drift apart"""
    mgr = _mock_manager()
    failure = DocumentNetworkError('connection lost')
    mgr.dbm.insert.side_effect = failure

    with pytest.raises(DocumentNetworkError) as caught:
        BaseManager.insert(mgr, {})

    assert caught.value is failure


def test_replace_addresses_the_document_by_its_public_id() -> None:
    """The whole document is handed to the database layer, keyed by public_id."""
    mgr = _mock_manager()

    BaseManager.replace(mgr, 7, {'public_id': 7, 'name': 'x'})

    mgr.dbm.replace.assert_called_once_with(COLLECTION, DB_NAME, {'public_id': 7}, {'public_id': 7, 'name': 'x'})
