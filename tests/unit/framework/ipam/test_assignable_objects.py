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
Unit tests for cmdb.framework.ipam.assignable_objects

Covers find_ipam_capable_type_ids (Mongo criteria shape + result mapping), the in-module
helpers (_build_type_label_lookup, _build_row, _apply_search), and the orchestrator
build_assignable_objects_page (empty-capable short-circuit, summary-line search filter,
pagination slicing, post-filter total). ObjectsManager / TypesManager are MagicMock
stand-ins so no Mongo is touched
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamPagination,
    IpamSearch,
    IpamSection,
)
from cmdb.framework.ipam.assignable_objects import (
    _apply_search,
    _build_row,
    _build_type_label_lookup,
    _shape_rows,
    build_assignable_objects_page,
    find_ipam_capable_type_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TEST CONSTANTS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12

SERVER_LABEL: str = 'Server'
ROUTER_LABEL: str = 'Router'

OBJECT_ID_A: int = 101
OBJECT_ID_B: int = 102
OBJECT_ID_C: int = 103
OBJECT_ID_D: int = 104

SUMMARY_LINE_A: str = 'Server #101 - alpha'
SUMMARY_LINE_B: str = 'Server #102 - bravo'
SUMMARY_LINE_C: str = 'Router #103 - charlie'
SUMMARY_LINE_D: str = 'Router #104 - delta'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  FACTORIES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_type_mock(public_id: int, label: str) -> MagicMock:
    """Builds a CmdbType-shaped MagicMock exposing public_id and label."""
    type_mock = MagicMock()
    type_mock.public_id = public_id
    type_mock.label = label

    return type_mock


def _make_object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a CmdbObject dict carrying just the keys the assignable-objects pipeline reads."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                       find_ipam_capable_type_ids                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_ipam_capable_type_ids_returns_empty_when_no_match() -> None:
    """No type carries the dg-ipam-interface section → empty list, no fall-through to find_objects"""
    types_manager = MagicMock()
    types_manager.find_types.return_value = []

    assert find_ipam_capable_type_ids(types_manager) == []


def test_find_ipam_capable_type_ids_returns_all_matching_type_ids() -> None:
    """Every matching type's public_id is projected out in result order"""
    types_manager = MagicMock()
    types_manager.find_types.return_value = [
        _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
        _make_type_mock(ROUTER_TYPE_ID, ROUTER_LABEL),
    ]

    assert find_ipam_capable_type_ids(types_manager) == [SERVER_TYPE_ID, ROUTER_TYPE_ID]


def test_find_ipam_capable_type_ids_issues_elemmatch_on_interface_section_name() -> None:
    """Mongo criteria is pinned: $elemMatch on render_meta.sections by name == IpamSection.INTERFACE"""
    types_manager = MagicMock()
    types_manager.find_types.return_value = []

    find_ipam_capable_type_ids(types_manager)

    assert types_manager.find_types.call_count == 1
    criteria: dict[str, Any] = types_manager.find_types.call_args.args[0]
    assert criteria == {
        'render_meta.sections': {
            '$elemMatch': {'name': IpamSection.INTERFACE},
        },
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                       _build_type_label_lookup                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_type_label_lookup_short_circuits_on_empty_input() -> None:
    """Empty type_ids → empty dict, no DB call"""
    types_manager = MagicMock()

    assert _build_type_label_lookup(types_manager, []) == {}
    types_manager.get_types_lookup.assert_not_called()


def test_build_type_label_lookup_deduplicates_before_dispatching_the_bulk_call() -> None:
    """Duplicate ids collapse before reaching get_types_lookup so the bulk fetch stays minimal"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
    }

    _build_type_label_lookup(types_manager, [SERVER_TYPE_ID, SERVER_TYPE_ID, SERVER_TYPE_ID])

    forwarded: list[int] = types_manager.get_types_lookup.call_args.args[0]
    assert sorted(forwarded) == [SERVER_TYPE_ID]


def test_build_type_label_lookup_projects_each_type_to_its_label() -> None:
    """The resolved CmdbTypes are projected down to {type_id: label}"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
        ROUTER_TYPE_ID: _make_type_mock(ROUTER_TYPE_ID, ROUTER_LABEL),
    }

    result: dict[int, str] = _build_type_label_lookup(
        types_manager, [SERVER_TYPE_ID, ROUTER_TYPE_ID],
    )

    assert result == {SERVER_TYPE_ID: SERVER_LABEL, ROUTER_TYPE_ID: ROUTER_LABEL}


def test_build_type_label_lookup_omits_types_absent_from_lookup() -> None:
    """A type that no longer resolves is silently absent so callers can fall back per row"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
    }

    result: dict[int, str] = _build_type_label_lookup(
        types_manager, [SERVER_TYPE_ID, ROUTER_TYPE_ID],
    )

    assert result == {SERVER_TYPE_ID: SERVER_LABEL}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _build_row                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_row_shapes_happy_path_payload() -> None:
    """All lookups resolved → row carries public_id, nested type_info, and summary_line verbatim"""
    object_doc: dict[str, Any] = _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID)

    row: dict[str, Any] = _build_row(
        object_doc,
        {OBJECT_ID_A: SUMMARY_LINE_A},
        {SERVER_TYPE_ID: SERVER_LABEL},
    )

    assert row == {
        CmdbObjectKey.PUBLIC_ID: OBJECT_ID_A,
        IpamOverviewKey.TYPE_INFO: {
            CmdbObjectKey.PUBLIC_ID: SERVER_TYPE_ID,
            IpamOverviewKey.LABEL: SERVER_LABEL,
        },
        IpamOverviewKey.SUMMARY_LINE: SUMMARY_LINE_A,
    }


def test_build_row_falls_back_to_empty_summary_when_lookup_misses() -> None:
    """Object absent from summary_lines → empty summary_line, never KeyError"""
    object_doc: dict[str, Any] = _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID)

    row: dict[str, Any] = _build_row(object_doc, {}, {SERVER_TYPE_ID: SERVER_LABEL})

    assert row[IpamOverviewKey.SUMMARY_LINE] == ''


def test_build_row_falls_back_to_empty_label_when_type_missing() -> None:
    """Type absent from type_labels → empty label inside type_info, never KeyError"""
    object_doc: dict[str, Any] = _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID)

    row: dict[str, Any] = _build_row(object_doc, {OBJECT_ID_A: SUMMARY_LINE_A}, {})

    assert row[IpamOverviewKey.TYPE_INFO][IpamOverviewKey.LABEL] == ''


def test_build_row_falls_back_when_public_id_is_missing() -> None:
    """Missing public_id (degenerate doc) → empty summary_line via dict.get fallback"""
    object_doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: None,
        CmdbObjectKey.TYPE_ID: SERVER_TYPE_ID,
    }

    row: dict[str, Any] = _build_row(
        object_doc,
        {OBJECT_ID_A: SUMMARY_LINE_A},
        {SERVER_TYPE_ID: SERVER_LABEL},
    )

    assert row[IpamOverviewKey.SUMMARY_LINE] == ''


def test_build_row_falls_back_when_type_id_is_missing() -> None:
    """Missing type_id (degenerate doc) → empty label via dict.get fallback"""
    object_doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: OBJECT_ID_A,
        CmdbObjectKey.TYPE_ID: None,
    }

    row: dict[str, Any] = _build_row(
        object_doc,
        {OBJECT_ID_A: SUMMARY_LINE_A},
        {SERVER_TYPE_ID: SERVER_LABEL},
    )

    assert row[IpamOverviewKey.TYPE_INFO][IpamOverviewKey.LABEL] == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _apply_search                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def _row_with_summary(summary: Any) -> dict[str, Any]:
    """Minimal row factory for the search-filter tests."""
    return {IpamOverviewKey.SUMMARY_LINE: summary}


def test_apply_search_returns_input_unchanged_when_needle_is_none() -> None:
    """needle=None means 'no filter' - the input list is returned untouched"""
    rows: list[dict[str, Any]] = [
        _row_with_summary(SUMMARY_LINE_A),
        _row_with_summary(SUMMARY_LINE_B),
    ]

    assert _apply_search(rows, None) is rows


def test_apply_search_keeps_rows_whose_summary_contains_the_needle_case_insensitively() -> None:
    """Substring match is case-insensitive on both sides"""
    rows: list[dict[str, Any]] = [
        _row_with_summary(SUMMARY_LINE_A),
        _row_with_summary(SUMMARY_LINE_C),
    ]

    filtered: list[dict[str, Any]] = _apply_search(rows, 'ALPHA')

    assert filtered == [_row_with_summary(SUMMARY_LINE_A)]


def test_apply_search_drops_rows_without_the_needle() -> None:
    """Rows whose summary does not contain the needle drop out of the result list"""
    rows: list[dict[str, Any]] = [
        _row_with_summary(SUMMARY_LINE_A),
        _row_with_summary(SUMMARY_LINE_B),
    ]

    assert _apply_search(rows, 'charlie') == []


def test_apply_search_skips_rows_with_empty_summary_when_filter_is_active() -> None:
    """Empty summary string carries no substring → row is filtered out under any non-empty needle"""
    rows: list[dict[str, Any]] = [
        _row_with_summary(''),
        _row_with_summary(SUMMARY_LINE_A),
    ]

    assert _apply_search(rows, 'alpha') == [_row_with_summary(SUMMARY_LINE_A)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _shape_rows                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_shape_rows_scopes_type_label_lookup_to_types_present_on_objects() -> None:
    """
    Only the type ids actually present on the given docs are looked up - the helper never sees
    capable types that have no objects, so they cannot contribute to the bulk type-label fetch
    """
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OBJECT_ID_A: SUMMARY_LINE_A}

    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
    }

    _shape_rows(
        objects_manager,
        types_manager,
        [_make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID)],
    )

    forwarded: list[int] = types_manager.get_types_lookup.call_args.args[0]
    assert sorted(forwarded) == [SERVER_TYPE_ID]


def test_shape_rows_passes_given_docs_to_summary_lookup_without_refetch() -> None:
    """The already-loaded docs are forwarded via the object_docs kwarg so no per-id re-fetch
    happens; the requested ids mirror the docs in input order"""
    object_docs: list[dict[str, Any]] = [
        _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
        _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID),
    ]
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {
        OBJECT_ID_A: SUMMARY_LINE_A,
        OBJECT_ID_B: SUMMARY_LINE_B,
    }
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
    }

    _shape_rows(objects_manager, types_manager, object_docs)

    objects_manager.find_objects.assert_not_called()
    objects_manager.get_summary_lines_lookup.assert_called_once_with(
        [OBJECT_ID_A, OBJECT_ID_B], with_type=True, object_docs=object_docs,
    )


def test_shape_rows_skips_summary_lookup_when_no_objects() -> None:
    """No docs handed in → no summary-line round-trip is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    result: list[dict[str, Any]] = _shape_rows(objects_manager, types_manager, [])

    assert result == []
    objects_manager.get_summary_lines_lookup.assert_not_called()


def test_shape_rows_preserves_input_order() -> None:
    """Rows come back in the same order as the input docs"""
    object_docs: list[dict[str, Any]] = [
        _make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID),
        _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
        _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID),
    ]
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {}
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}

    rows: list[dict[str, Any]] = _shape_rows(objects_manager, types_manager, object_docs)

    assert [row[CmdbObjectKey.PUBLIC_ID] for row in rows] == [OBJECT_ID_C, OBJECT_ID_A, OBJECT_ID_B]


