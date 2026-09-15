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
Unit tests for cmdb.manager.objects_manager summary-line helpers

Covers the projection-aware ``find_objects``, the private composition helper
``_compose_summary_line``, the batch type loader ``_load_types_lookup``, the orchestration
in ``get_summary_line`` (refactored to delegate composition) and the batch
``get_summary_lines_lookup`` (including its pre-loaded ``object_docs`` fast path). Mongo
touch-points are stubbed via MagicMock on a ``MagicMock``-typed self so the method body
runs without an actual database connection
"""
# pylint: disable=protected-access
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
    ObjectsManagerDeleteError,
    ObjectsManagerInitError,
    ObjectsManagerIterationError,
    ObjectsManagerGetTypeError,
    ObjectsManagerSummaryLineError,
    ObjectsManagerMdsReferencesError,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.security import AccessDeniedError
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #


OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_OBJECT_ID: int = 701
OTHER_OWNER_TYPE_ID: int = 51

PATH: str = 'cmdb.manager.objects_manager'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    FIXTURES                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with the given public_id, type_id, and field list."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'fields': fields or [],
    }


def _make_full_object_doc(public_id: int, type_id: int = OWNER_TYPE_ID) -> dict[str, Any]:
    """Builds an aggregation row carrying every key CmdbObject.from_data requires."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'creation_time': datetime(2026, 1, 1, tzinfo=timezone.utc),
        'author_id': 1,
        'active': True,
        'fields': [],
    }


def _make_type_mock(public_id: int, label: str, *, has_summaries: bool = False,
                    summary_fields: list[dict[str, Any]] | None = None) -> MagicMock:
    """Builds a MagicMock that quacks like a CmdbType for summary-line composition."""
    type_mock = MagicMock()
    type_mock.public_id = public_id
    type_mock.label = label
    type_mock.has_summaries.return_value = has_summaries

    summary_obj = MagicMock()
    summary_obj.fields = summary_fields or []
    type_mock.get_summary.return_value = summary_obj

    return type_mock


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _load_types_lookup                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_types_lookup_returns_empty_dict_for_empty_type_ids() -> None:
    """No type ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager._load_types_lookup(mock_self, [])

    assert not result
    mock_self.get_many_from_other_collection.assert_not_called()


def test_load_types_lookup_returns_loaded_types_keyed_by_public_id() -> None:
    """Every successfully deserialised type lands in the result keyed by its public_id"""
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')
    mock_self = MagicMock()
    mock_self.get_many_from_other_collection.return_value = [
        {'public_id': OWNER_TYPE_ID, 'label': 'Server'},
        {'public_id': OTHER_OWNER_TYPE_ID, 'label': 'Printer'},
    ]

    with patch(f'{PATH}.CmdbType.from_data', side_effect=[type_a, type_b]):
        result = ObjectsManager._load_types_lookup(mock_self, [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    assert result == {OWNER_TYPE_ID: type_a, OTHER_OWNER_TYPE_ID: type_b}


def test_load_types_lookup_skips_types_that_fail_to_deserialise() -> None:
    """A drifted type doc that raises during deserialisation is skipped silently"""
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')
    mock_self = MagicMock()
    mock_self.get_many_from_other_collection.return_value = [
        {'public_id': OWNER_TYPE_ID, 'label': 'Broken'},
        {'public_id': OTHER_OWNER_TYPE_ID, 'label': 'Printer'},
    ]

    with patch(f'{PATH}.CmdbType.from_data', side_effect=[RuntimeError('drifted'), type_b]):
        result = ObjectsManager._load_types_lookup(mock_self, [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    assert result == {OTHER_OWNER_TYPE_ID: type_b}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_summary_line                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_summary_line_returns_empty_string_for_falsy_public_id() -> None:
    """public_id of 0 or None short-circuits to an empty line before any DB call"""
    mock_self = MagicMock()

    assert ObjectsManager.get_summary_line(mock_self, 0) == ''
    mock_self.get_object.assert_not_called()


def test_get_summary_line_returns_empty_string_when_object_not_found() -> None:
    """A missing CmdbObject yields '' without attempting to compose"""
    mock_self = MagicMock()
    mock_self.get_object.return_value = None

    assert ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID) == ''


def test_get_summary_line_returns_empty_string_when_object_type_not_found() -> None:
    """A CmdbObject without a resolvable type yields '' (no _compose_summary_line call)"""
    mock_self = MagicMock()
    mock_self.get_object.return_value = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    mock_self.get_object_type.return_value = None

    result = ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID)

    assert result == ''
    mock_self._compose_summary_line.assert_not_called()


def test_get_summary_line_delegates_to_compose_summary_line_on_happy_path() -> None:
    """
    When the object + type both resolve, the manager reads and the helper composes

    The manager owns the two lookups; the text itself is composed by objects_summary_helper, which is
    what keeps the single-object and the batch path producing the same line.
    """
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')
    mock_self = MagicMock()
    mock_self.get_object.return_value = obj_doc
    mock_self.get_object_type.return_value = type_mock

    with patch(f'{PATH}.compose_summary_line', return_value=f"Server #{OWNER_OBJECT_ID}") as compose:
        result = ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID, with_type=True)

    assert result == f"Server #{OWNER_OBJECT_ID}"
    compose.assert_called_once_with(obj_doc, type_mock, with_type=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_summary_lines_lookup                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_summary_lines_lookup_returns_empty_dict_for_empty_input() -> None:
    """No public_ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [])

    assert not result
    mock_self.find_objects.assert_not_called()


