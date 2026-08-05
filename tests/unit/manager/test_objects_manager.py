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
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerUpdateError,
    ObjectsManagerDeleteError,
)
from cmdb.errors.security import AccessDeniedError
from cmdb.manager.objects_manager import ObjectsManager
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
#                                             _compose_summary_line                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_summary_line_returns_default_prefix_when_type_has_no_summaries() -> None:
    """A type without summaries yields 'label #id' as the entire line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_line_omits_type_label_when_with_type_is_false() -> None:
    """with_type=False yields '#id' without the type label prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock, with_type=False)

    assert result == f"#{OWNER_OBJECT_ID}"


def test_compose_summary_line_appends_summary_fields_with_separators() -> None:
    """Type with summary fields appends '- first | second' to the default prefix"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
        {'name': 'fqdn', 'value': 'web01.example.com'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'fqdn'}],
    )

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01 | web01.example.com"


def test_compose_summary_line_falls_back_to_default_when_field_walk_raises() -> None:
    """An exception while walking summary fields produces the default prefix and does not raise"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)  # 'fields' is []
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server', has_summaries=True)
    type_mock.get_summary.side_effect = RuntimeError('boom')

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID}"


def test_compose_summary_line_emits_none_for_missing_field_value() -> None:
    """A summary field absent from the object's fields list shows up as None in the line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID, fields=[
        {'name': 'hostname', 'value': 'web01'},
    ])
    type_mock = _make_type_mock(
        OWNER_TYPE_ID, 'Server',
        has_summaries=True,
        summary_fields=[{'name': 'hostname'}, {'name': 'missing'}],
    )

    result = ObjectsManager._compose_summary_line(MagicMock(), obj_doc, type_mock)

    assert result == f"Server #{OWNER_OBJECT_ID} - web01 | None"


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _load_types_lookup                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_types_lookup_returns_empty_dict_for_empty_type_ids() -> None:
    """No type ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager._load_types_lookup(mock_self, [])

    assert result == {}
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
    """When the object + type both resolve, composition is delegated to _compose_summary_line"""
    obj_doc = _make_object_doc(OWNER_OBJECT_ID, OWNER_TYPE_ID)
    type_mock = _make_type_mock(OWNER_TYPE_ID, 'Server')
    mock_self = MagicMock()
    mock_self.get_object.return_value = obj_doc
    mock_self.get_object_type.return_value = type_mock
    mock_self._compose_summary_line.return_value = f"Server #{OWNER_OBJECT_ID}"

    result = ObjectsManager.get_summary_line(mock_self, OWNER_OBJECT_ID, with_type=True)

    assert result == f"Server #{OWNER_OBJECT_ID}"
    mock_self._compose_summary_line.assert_called_once_with(obj_doc, type_mock, with_type=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_summary_lines_lookup                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_summary_lines_lookup_returns_empty_dict_for_empty_input() -> None:
    """No public_ids → empty result and no DB call issued"""
    mock_self = MagicMock()

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [])

    assert result == {}
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

    assert result == {}


