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
Unit tests for cmdb.manager.objects_reference_helper

An object is referenced either by a plain `ref` field - which the database can match - or from inside a
multi-data-section row, which it cannot: those candidates come back from a broader query and are
filtered here, row by row. Everything under test is pure, so the manager's reads are represented by
what it would have passed in: the candidate documents and the ref-field names it resolved per type.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.manager.objects_manager import ObjectsManagerMdsReferencesError
from cmdb.manager.objects_reference_helper import (
    build_reference_match_queries,
    filter_mds_results_referencing,
    merge_mds_references,
    mds_rows_reference,
)
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_OBJECT_ID: int = 701

PATH: str = 'cmdb.manager.objects_reference_helper'


# -------------------------------------------------------------------------------------------------------------------- #
#                                        _build_reference_match_queries                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_reference_match_queries_uses_exact_type_id_match() -> None:
    """The field-ref query matches ref_types by exact type_id (no substring regex) plus a section query"""
    object_ = MagicMock()
    object_.type_id = OWNER_TYPE_ID

    field_query, section_query = build_reference_match_queries(object_)

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

    assert mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is True


def test_mds_rows_reference_false_when_field_not_a_ref_field() -> None:
    """A matching value in a non-ref field name is ignored"""
    result = _mds_doc('not-a-ref', OWNER_OBJECT_ID)

    assert mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is False


def test_mds_rows_reference_false_when_value_differs() -> None:
    """A ref field pointing at a different id does not match"""
    result = _mds_doc('mds-ref', OTHER_OWNER_OBJECT_ID)

    assert mds_rows_reference(result, {'mds-ref'}, OWNER_OBJECT_ID) is False


def test_mds_rows_reference_false_when_no_sections() -> None:
    """An object without multi_data_sections never matches"""
    assert mds_rows_reference({}, {'mds-ref'}, OWNER_OBJECT_ID) is False



# -------------------------------------------------------------------------------------------------------------------- #
#                                        _filter_mds_results_referencing                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_filter_mds_results_referencing_keeps_only_matching_rows() -> None:
    """
    Keeps the results whose MDS rows reference the target, and reads nothing to decide it

    The ref-field names per type are resolved by the MANAGER in one query and handed in, which is what
    keeps this a per-row decision rather than a per-row type fetch.
    """
    keep = {'public_id': 1, 'type_id': OWNER_TYPE_ID,
            'multi_data_sections': [{'values': [{'data': [
                {'name': 'mds-ref', 'value': OWNER_OBJECT_ID}]}]}]}
    drop = {'public_id': 2, 'type_id': OWNER_TYPE_ID,
            'multi_data_sections': [{'values': [{'data': [
                {'name': 'mds-ref', 'value': 999}]}]}]}

    result = filter_mds_results_referencing([keep, drop], OWNER_OBJECT_ID, {OWNER_TYPE_ID: {'mds-ref'}})

    assert result == [keep]


def test_filter_mds_results_referencing_without_names_for_a_type_keeps_nothing() -> None:
    """A type the manager resolved no ref fields for cannot reference anything through MDS"""
    candidate = {'public_id': 1, 'type_id': OWNER_TYPE_ID,
                 'multi_data_sections': [{'values': [{'data': [
                     {'name': 'mds-ref', 'value': OWNER_OBJECT_ID}]}]}]}

    assert filter_mds_results_referencing([candidate], OWNER_OBJECT_ID, {}) == []



def test_merge_mds_references_wraps_failure() -> None:
    """A failure while merging MDS references surfaces as ObjectsManagerMdsReferencesError."""
    obj_result = MagicMock()
    obj_result.results = []
    with patch(f'{PATH}.CmdbObject.from_data', side_effect=RuntimeError('boom')):
        with pytest.raises(ObjectsManagerMdsReferencesError):
            merge_mds_references([{'public_id': 9}], obj_result, 0, 0, 'public_id', 1)



    def test_an_object_already_referenced_is_not_added_twice(self) -> None:
        """
        The same object can be reached through a normal field AND an MDS row

        It is one node in the result, which is what the referenced-ids set is for.
        """
        existing = MagicMock(public_id=7)
        obj_result = MagicMock(results=[existing], total=1)

        with patch(f'{PATH}.CmdbObject.from_data', return_value=MagicMock(public_id=7)):
            merged = merge_mds_references([{'public_id': 7}], obj_result, 0, 0, 'public_id', 1)

        assert merged.total == 1
        assert merged.results == [existing]