def test_get_summary_lines_lookup_dedups_public_ids_before_bulk_fetch() -> None:
    """Duplicate ids in the input are collapsed in the find_objects criteria"""
    mock_self = MagicMock()
    mock_self.find_objects.return_value = []
    mock_self._load_types_lookup.return_value = {}

    ObjectsManager.get_summary_lines_lookup(
        mock_self,
        [OWNER_OBJECT_ID, OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    call_kwargs = mock_self.find_objects.call_args.kwargs
    in_clause = call_kwargs['criteria']['public_id']['$in']
    assert sorted(in_clause) == sorted({OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID})


def test_get_summary_lines_lookup_maps_each_object_to_its_summary_line() -> None:
    """Happy path: each resolved object/type pair produces one summary line in the result"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    obj_b = _make_object_doc(OTHER_OWNER_OBJECT_ID, OTHER_OWNER_TYPE_ID)
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')

    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj_a, obj_b]
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: type_a, OTHER_OWNER_TYPE_ID: type_b}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    assert result == {
        OWNER_OBJECT_ID: f"Server #{OWNER_OBJECT_ID}",
        OTHER_OWNER_OBJECT_ID: f"Printer #{OTHER_OWNER_OBJECT_ID}",
    }


def test_get_summary_lines_lookup_skips_object_when_type_unresolvable() -> None:
    """An object whose type does not load is silently absent from the result"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    obj_b = _make_object_doc(OTHER_OWNER_OBJECT_ID, OTHER_OWNER_TYPE_ID)
    type_b = _make_type_mock(OTHER_OWNER_TYPE_ID, 'Printer')

    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj_a, obj_b]
    mock_self._load_types_lookup.return_value = {OTHER_OWNER_TYPE_ID: type_b}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID, OTHER_OWNER_OBJECT_ID],
    )

    assert OWNER_OBJECT_ID not in result
    assert OTHER_OWNER_OBJECT_ID in result


def test_get_summary_lines_lookup_skips_object_with_non_int_public_id() -> None:
    """Drifted documents whose public_id is not an int are excluded from the result"""
    obj = {'public_id': 'not-an-int', 'type_id': OWNER_TYPE_ID, 'fields': []}
    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj]
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: _make_type_mock(OWNER_TYPE_ID, 'Server')}

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [OWNER_OBJECT_ID])

    assert not result


def test_get_summary_lines_lookup_skips_object_with_non_int_type_id() -> None:
    """Objects whose type_id is non-integer never look up a CmdbType and are excluded"""
    obj = {'public_id': OWNER_OBJECT_ID, 'type_id': None, 'fields': []}
    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj]
    mock_self._load_types_lookup.return_value = {}

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [OWNER_OBJECT_ID])

    assert not result