def test_get_summary_lines_lookup_skips_object_with_non_int_type_id() -> None:
    """Objects whose type_id is non-integer never look up a CmdbType and are excluded"""
    obj = {'public_id': OWNER_OBJECT_ID, 'type_id': None, 'fields': []}
    mock_self = MagicMock()
    mock_self.find_objects.return_value = [obj]
    mock_self._load_types_lookup.return_value = {}

    result = ObjectsManager.get_summary_lines_lookup(mock_self, [OWNER_OBJECT_ID])

    assert result == {}


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
#                                        _build_reference_match_queries                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_reference_match_queries_uses_exact_type_id_match() -> None:
    """The field-ref query matches ref_types by exact type_id (no substring regex) plus a section query"""
    object_ = MagicMock()
    object_.type_id = OWNER_TYPE_ID

    field_query, section_query = ObjectsManager._build_reference_match_queries(object_)

    assert field_query == {
        'type.fields.type': FieldType.REFERENCE.value,
        'type.fields.ref_types': OWNER_TYPE_ID,
    }
    # No leftover regex/$or branch
    assert '$or' not in field_query
    assert section_query == {
        'type.render_meta.sections.type': SectionType.REF_SECTION.value,
        'type.render_meta.sections.reference.type_id': OWNER_TYPE_ID,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _mds_rows_reference                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _mds_doc(field_name: str, value: Any) -> dict[str, Any]:
    """A CmdbObject doc with one multi-data-section row carrying a single field."""
    return {
        'multi_data_sections': [
            {'values': [{'data': [{'type': 'ref', 'name': field_name, 'value': value}]}]}
        ]
    }


def test_mds_rows_reference_true_when_ref_field_points_at_target() -> None:
    """Returns True when a ref-named MDS field holds the referenced public_id"""
    result = _mds_doc('mds-ref', OWNER_OBJECT_ID)

    assert ObjectsManager._mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is True


def test_mds_rows_reference_false_when_field_not_a_ref_field() -> None:
    """A matching value in a non-ref field name is ignored"""
    result = _mds_doc('not-a-ref', OWNER_OBJECT_ID)

    assert ObjectsManager._mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is False


def test_mds_rows_reference_false_when_value_differs() -> None:
    """A ref field pointing at a different id does not match"""
    result = _mds_doc('mds-ref', OTHER_OWNER_OBJECT_ID)

    assert ObjectsManager._mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is False


def test_mds_rows_reference_false_when_no_sections() -> None:
    """An object without multi_data_sections never matches"""
    assert ObjectsManager._mds_rows_reference({}, {'mds-ref'}, OWNER_OBJECT_ID) is False


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
#                                        _filter_mds_results_referencing                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_filter_mds_results_referencing_keeps_only_matching_rows() -> None:
    """Keeps results whose MDS rows reference the target and resolves ref names in one batch"""
    keep = {'public_id': 1, 'type_id': OWNER_TYPE_ID}
    drop = {'public_id': 2, 'type_id': OWNER_TYPE_ID}
    mock_self = MagicMock()
    mock_self._ref_field_names_by_type.return_value = {OWNER_TYPE_ID: {'mds-ref'}}
    mock_self._mds_rows_reference.side_effect = [True, False]

    result = ObjectsManager._filter_mds_results_referencing(mock_self, [keep, drop], OWNER_OBJECT_ID)

    assert result == [keep]
    # The type ref-field names are resolved exactly once (batched), not per row
    mock_self._ref_field_names_by_type.assert_called_once_with([OWNER_TYPE_ID])


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
    """A missing CmdbType surfaces as ObjectsManagerUpdateError, not an AttributeError"""
    mock_self = MagicMock()
    mock_self.get_object_type.return_value = None

    with pytest.raises(ObjectsManagerUpdateError):
        ObjectsManager.update_object(mock_self, OWNER_OBJECT_ID, {'type_id': OWNER_TYPE_ID, 'fields': []})


def test_delete_object_returns_false_for_missing_object() -> None:
    """A missing object short-circuits to False before any type/permission work"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = None

    assert ObjectsManager.delete_object(mock_self, MISSING := 9999) is False
    mock_self.get_object_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          count_objects_grouped_by_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_count_objects_grouped_by_type_maps_type_id_to_count() -> None:
    """Each aggregation bucket becomes a type_id -> count entry in the returned dict"""
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = [
        {'_id': OWNER_TYPE_ID, 'count': 30},
        {'_id': OTHER_OWNER_TYPE_ID, 'count': 12},
    ]

    result = ObjectsManager.count_objects_grouped_by_type(mock_self)

    assert result == {OWNER_TYPE_ID: 30, OTHER_OWNER_TYPE_ID: 12}


def test_count_objects_grouped_by_type_skips_non_int_id() -> None:
    """A bucket whose _id is not an int (e.g. a null type_id) is left out of the result"""
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = [
        {'_id': OWNER_TYPE_ID, 'count': 5},
        {'_id': None, 'count': 3},
    ]

    result = ObjectsManager.count_objects_grouped_by_type(mock_self)

    assert result == {OWNER_TYPE_ID: 5}


def test_count_objects_grouped_by_type_uses_single_group_aggregation() -> None:
    """The count runs one $group stage (not one count per type)"""
    mock_self = MagicMock()
    mock_self.aggregate_objects.return_value = []

    ObjectsManager.count_objects_grouped_by_type(mock_self)

    pipeline = mock_self.aggregate_objects.call_args.args[0]
    assert pipeline == [{'$group': {'_id': '$type_id', 'count': {'$sum': 1}}}]


def test_delete_object_raises_when_type_missing() -> None:
    """A present object whose type is gone surfaces as ObjectsManagerDeleteError, not AttributeError"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = {'public_id': OWNER_OBJECT_ID, 'type_id': OWNER_TYPE_ID}
    mock_self.get_object_type.return_value = None

    with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(type_id=OWNER_TYPE_ID)):
        with pytest.raises(ObjectsManagerDeleteError):
            ObjectsManager.delete_object(mock_self, OWNER_OBJECT_ID)