# -------------------------------------------------------------------------------------------------------------------- #
#                                       build_assignable_objects_page                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='types_manager_two_capable_types')
def fixture_types_manager_two_capable_types() -> MagicMock:
    """TypesManager mock returning Server + Router as IPAM-capable, with labels."""
    types_manager = MagicMock()
    types_manager.find_types.return_value = [
        _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
        _make_type_mock(ROUTER_TYPE_ID, ROUTER_LABEL),
    ]
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
        ROUTER_TYPE_ID: _make_type_mock(ROUTER_TYPE_ID, ROUTER_LABEL),
    }

    return types_manager


@pytest.fixture(name='objects_manager_four_objects')
def fixture_objects_manager_four_objects() -> MagicMock:
    """ObjectsManager mock returning 4 IPAM-eligible objects with pre-computed summary lines."""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
        _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID),
        _make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID),
        _make_object_doc(OBJECT_ID_D, ROUTER_TYPE_ID),
    ]
    objects_manager.get_summary_lines_lookup.return_value = {
        OBJECT_ID_A: SUMMARY_LINE_A,
        OBJECT_ID_B: SUMMARY_LINE_B,
        OBJECT_ID_C: SUMMARY_LINE_C,
        OBJECT_ID_D: SUMMARY_LINE_D,
    }

    return objects_manager