def test_get_summary_lines_lookup_with_object_docs_skips_the_find() -> None:
    """Pre-loaded object_docs answer the batch without any find_objects round-trip"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')

    mock_self = MagicMock()
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: type_a}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID], object_docs=[obj_a],
    )

    assert result == {OWNER_OBJECT_ID: f"Server #{OWNER_OBJECT_ID}"}
    mock_self.find_objects.assert_not_called()


def test_get_summary_lines_lookup_with_object_docs_filters_to_requested_ids() -> None:
    """Docs outside the requested public_ids are ignored when object_docs is supplied"""
    obj_a = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    obj_b = _make_object_doc(OTHER_OWNER_OBJECT_ID, OTHER_OWNER_TYPE_ID)
    type_a = _make_type_mock(OWNER_TYPE_ID, 'Server')

    mock_self = MagicMock()
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: type_a}
    mock_self._compose_summary_line.side_effect = lambda obj, t, with_type=True: f"{t.label} #{obj['public_id']}"

    result = ObjectsManager.get_summary_lines_lookup(
        mock_self, [OWNER_OBJECT_ID], object_docs=[obj_a, obj_b],
    )

    assert OWNER_OBJECT_ID in result
    assert OTHER_OWNER_OBJECT_ID not in result
    mock_self.find_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  find_objects                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_objects_rejects_projection_without_as_dict() -> None:
    """A projection on the CmdbObject-deserialising path is a caller error"""
    mock_self = MagicMock()

    with pytest.raises(ObjectsManagerGetError):
        ObjectsManager.find_objects(mock_self, {}, as_dict=False, projection={'public_id': 1})

    mock_self.find.assert_not_called()


def test_find_objects_merges_id_exclusion_into_projection() -> None:
    """A caller projection is forwarded with the default '_id' exclusion preserved"""
    mock_self = MagicMock()
    mock_self.find.return_value = []

    ObjectsManager.find_objects(mock_self, {}, as_dict=True, projection={'public_id': 1})

    forwarded = mock_self.find.call_args.kwargs['projection']
    assert forwarded == {'_id': 0, 'public_id': 1}


def test_find_objects_lets_caller_override_id_exclusion() -> None:
    """A projection that addresses '_id' explicitly wins over the default exclusion"""
    mock_self = MagicMock()
    mock_self.find.return_value = []

    ObjectsManager.find_objects(mock_self, {}, as_dict=True, projection={'_id': 1, 'public_id': 1})

    forwarded = mock_self.find.call_args.kwargs['projection']
    assert forwarded == {'_id': 1, 'public_id': 1}


def test_find_objects_without_projection_issues_plain_find() -> None:
    """No projection keeps the pre-existing call shape (criteria only)"""
    doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    mock_self = MagicMock()
    mock_self.find.return_value = [doc]

    result = ObjectsManager.find_objects(mock_self, {}, as_dict=True)

    assert result == [doc]
    assert 'projection' not in mock_self.find.call_args.kwargs


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _ref_field_names_by_type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ref_field_names_by_type_collects_only_ref_fields() -> None:
    """Only fields of type 'ref' contribute names, keyed by type public_id"""
    type_mock = MagicMock()
    type_mock.fields = [
        {'name': 'r1', 'type': FieldType.REFERENCE.value},
        {'name': 't1', 'type': FieldType.TEXT.value},
        {'name': 'r2', 'type': FieldType.REFERENCE.value},
    ]
    mock_self = MagicMock()
    mock_self._load_types_lookup.return_value = {OWNER_TYPE_ID: type_mock}

    result = ObjectsManager._ref_field_names_by_type(mock_self, [OWNER_TYPE_ID])

    assert result == {OWNER_TYPE_ID: {'r1', 'r2'}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          delete_all_object_references                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_all_object_references_empty_list_is_noop() -> None:
    """An empty list scrubs nothing and issues no update"""
    mock_self = MagicMock()

    ObjectsManager.delete_all_object_references(mock_self, [])

    mock_self.update_many_raw.assert_not_called()


def test_delete_all_object_references_falsy_non_list_raises() -> None:
    """A falsy non-list id (e.g. 0/None) is rejected"""
    mock_self = MagicMock()

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.delete_all_object_references(mock_self, 0)


def test_delete_all_object_references_runs_two_scrubs_for_valid_ids() -> None:
    """A valid id list scrubs both the flat fields and the multi-data-section fields"""
    mock_self = MagicMock()

    ObjectsManager.delete_all_object_references(mock_self, [OWNER_OBJECT_ID])

    assert mock_self.update_many_raw.call_count == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                      get_objects_by (batch + ACL skip)                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_objects_by_batches_types_and_skips_access_denied() -> None:
    """Types are resolved in one batch; objects failing the ACL check are skipped, others kept"""
    obj_a = MagicMock()
    obj_a.type_id = OWNER_TYPE_ID
    obj_b = MagicMock()
    obj_b.type_id = OTHER_OWNER_TYPE_ID

    mock_self = MagicMock()
    mock_self.get_many.return_value = [{'public_id': 1}, {'public_id': 2}]
    mock_self._load_types_lookup.return_value = {
        OWNER_TYPE_ID: MagicMock(), OTHER_OWNER_TYPE_ID: MagicMock(),
    }

    with patch(f'{PATH}.CmdbObject.from_data', side_effect=[obj_a, obj_b]), \
         patch(f'{PATH}.verify_access', side_effect=[None, AccessDeniedError('nope')]):
        result = ObjectsManager.get_objects_by(mock_self)

    assert result == [obj_a]
    # A single batched type load, not one per object
    mock_self._load_types_lookup.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                      update_object / delete_object null type                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_object_raises_when_type_missing() -> None:
    """
    A missing CmdbType surfaces as ObjectsManagerUpdateError, not an AttributeError

    The three checks (type exists, type active, ACL) moved into _guard_writable_type, so the update
    passes it the error type it wants raised - which is what this asserts.
    """
    mock_self = MagicMock()
    mock_self._guard_writable_type.side_effect = ObjectsManagerUpdateError('gone')

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.update_object(mock_self, OWNER_OBJECT_ID, {'type_id': OWNER_TYPE_ID, 'fields': []})

    assert mock_self._guard_writable_type.call_args.args[3] is ObjectsManagerUpdateError


def test_update_object_partial_writes_only_the_given_keys() -> None:
    """A partial update reads the type from the STORED object and $sets just the payload keys"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID, 'fields': []}

    with patch(f'{PATH}.verify_access'):
        ObjectsManager.update_object(mock_self, OWNER_OBJECT_ID, {'ci_explorer_tooltip': 'hint'}, partial=True)

    assert mock_self._guard_writable_type.call_args.args[0] == OWNER_TYPE_ID
    mock_self.update.assert_called_once_with({'public_id': OWNER_OBJECT_ID}, {'ci_explorer_tooltip': 'hint'})


def test_update_object_partial_raises_for_a_missing_object() -> None:
    """A partial update of an unknown id fails with the manager error, not an AttributeError"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = None

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.update_object(mock_self, 9999, {'ci_explorer_tooltip': 'hint'}, partial=True)

    mock_self.update.assert_not_called()


def test_delete_object_returns_false_for_missing_object() -> None:
    """A missing object short-circuits to False before any type/permission work"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = None

    assert ObjectsManager.delete_object(mock_self, 9999) is False
    mock_self.get_object_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_objects_grouped_by_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_count_objects_grouped_by_type_maps_type_id_to_count() -> None:
    """Each aggregation bucket becomes a type_id -> count entry, and the total sums them"""
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = [
        {'_id': OWNER_TYPE_ID, 'count': 30},
        {'_id': OTHER_OWNER_TYPE_ID, 'count': 12},
    ]

    counts, total = ObjectsManager.count_objects_grouped_by_type_with_total(mock_self)

    assert counts == {OWNER_TYPE_ID: 30, OTHER_OWNER_TYPE_ID: 12}
    assert total == 42


