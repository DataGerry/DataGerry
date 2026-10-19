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

from cmdb.manager.objects_reference_helper import (
    SORT_MISSING_KEY,
    build_reference_id_criteria,
    build_reference_match_queries,
    build_reference_page_query,
    build_reference_page_stages,
    filter_mds_results_referencing,
    is_sortable_path,
    mds_rows_reference,
    merge_reference_ids,
)
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_OBJECT_ID: int = 701


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                             merge_reference_ids                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_merge_reference_ids_keeps_the_field_references_first() -> None:
    """Both halves contribute, in the order they were found"""
    assert merge_reference_ids([{'public_id': 3}, {'public_id': 1}], [{'public_id': 2}]) == [3, 1, 2]


def test_an_object_reached_both_ways_counts_once() -> None:
    """
    The same object can be reached through a normal field AND an MDS row

    It is one row of the listing and one of its total.
    """
    assert merge_reference_ids([{'public_id': 7}], [{'public_id': 7}, {'public_id': 8}]) == [7, 8]


@pytest.mark.parametrize('public_id', [None, '7', True, 7.0], ids=['none', 'string', 'bool', 'float'])
def test_a_row_without_an_integer_id_is_skipped(public_id: Any) -> None:
    """A row naming no object can not be on a page"""
    assert merge_reference_ids([{'public_id': public_id}], [{}]) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_reference_page_stages                                                #
# -------------------------------------------------------------------------------------------------------------------- #
PAGE_IDS: list[int] = [4, 5, 6]


def _stage(stages: list[dict[str, Any]], operator: str) -> Any:
    """The body of the one stage using the operator, or None"""
    bodies = [stage[operator] for stage in stages if operator in stage]

    return bodies[0] if bodies else None


def test_the_page_reads_only_the_referencing_ids() -> None:
    """The first stage narrows the collection to the union"""
    stages = build_reference_page_stages(PAGE_IDS, 2, 1, 'author_id', 1)

    assert stages[0] == {'$match': {'public_id': {'$in': PAGE_IDS}}}


@pytest.mark.parametrize('order', [1, -1], ids=['ascending', 'descending'])
def test_the_missing_flag_is_sorted_first_in_the_requested_direction(order: int) -> None:
    """
    A missing or null value goes last ascending and first descending

    MongoDB alone does the opposite; the flag sorted in the same direction as the key restores it.
    """
    stages = build_reference_page_stages(PAGE_IDS, 0, 0, 'author_id', order)

    assert list(_stage(stages, '$sort').items()) == [
        (SORT_MISSING_KEY, order), ('author_id', order), ('public_id', 1),
    ]
    assert _stage(stages, '$addFields') == {
        SORT_MISSING_KEY: {'$eq': [{'$ifNull': ['$author_id', None]}, None]},
    }


def test_sorting_by_public_id_needs_no_tiebreaker() -> None:
    """The key is unique, so it is not repeated"""
    stages = build_reference_page_stages(PAGE_IDS, 0, 0, 'public_id', -1)

    assert list(_stage(stages, '$sort').items()) == [(SORT_MISSING_KEY, -1), ('public_id', -1)]


@pytest.mark.parametrize('sort', ['', '$where', 'na\x00me'], ids=['empty', 'operator', 'nul'])
def test_a_key_that_is_no_field_path_sorts_by_public_id(sort: str) -> None:
    """The listing never failed over its sort key, so an unusable one orders by id instead of a 400"""
    stages = build_reference_page_stages(PAGE_IDS, 0, 0, sort, 1)

    assert list(_stage(stages, '$sort')) == [SORT_MISSING_KEY, 'public_id']


def test_a_limit_pages_after_the_sort() -> None:
    """skip then limit, behind the sort"""
    stages = build_reference_page_stages(PAGE_IDS, 2, 1, 'author_id', 1)
    operators = [next(iter(stage)) for stage in stages]

    assert operators.index('$sort') < operators.index('$skip') < operators.index('$limit')
    assert _stage(stages, '$skip') == 1
    assert _stage(stages, '$limit') == 2


def test_without_a_limit_every_row_is_answered_and_skip_is_ignored() -> None:
    """A limit of 0 is the whole listing, as it has always been"""
    stages = build_reference_page_stages(PAGE_IDS, 0, 3, 'author_id', 1)

    assert _stage(stages, '$skip') is None
    assert _stage(stages, '$limit') is None


def test_the_flag_and_the_mongo_id_are_projected_away() -> None:
    """The page is plain CmdbObject documents"""
    stages = build_reference_page_stages(PAGE_IDS, 0, 0, 'author_id', 1)

    assert stages[-1] == {'$project': {SORT_MISSING_KEY: 0, '_id': 0}}


@pytest.mark.parametrize('sort, usable', [
    ('author_id', True), ('fields.value', True), ('', False), ('$expr', False), ('a\x00b', False),
])
def test_is_sortable_path(sort: str, usable: bool) -> None:
    """A path is anything but empty, an operator, or a NUL"""
    assert is_sortable_path(sort) is usable

# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_reference_page_query                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('limit, skip, expected_skip', [(5, 10, 10), (0, 10, 0)], ids=['paged', 'unlimited'])
def test_a_fields_sort_uses_the_listings_field_value_sort(limit: int, skip: int, expected_skip: int) -> None:
    """A fields.<name> key sorts like the object listing; skip only applies together with a limit"""
    query_builder = MagicMock()

    with patch('cmdb.manager.objects_reference_helper.BuilderParameters') as builder_params:
        build_reference_page_query(query_builder, [3, 4], limit, skip, 'fields.name', 1)

    assert builder_params.call_args.kwargs == {
        'criteria': {'public_id': {'$in': [3, 4]}}, 'limit': limit, 'skip': expected_skip,
        'sort': 'fields.name', 'order': 1,
    }
    query_builder.build.assert_called_once_with(builder_params.return_value)


def test_any_other_sort_uses_the_reference_page_stages() -> None:
    """Every key but fields.<name> goes through build_reference_page_stages, without the query builder"""
    query_builder = MagicMock()

    stages = build_reference_page_query(query_builder, [3], 5, 0, 'author_id', 1)

    assert stages == build_reference_page_stages([3], 5, 0, 'author_id', 1)
    query_builder.build.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_reference_id_criteria                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('criteria, leading', [
    ({'$match': {'active': True}}, [{'$match': {'active': True}}]),
    ([{'$match': {'a': 1}}, {'$match': {'b': 2}}], [{'$match': {'a': 1}}, {'$match': {'b': 2}}]),
    (None, []),
], ids=['one-stage', 'stages', 'none'])
def test_the_callers_stages_come_first(criteria: Any, leading: list[dict[str, Any]]) -> None:
    """A filter narrows the candidates before the type join"""
    query = build_reference_id_criteria(MagicMock(type_id=OWNER_TYPE_ID, public_id=OWNER_OBJECT_ID), criteria)

    assert query[:len(leading)] == leading
    assert '$lookup' in query[len(leading)]


def test_the_candidate_must_hold_the_referenced_id() -> None:
    """The last stage matches the referenced public_id among the field values"""
    query = build_reference_id_criteria(MagicMock(type_id=OWNER_TYPE_ID, public_id=OWNER_OBJECT_ID), None)

    assert query[-1] == {'$match': {'fields.value': OWNER_OBJECT_ID}}
    assert query[1] == {'$unwind': {'path': '$type', 'preserveNullAndEmptyArrays': True}}