def test_build_assignable_objects_page_short_circuits_when_no_capable_type() -> None:
    """No IPAM-capable type → empty page envelope, find_objects is never called"""
    types_manager = MagicMock()
    types_manager.find_types.return_value = []
    objects_manager = MagicMock()

    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager,
        types_manager,
        page=1,
        page_size=IpamPagination.DEFAULT_PAGE_SIZE,
        search='',
    )

    assert payload[IpamOverviewKey.TOTAL] == 0
    assert payload[IpamOverviewKey.ROWS] == []
    objects_manager.find_objects.assert_not_called()
    objects_manager.get_summary_lines_lookup.assert_not_called()


def test_build_assignable_objects_page_returns_all_rows_on_first_page_when_dataset_fits(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """Page size ≥ total → first page carries every row in find_objects order"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='',
    )

    assert payload[IpamOverviewKey.TOTAL] == 4
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in payload[IpamOverviewKey.ROWS]] == [
        OBJECT_ID_A, OBJECT_ID_B, OBJECT_ID_C, OBJECT_ID_D,
    ]


def test_build_assignable_objects_page_paginates_with_clamped_window(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """page=2, page_size=2 over a 4-row set returns rows 3-4 in input order"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=2,
        page_size=2,
        search='',
    )

    assert payload[IpamOverviewKey.PAGE] == 2
    assert payload[IpamOverviewKey.PAGE_SIZE] == 2
    assert payload[IpamOverviewKey.TOTAL] == 4
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in payload[IpamOverviewKey.ROWS]] == [
        OBJECT_ID_C, OBJECT_ID_D,
    ]