def test_count_objects_grouped_by_type_skips_non_int_id() -> None:
    """
    A bucket whose _id is not an int is left out of the mapping but still counts toward the total

    The mapping answers 'how many objects per CmdbType', which a null type_id cannot; the total is
    what the Service Portal is billed on, so it has to match an unfiltered count_documents() exactly.
    """
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = [
        {'_id': OWNER_TYPE_ID, 'count': 5},
        {'_id': None, 'count': 3},
    ]

    counts, total = ObjectsManager.count_objects_grouped_by_type_with_total(mock_self)

    assert counts == {OWNER_TYPE_ID: 5}
    assert total == 8


def test_count_objects_grouped_by_type_uses_single_group_aggregation() -> None:
    """The count runs one $group stage (not one count per type)"""
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = []

    ObjectsManager.count_objects_grouped_by_type_with_total(mock_self)

    pipeline = mock_self.aggregate_objects.call_args.args[0]
    assert pipeline == [{'$group': {'_id': '$type_id', 'count': {'$sum': 1}}}]


def test_count_objects_grouped_by_type_returns_only_the_mapping() -> None:
    """The mapping-only helper is a thin projection of the with-total one"""
    mock_self = MagicMock()
    mock_self.count_objects_grouped_by_type_with_total.return_value = ({OWNER_TYPE_ID: 5}, 8)

    assert ObjectsManager.count_objects_grouped_by_type(mock_self) == {OWNER_TYPE_ID: 5}