def test_build_assignable_objects_page_search_shrinks_total_to_post_filter_count(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """An active search filter → total reflects post-filter rows, not the unfiltered dataset"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='Router',
    )

    assert payload[IpamOverviewKey.TOTAL] == 2
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in payload[IpamOverviewKey.ROWS]] == [
        OBJECT_ID_C, OBJECT_ID_D,
    ]


def test_build_assignable_objects_page_ignores_search_below_min_query_length(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """A search shorter than IpamSearch.MIN_QUERY_LENGTH is dropped - total stays at the unfiltered count"""
    short_query: str = 'x' * (IpamSearch.MIN_QUERY_LENGTH - 1)

    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search=short_query,
    )

    assert payload[IpamOverviewKey.TOTAL] == 4


def test_build_assignable_objects_page_echoes_raw_search_in_envelope(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """The envelope's 'search' field carries the raw query as received, not the normalized form"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='  Router  ',
    )

    assert payload[IpamOverviewKey.SEARCH] == '  Router  '


def test_build_assignable_objects_page_clamps_out_of_range_page_into_valid_window(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """Requesting a page past the last available page snaps back to the last non-empty page"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=99,
        page_size=2,
        search='',
    )

    assert payload[IpamOverviewKey.PAGE] == 2
    assert payload[IpamOverviewKey.PAGE_SIZE] == 2
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in payload[IpamOverviewKey.ROWS]] == [
        OBJECT_ID_C, OBJECT_ID_D,
    ]


def test_build_assignable_objects_page_queries_objects_by_type_id_in_capable_set(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """Mongo criteria forwarded to find_objects is pinned: type_id ∈ {capable_type_ids}"""
    build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='',
    )

    criteria: dict[str, Any] = objects_manager_four_objects.find_objects.call_args.args[0]
    assert CmdbObjectKey.TYPE_ID in criteria
    assert set(criteria[CmdbObjectKey.TYPE_ID]['$in']) == {SERVER_TYPE_ID, ROUTER_TYPE_ID}


def test_build_assignable_objects_page_row_payload_carries_type_info_and_summary_line(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """A returned row carries public_id, type_info (id + label) and the rendered summary line"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='',
    )

    first_row: dict[str, Any] = payload[IpamOverviewKey.ROWS][0]
    assert first_row[CmdbObjectKey.PUBLIC_ID] == OBJECT_ID_A
    assert first_row[IpamOverviewKey.TYPE_INFO] == {
        CmdbObjectKey.PUBLIC_ID: SERVER_TYPE_ID,
        IpamOverviewKey.LABEL: SERVER_LABEL,
    }
    assert first_row[IpamOverviewKey.SUMMARY_LINE] == SUMMARY_LINE_A


def test_build_assignable_objects_page_without_search_shapes_only_the_page_slice(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """No active search → docs are sliced first and only the page's docs are shaped, so the
    summary-line lookup is scoped to that slice while total reflects the unfiltered count"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=2,
        page_size=2,
        search='',
    )

    assert payload[IpamOverviewKey.TOTAL] == 4

    forwarded_ids, kwargs = objects_manager_four_objects.get_summary_lines_lookup.call_args
    shaped_docs: list[dict[str, Any]] = kwargs['object_docs']
    assert forwarded_ids[0] == [OBJECT_ID_C, OBJECT_ID_D]
    assert [doc[CmdbObjectKey.PUBLIC_ID] for doc in shaped_docs] == [OBJECT_ID_C, OBJECT_ID_D]


def test_build_assignable_objects_page_with_search_shapes_all_docs_and_totals_filtered(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """An active search → every doc is shaped (so the substring filter can run against each
    summary line) while total reflects only the post-filter count"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='Router',
    )

    assert payload[IpamOverviewKey.TOTAL] == 2

    forwarded_ids, kwargs = objects_manager_four_objects.get_summary_lines_lookup.call_args
    shaped_docs: list[dict[str, Any]] = kwargs['object_docs']
    assert forwarded_ids[0] == [OBJECT_ID_A, OBJECT_ID_B, OBJECT_ID_C, OBJECT_ID_D]
    assert [doc[CmdbObjectKey.PUBLIC_ID] for doc in shaped_docs] == [
        OBJECT_ID_A, OBJECT_ID_B, OBJECT_ID_C, OBJECT_ID_D,
    ]