def test_delete_object_raises_when_type_missing() -> None:
    """A present object whose type is gone surfaces as ObjectsManagerDeleteError, not AttributeError"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}
    mock_self._guard_writable_type.side_effect = ObjectsManagerDeleteError('gone')

    with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)):
        with pytest.raises(ObjectsManagerDeleteError):
            ObjectsManager.delete_object(mock_self, OWNER_OBJECT_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       error wrapping: read / write delegations                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_wraps_super_failure_as_init_error() -> None:
    """A failure constructing the base manager (None dbm) surfaces as ObjectsManagerInitError."""
    with pytest.raises(ObjectsManagerInitError):
        ObjectsManager(None)


def test_get_object_wraps_unexpected_error() -> None:
    """A generic failure while fetching an object surfaces as ObjectsManagerGetError."""
    mock_self = MagicMock()
    mock_self.get_one.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerGetError):
        ObjectsManager.get_object(mock_self, 1)


def test_iterate_wraps_failure_as_iteration_error() -> None:
    """A failure in the aggregation surfaces as ObjectsManagerIterationError."""
    mock_self = MagicMock()
    mock_self.iterate_query.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.iterate(mock_self, MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  iterate_results                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iterate_results_returns_models_without_counting() -> None:
    """The rows come from aggregate_query - so no count aggregation runs - and arrive as CmdbObjects."""
    mock_self = MagicMock()
    mock_self.aggregate_query.return_value = [_make_full_object_doc(1), _make_full_object_doc(2)]
    params = MagicMock()

    result = ObjectsManager.iterate_results(mock_self, params)

    assert [obj.get_public_id() for obj in result] == [1, 2]
    assert all(isinstance(obj, CmdbObject) for obj in result)
    mock_self.aggregate_query.assert_called_once_with(params, None, None)
    mock_self.iterate_query.assert_not_called()


def test_iterate_results_forwards_user_and_permission() -> None:
    """The ACL arguments are handed to aggregate_query unchanged."""
    mock_self = MagicMock()
    mock_self.aggregate_query.return_value = []
    params, user, permission = MagicMock(), MagicMock(), MagicMock()

    ObjectsManager.iterate_results(mock_self, params, user, permission)

    mock_self.aggregate_query.assert_called_once_with(params, user, permission)


def test_iterate_results_empty_result_is_an_empty_list() -> None:
    """No matching rows yields an empty list rather than None."""
    mock_self = MagicMock()
    mock_self.aggregate_query.return_value = []

    assert ObjectsManager.iterate_results(mock_self, MagicMock()) == []


def test_iterate_results_wraps_failure_as_iteration_error() -> None:
    """A failure in the aggregation surfaces as ObjectsManagerIterationError."""
    mock_self = MagicMock()
    mock_self.aggregate_query.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.iterate_results(mock_self, MagicMock())


def test_get_objects_by_wraps_unexpected_error() -> None:
    """A generic failure while fetching objects surfaces as ObjectsManagerGetError."""
    mock_self = MagicMock()
    mock_self.get_many.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerGetError):
        ObjectsManager.get_objects_by(mock_self)


def test_get_object_type_wraps_base_get_error() -> None:
    """A BaseManagerGetError fetching the type surfaces as ObjectsManagerGetTypeError."""
    mock_self = MagicMock()
    mock_self.get_one_from_other_collection.side_effect = BaseManagerGetError('boom')

    with pytest.raises(ObjectsManagerGetTypeError):
        ObjectsManager.get_object_type(mock_self, 1)


def test_get_object_type_wraps_unexpected_error() -> None:
    """Any other failure fetching the type surfaces as ObjectsManagerGetTypeError."""
    mock_self = MagicMock()
    mock_self.get_one_from_other_collection.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerGetTypeError):
        ObjectsManager.get_object_type(mock_self, 1)


def test_find_objects_wraps_unexpected_error() -> None:
    """A generic failure in the find surfaces as ObjectsManagerGetError."""
    mock_self = MagicMock()
    mock_self.find.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerGetError):
        ObjectsManager.find_objects(mock_self, {'public_id': 1})


def test_get_new_object_public_id_wraps_get_error() -> None:
    """A BaseManagerGetError from the id counter surfaces as ObjectsManagerGetError."""
    mock_self = MagicMock()
    mock_self.get_next_public_id.side_effect = BaseManagerGetError('boom')

    with pytest.raises(ObjectsManagerGetError):
        ObjectsManager.get_new_object_public_id(mock_self)


def test_aggregate_objects_wraps_iteration_error() -> None:
    """A BaseManagerIterationError from the aggregation surfaces as ObjectsManagerIterationError."""
    mock_self = MagicMock()
    mock_self.aggregate.side_effect = BaseManagerIterationError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.aggregate_objects(mock_self, [])


def test_set_location_field_for_objects_wraps_unexpected_error() -> None:
    """A failure writing the mirrored location field surfaces as ObjectsManagerUpdateError."""
    mock_self = MagicMock()
    mock_self.update_many_raw.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.set_location_field_for_objects(mock_self, [1], 5)


def test_get_summary_line_wraps_unexpected_error() -> None:
    """A failure while composing a summary line surfaces as ObjectsManagerSummaryLineError."""
    mock_self = MagicMock()
    mock_self.get_object.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerSummaryLineError):
        ObjectsManager.get_summary_line(mock_self, 1)


def test_bulk_update_multi_data_sections_wraps_failure() -> None:
    """A failing bulk write surfaces as ObjectsManagerUpdateError."""
    mock_self = MagicMock()
    mock_self.bulk_write.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.bulk_update_multi_data_sections(mock_self, [MagicMock(public_id=1, multi_data_sections=[])])


def test_group_objects_by_value_wraps_failure_and_skips_match_stage() -> None:
    """With no match filter and a failing aggregation the error surfaces as ObjectsManagerIterationError."""
    mock_self = MagicMock()
    mock_self.aggregate_objects.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.group_objects_by_value(mock_self, 'type_id', match=None)


def test_delete_object_wraps_get_type_error_as_delete_error() -> None:
    """An ObjectsManagerGetError while resolving the type surfaces as ObjectsManagerDeleteError."""
    mock_self = MagicMock()
    mock_self.get_one.return_value = {'public_id': 1, 'type_id': 5}
    mock_self._guard_writable_type.side_effect = ObjectsManagerGetError('boom')

    with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=5)):
        with pytest.raises(ObjectsManagerDeleteError):
            ObjectsManager.delete_object(mock_self, 1)


def test_get_mds_references_for_object_wraps_failure() -> None:
    """A failing cross-collection aggregation surfaces as ObjectsManagerIterationError."""
    mock_self = MagicMock()
    mock_self.aggregate_from_other_collection.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.get_mds_references_for_object(mock_self, MagicMock(type_id=5, public_id=1), {'$match': {}})


def _references_self() -> MagicMock:
    """A MagicMock self for references() with the reference-match builder stubbed to an empty list."""
    mock_self = MagicMock()
    mock_self._build_reference_match_queries.return_value = []
    return mock_self


def test_references_wraps_mds_references_error() -> None:
    """An ObjectsManagerMdsReferencesError from the MDS lookup surfaces as ObjectsManagerIterationError."""
    mock_self = _references_self()
    mock_self.get_mds_references_for_object.side_effect = ObjectsManagerMdsReferencesError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.references(mock_self, MagicMock(public_id=1, type_id=5), {}, 0, 0, 'public_id', 1)


def test_references_reraises_iteration_error() -> None:
    """An ObjectsManagerIterationError from the object iteration is re-raised unchanged."""
    mock_self = _references_self()
    mock_self.iterate.side_effect = ObjectsManagerIterationError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.references(mock_self, MagicMock(public_id=1, type_id=5), {}, 0, 0, 'public_id', 1)


def test_references_wraps_unexpected_error() -> None:
    """Any other failure while resolving references surfaces as ObjectsManagerIterationError."""
    mock_self = _references_self()
    mock_self.iterate.side_effect = RuntimeError('boom')

    with pytest.raises(ObjectsManagerIterationError):
        ObjectsManager.references(mock_self, MagicMock(public_id=1, type_id=5), {}, 0, 0, 'public_id', 1)


# -------------------------------------------------------------------------------------------------------------------- #
#                                     the shared write guard and the delete ordering                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardWritableType:
    """
    The one place a write checks the type exists, is active, and that the ACL allows it

    Insert, update and delete wrote the three checks out separately, with three different errors for
    the missing type and three copies of the deactivated-type message.
    """

    def test_it_resolves_the_type_when_none_was_given(self) -> None:
        """The ordinary path: one lookup, and the resolved type handed back to the caller."""
        mock_self = MagicMock()
        object_type = MagicMock(active=True)
        mock_self.get_object_type.return_value = object_type

        with patch(f'{PATH}.verify_access'):
            resolved = ObjectsManager._guard_writable_type(  # pylint: disable=protected-access
                mock_self, OWNER_TYPE_ID, None, None, ObjectsManagerDeleteError, 'removed',
            )

        mock_self.get_object_type.assert_called_once_with(OWNER_TYPE_ID)
        assert resolved is object_type

    def test_a_supplied_type_skips_the_lookup(self) -> None:
        """
        What keeps a bulk delete from resolving the same type once per object

        The caller holding a type map passes it in, and the guard trusts it.
        """
        mock_self = MagicMock()
        object_type = MagicMock(active=True)

        with patch(f'{PATH}.verify_access'):
            ObjectsManager._guard_writable_type(  # pylint: disable=protected-access
                mock_self, OWNER_TYPE_ID, None, None, ObjectsManagerDeleteError, 'removed', object_type,
            )

        mock_self.get_object_type.assert_not_called()

    def test_a_missing_type_raises_the_callers_own_error(self) -> None:
        """
        Each write reports its own operation

        An insert failing because the type is gone must not surface as a delete error.
        """
        mock_self = MagicMock()
        mock_self.get_object_type.return_value = None

        with pytest.raises(ObjectsManagerInsertError):
            ObjectsManager._guard_writable_type(  # pylint: disable=protected-access
                mock_self, OWNER_TYPE_ID, None, None, ObjectsManagerInsertError, 'created',
            )

    def test_a_deactivated_type_is_refused_with_the_action_in_the_message(self) -> None:
        """The message tells the user what they were trying to do, which is why 'action' is passed."""
        mock_self = MagicMock()
        mock_self.get_object_type.return_value = MagicMock(active=False, name='Server')

        with pytest.raises(AccessDeniedError) as caught:
            ObjectsManager._guard_writable_type(  # pylint: disable=protected-access
                mock_self, OWNER_TYPE_ID, None, None, ObjectsManagerUpdateError, 'updated',
            )

        assert 'updated' in str(caught.value)

    def test_the_acl_is_consulted_with_the_user_and_permission(self) -> None:
        """The ACL check is the guard's last step, and it is the type's ACL that decides."""
        mock_self = MagicMock()
        object_type = MagicMock(active=True)
        mock_self.get_object_type.return_value = object_type
        user = MagicMock()

        with patch(f'{PATH}.verify_access') as verify:
            ObjectsManager._guard_writable_type(  # pylint: disable=protected-access
                mock_self, OWNER_TYPE_ID, user, AccessControlPermission.DELETE,
                ObjectsManagerDeleteError, 'removed',
            )

        verify.assert_called_once_with(object_type, user, AccessControlPermission.DELETE)


class TestDeleteWithFollowUpChecksAccessFirst:
    """
    The ordering defect: the ISMS cascade used to run before the permission check

    A delete the caller was not allowed to make answered 403 with the object's risk assessments and
    their control-measure assignments already deleted - the object survived, its risk history did not.
    """

    def test_a_refused_delete_leaves_the_risk_assessments_alone(self) -> None:
        """Nothing is deleted when the guard refuses - not the cascade, not the object."""
        mock_self = MagicMock()
        mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}
        mock_self._guard_writable_type.side_effect = AccessDeniedError('denied')

        with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)):
            with pytest.raises(AccessDeniedError):
                ObjectsManager.delete_with_follow_up(mock_self, OWNER_OBJECT_ID, MagicMock(),
                                                     AccessControlPermission.DELETE)

        mock_self.delete_object_from_risk_assessment_cascade.assert_not_called()
        mock_self.delete_object.assert_not_called()

    def test_a_permitted_delete_cascades_then_deletes(self) -> None:
        """The order the ISMS data depends on: guard, cascade, delete."""
        mock_self = MagicMock()
        mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}
        order: list[str] = []
        mock_self._guard_writable_type.side_effect = lambda *_a, **_k: order.append('guard')
        mock_self.delete_object_from_risk_assessment_cascade.side_effect = lambda *_: order.append('cascade')
        mock_self.delete_object.side_effect = lambda *_a, **_k: order.append('delete') or True

        with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)):
            assert ObjectsManager.delete_with_follow_up(mock_self, OWNER_OBJECT_ID) is True

        assert order == ['guard', 'cascade', 'delete']

    def test_a_missing_object_neither_cascades_nor_raises(self) -> None:
        """
        There is nothing to authorise and nothing to delete

        Cascading here would delete the risk assessments of an object that is already gone, on a call
        that answers False.
        """
        mock_self = MagicMock()
        mock_self.get_one.return_value = None

        assert ObjectsManager.delete_with_follow_up(mock_self, OWNER_OBJECT_ID) is False
        mock_self.delete_object_from_risk_assessment_cascade.assert_not_called()

    def test_the_resolved_type_is_handed_to_the_delete(self) -> None:
        """The guard already resolved it, so delete_object must not look it up a second time."""
        mock_self = MagicMock()
        mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}
        object_type = MagicMock(active=True)
        mock_self._guard_writable_type.return_value = object_type

        with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)):
            ObjectsManager.delete_with_follow_up(mock_self, OWNER_OBJECT_ID)

        assert mock_self.delete_object.call_args.args[3] is object_type

    def test_a_failing_read_is_wrapped(self) -> None:
        """The read happens outside delete_object now, so it needs its own mapping."""
        mock_self = MagicMock()
        mock_self.get_one.side_effect = RuntimeError('boom')

        with pytest.raises(ObjectsManagerDeleteError):
            ObjectsManager.delete_with_follow_up(mock_self, OWNER_OBJECT_ID)


class TestTheSharedRiskAssessmentCascade:
    """One implementation for the single and the batched form."""

    def test_the_single_form_filters_on_one_object_id(self) -> None:
        """Both public methods are thin wrappers over the shared criterion."""
        mock_self = MagicMock()

        ObjectsManager.delete_object_from_risk_assessment_cascade(mock_self, OWNER_OBJECT_ID)

        mock_self._delete_risk_assessments_of_objects.assert_called_once_with(OWNER_OBJECT_ID)

    def test_the_batched_form_filters_with_an_in_clause(self) -> None:
        """One '$in' query per collection instead of a round trip per object."""
        mock_self = MagicMock()

        ObjectsManager.delete_objects_from_risk_assessment_cascade(mock_self, [1, 2, 3])

        mock_self._delete_risk_assessments_of_objects.assert_called_once_with({'$in': [1, 2, 3]})

    def test_the_batched_form_does_nothing_for_an_empty_list(self) -> None:
        """A bulk delete of nothing must not query, let alone delete."""
        mock_self = MagicMock()

        ObjectsManager.delete_objects_from_risk_assessment_cascade(mock_self, [])

        mock_self._delete_risk_assessments_of_objects.assert_not_called()

    def test_only_assessments_of_OBJECT_reference_type_are_deleted(self) -> None:
        """
        An assessment of an ObjectGroup that happens to share the public_id belongs to another cascade

        The two counters are independent, so overlapping ids are the normal case.
        """
        mock_self = MagicMock()
        mock_self.dbm.find.return_value = []

        ObjectsManager._delete_risk_assessments_of_objects(  # pylint: disable=protected-access
            mock_self, OWNER_OBJECT_ID,
        )

        criteria = mock_self.dbm.find.call_args.args[2]

        assert criteria['object_id_ref_type'] == 'OBJECT'
        assert criteria['object_id'] == OWNER_OBJECT_ID

    def test_nothing_is_deleted_when_no_assessment_matches(self) -> None:
        """The common case: an object nobody assessed costs one query and no deletes."""
        mock_self = MagicMock()
        mock_self.dbm.find.return_value = []

        ObjectsManager._delete_risk_assessments_of_objects(  # pylint: disable=protected-access
            mock_self, OWNER_OBJECT_ID,
        )

        mock_self.delete_many_from_other_collection.assert_not_called()

    def test_the_assignments_are_deleted_by_the_assessment_ids(self) -> None:
        """
        Read first, delete second: the assignments are found by the ids of the assessments going away

        Deleting the assessments first would leave nothing to look their assignments up by.
        """
        mock_self = MagicMock()
        mock_self.dbm.find.return_value = [{'public_id': 11}, {'public_id': 12}]

        ObjectsManager._delete_risk_assessments_of_objects(  # pylint: disable=protected-access
            mock_self, OWNER_OBJECT_ID,
        )

        assessments_call, assignments_call = mock_self.delete_many_from_other_collection.call_args_list

        assert assessments_call.args[1] == {'public_id': {'$in': [11, 12]}}
        assert assignments_call.args[1] == {'risk_assessment_id': {'$in': [11, 12]}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                  the ACL arms: refused, skipped, and re-raised                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAccessDeniedTravelsUnwrapped:
    """
    A denial is not a manager failure

    Every write and single read re-raises AccessDeniedError as-is, so the route can answer 403 rather
    than the 400 its manager-error arm would produce.
    """

    def test_insert_re_raises_a_denial(self) -> None:
        """The guard refuses, and the insert must not turn that into an insert error."""
        mock_self = MagicMock()
        mock_self._guard_writable_type.side_effect = AccessDeniedError('denied')

        with pytest.raises(AccessDeniedError):
            ObjectsManager.insert_object(
                mock_self,
                {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID, 'author_id': 1, 'fields': []},
            )

        mock_self.insert.assert_not_called()

    def test_update_re_raises_a_denial(self) -> None:
        """Same on the update path."""
        mock_self = MagicMock()
        mock_self._guard_writable_type.side_effect = AccessDeniedError('denied')

        with pytest.raises(AccessDeniedError):
            ObjectsManager.update_object(mock_self, OWNER_OBJECT_ID, {'type_id': OWNER_TYPE_ID, 'fields': []})

        mock_self.update.assert_not_called()

    def test_a_single_read_re_raises_a_denial(self) -> None:
        """
        Reading one object the caller may not see is a 403, not an empty result

        The list reads below are the deliberate exception to that.
        """
        mock_self = MagicMock()
        mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}

        with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)), \
             patch(f'{PATH}.verify_access', side_effect=AccessDeniedError('denied')):
            with pytest.raises(AccessDeniedError):
                ObjectsManager.get_object(mock_self, OWNER_OBJECT_ID, MagicMock(), 'READ')

    def test_a_denial_raised_outside_the_per_object_loop_propagates(self) -> None:
        """
        get_objects_by skips the objects the caller may not see - but only those

        A denial from the query itself is a real refusal and reaches the caller.
        """
        mock_self = MagicMock()
        mock_self.get_many.side_effect = AccessDeniedError('denied')

        with pytest.raises(AccessDeniedError):
            ObjectsManager.get_objects_by(mock_self, user=MagicMock(), permission='READ')


class TestListReadsSkipWhatTheCallerMayNotSee:
    """The deliberate exception: a list is filtered rather than refused."""

    def test_get_objects_by_drops_the_inaccessible_objects(self) -> None:
        """
        Two objects, one type the caller may not read - the other object is still returned

        Which also means the list is the caller's list, not the collection's.
        """
        mock_self = MagicMock()
        mock_self.get_many.return_value = [{'type_id': 1}, {'type_id': 2}]
        mock_self._load_types_lookup.return_value = {1: 'allowed-type', 2: 'denied-type'}

        def _verify(object_type: Any, *_args: Any) -> None:
            if object_type == 'denied-type':
                raise AccessDeniedError('denied')

        with patch(f'{PATH}.CmdbObject.from_data', side_effect=lambda doc: MagicMock(type_id=doc['type_id'])), \
             patch(f'{PATH}.verify_access', side_effect=_verify):
            result = ObjectsManager.get_objects_by(mock_self, user=MagicMock(), permission='READ')

        assert [item.type_id for item in result] == [1]

    def test_group_objects_by_value_drops_the_inaccessible_groups(self) -> None:
        """
        The same rule on the grouped read, which feeds the object-count widgets

        So a count shown to a restricted user is their count, not the total.
        """
        mock_self = MagicMock()
        mock_self.aggregate_objects.return_value = [{'result': {'type_id': 1}}, {'result': {'type_id': 2}}]
        mock_self.get_object_type.side_effect = lambda type_id: type_id

        def _verify(object_type: Any, *_args: Any) -> None:
            if object_type == 2:
                raise AccessDeniedError('denied')

        with patch(f'{PATH}.CmdbObject.from_data', side_effect=lambda doc: MagicMock(type_id=doc['type_id'])), \
             patch(f'{PATH}.verify_access', side_effect=_verify):
            grouped = ObjectsManager.group_objects_by_value(
                mock_self, 'type_id', user=MagicMock(), permission='READ',
            )

        assert grouped == [{'result': {'type_id': 1}}]


class TestTheFilterShapesBothQueryBuildersAccept:
    """A criterion may be one match stage or a whole pipeline, and both paths are live."""

    def test_the_mds_reference_query_accepts_a_single_match(self) -> None:
        """A dict filter is appended as one stage."""
        mock_self = MagicMock()
        mock_self.aggregate_from_other_collection.return_value = []
        referenced = MagicMock(type_id=OWNER_TYPE_ID)

        ObjectsManager.get_mds_references_for_object(mock_self, referenced, {'$match': {'active': True}})

        pipeline = mock_self.aggregate_from_other_collection.call_args.args[1]

        assert {'$match': {'active': True}} in pipeline

    def test_the_reference_query_accepts_a_single_match(self) -> None:
        """The same shape on the reference lookup."""
        mock_self = MagicMock()
        mock_self._build_reference_match_queries.return_value = []

        with patch(f'{PATH}.BuilderParameters') as builder_params:
            ObjectsManager.references(mock_self, MagicMock(), {'$match': {'active': True}}, 10, 0, 'public_id', 1)

        pipeline = builder_params.call_args.kwargs['criteria']

        assert {'$match': {'active': True}} in pipeline


class TestTheMdsMerge:
    """Merging the MDS reference hits into the ordinary ones."""

    def test_the_mds_reference_query_tolerates_no_filter_at_all(self) -> None:
        """
        A criterion that is neither a match nor a pipeline contributes nothing

        Pinned as tolerated rather than refused: the reference lookup is called internally with
        whatever the route parsed, and an empty search there means "no extra filter", not an error.
        """
        mock_self = MagicMock()
        mock_self.aggregate_from_other_collection.return_value = []

        ObjectsManager.get_mds_references_for_object(mock_self, MagicMock(type_id=OWNER_TYPE_ID), None)

        pipeline = mock_self.aggregate_from_other_collection.call_args.args[1]

        assert all('$match' not in str(stage) or 'fields' in str(stage) for stage in pipeline[:1])

    def test_the_reference_query_tolerates_no_filter_at_all(self) -> None:
        """The same tolerance on the reference lookup."""
        mock_self = MagicMock()
        mock_self._build_reference_match_queries.return_value = []

        with patch(f'{PATH}.BuilderParameters') as builder_params:
            ObjectsManager.references(mock_self, MagicMock(), None, 10, 0, 'public_id', 1)

        assert isinstance(builder_params.call_args.kwargs['criteria'], list)
