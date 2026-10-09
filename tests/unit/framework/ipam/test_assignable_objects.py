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
helpers (build_summary_lines, _build_row, _apply_search, _shape_rows - ONE type lookup per page), the two
read paths (read_unsearched_page: a count + one projected, skip/limit-paged find; read_searched_page: one
projected find, filtered and paged in Python), and the orchestrator build_assignable_objects_page
(empty-capable short-circuit, summary-line search filter, pagination, post-filter total).
ObjectsManager / TypesManager are MagicMock stand-ins so no Mongo is touched; the find stand-in honours
skip / limit the way MongoDB does. Both read paths ask for public_id order
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
    ASSIGNABLE_OBJECT_ORDER,
    ASSIGNABLE_OBJECT_PROJECTION,
    _apply_search,
    _build_row,
    _shape_rows,
    build_assignable_objects_page,
    build_summary_lines,
    find_ipam_capable_type_ids,
    read_searched_page,
    read_unsearched_page,
)
from cmdb.framework.ipam import assignable_objects
from cmdb.security.acl.permission import AccessControlPermission
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
#                                            build_summary_lines                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
SUMMARY_LINES: dict[int, str] = {
    OBJECT_ID_A: SUMMARY_LINE_A,
    OBJECT_ID_B: SUMMARY_LINE_B,
    OBJECT_ID_C: SUMMARY_LINE_C,
    OBJECT_ID_D: SUMMARY_LINE_D,
}


@pytest.fixture(autouse=True)
def _canned_summary_lines(monkeypatch: pytest.MonkeyPatch):
    """compose_summary_line answers the canned line of each object, so the tests pin the plumbing, not the text"""
    monkeypatch.setattr(
        assignable_objects, 'compose_summary_line',
        lambda doc, object_type, with_type: SUMMARY_LINES[doc[CmdbObjectKey.PUBLIC_ID]],
    )


def test_build_summary_lines_composes_each_doc_with_its_type() -> None:
    """One line per doc whose type resolved, from the given lookup - no query of its own"""
    lookup = {SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL)}

    lines = build_summary_lines(
        [_make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID), _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID)], lookup,
    )

    assert lines == {OBJECT_ID_A: SUMMARY_LINE_A, OBJECT_ID_B: SUMMARY_LINE_B}


def test_build_summary_lines_skips_a_doc_whose_type_did_not_resolve() -> None:
    """No type, no line - the row falls back to the empty summary"""
    lines = build_summary_lines([_make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID)], {})

    assert not lines


def test_build_summary_lines_skips_a_doc_without_an_integer_public_id() -> None:
    """A doc that cannot be keyed gets no line"""
    lookup = {SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL)}

    assert not build_summary_lines([{CmdbObjectKey.PUBLIC_ID: 'x', CmdbObjectKey.TYPE_ID: SERVER_TYPE_ID}], lookup)


def test_build_summary_lines_composes_with_the_type_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """The line is the one get_summary_lines_lookup answered: with_type=True, the doc and its type"""
    calls: list[tuple[Any, Any, bool]] = []
    monkeypatch.setattr(assignable_objects, 'compose_summary_line',
                        lambda doc, object_type, with_type: calls.append((doc, object_type, with_type)) or 'x')
    server = _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL)
    doc = _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID)

    build_summary_lines([doc], {SERVER_TYPE_ID: server})

    assert calls == [(doc, server, True)]


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
def test_shape_rows_reads_the_types_once_scoped_to_the_docs() -> None:
    """One get_types_lookup per page, over the distinct types present on the docs"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL)}

    _shape_rows(types_manager, [_make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
                                _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID)])

    types_manager.get_types_lookup.assert_called_once()
    assert types_manager.get_types_lookup.call_args.args[0] == [SERVER_TYPE_ID]


def test_shape_rows_feeds_labels_and_summary_lines_from_the_one_lookup() -> None:
    """The same lookup gives the row its type label and its summary line"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        SERVER_TYPE_ID: _make_type_mock(SERVER_TYPE_ID, SERVER_LABEL),
        ROUTER_TYPE_ID: _make_type_mock(ROUTER_TYPE_ID, ROUTER_LABEL),
    }

    rows = _shape_rows(types_manager, [_make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
                                       _make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID)])

    assert [(row[IpamOverviewKey.TYPE_INFO][IpamOverviewKey.LABEL], row[IpamOverviewKey.SUMMARY_LINE])
            for row in rows] == [(SERVER_LABEL, SUMMARY_LINE_A), (ROUTER_LABEL, SUMMARY_LINE_C)]


def test_shape_rows_reads_no_types_when_no_objects() -> None:
    """No docs handed in → no type round-trip"""
    types_manager = MagicMock()

    assert _shape_rows(types_manager, []) == []
    types_manager.get_types_lookup.assert_not_called()


def test_shape_rows_preserves_input_order() -> None:
    """Rows come back in the same order as the input docs"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}

    rows = _shape_rows(types_manager, [
        _make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID),
        _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
        _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID),
    ])

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


FOUR_DOCS: list[dict[str, Any]] = [
    _make_object_doc(OBJECT_ID_A, SERVER_TYPE_ID),
    _make_object_doc(OBJECT_ID_B, SERVER_TYPE_ID),
    _make_object_doc(OBJECT_ID_C, ROUTER_TYPE_ID),
    _make_object_doc(OBJECT_ID_D, ROUTER_TYPE_ID),
]


def _find_like_mongo(_criteria: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    """find_objects as MongoDB answers it: skip, then limit (0 = none), over the four docs in natural order"""
    skip: int = kwargs.get('skip', 0)
    limit: int = kwargs.get('limit', 0)

    return FOUR_DOCS[skip:skip + limit] if limit else FOUR_DOCS[skip:]


@pytest.fixture(name='objects_manager_four_objects')
def fixture_objects_manager_four_objects() -> MagicMock:
    """ObjectsManager mock over 4 IPAM-eligible objects: a count and a skip/limit-honouring find."""
    objects_manager = MagicMock()
    objects_manager.count_objects.return_value = len(FOUR_DOCS)
    objects_manager.find_objects.side_effect = _find_like_mongo

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
    objects_manager.count_objects.assert_not_called()


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


def test_build_assignable_objects_page_without_search_reads_only_the_page(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """No active search → MongoDB cuts the page: one count for the total, one find with skip / limit"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=2,
        page_size=2,
        search='',
    )

    assert payload[IpamOverviewKey.TOTAL] == 4
    kwargs: dict[str, Any] = objects_manager_four_objects.find_objects.call_args.kwargs
    assert (kwargs['skip'], kwargs['limit']) == (2, 2)
    objects_manager_four_objects.count_objects.assert_called_once()


def test_build_assignable_objects_page_with_search_reads_every_candidate_and_totals_filtered(
    types_manager_two_capable_types: MagicMock,
    objects_manager_four_objects: MagicMock,
) -> None:
    """An active search → one unpaged (projected) find, no count; total is the post-filter count"""
    payload: dict[str, Any] = build_assignable_objects_page(
        objects_manager_four_objects,
        types_manager_two_capable_types,
        page=1,
        page_size=10,
        search='Router',
    )

    assert payload[IpamOverviewKey.TOTAL] == 2
    kwargs: dict[str, Any] = objects_manager_four_objects.find_objects.call_args.kwargs
    assert 'skip' not in kwargs and 'limit' not in kwargs
    objects_manager_four_objects.count_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                         read_unsearched_page / read_searched_page                                    #
# -------------------------------------------------------------------------------------------------------------------- #
CRITERIA: dict[str, Any] = {CmdbObjectKey.TYPE_ID: {'$in': [SERVER_TYPE_ID, ROUTER_TYPE_ID]}}
REQUEST_USER: MagicMock = MagicMock(name='request_user')


@pytest.mark.parametrize('reader', ['unsearched', 'searched'])
def test_both_paths_read_projected_and_acl_scoped(
    reader: str, types_manager_two_capable_types: MagicMock, objects_manager_four_objects: MagicMock,
) -> None:
    """Only public_id, type_id and fields are read, through the caller's READ ACL"""
    if reader == 'unsearched':
        read_unsearched_page(objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 1, 10,
                             REQUEST_USER)
    else:
        read_searched_page(objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 'router', 1, 10,
                           REQUEST_USER)

    kwargs: dict[str, Any] = objects_manager_four_objects.find_objects.call_args.kwargs
    assert objects_manager_four_objects.find_objects.call_args.args[0] == CRITERIA
    assert kwargs['projection'] == ASSIGNABLE_OBJECT_PROJECTION
    assert (kwargs['user'], kwargs['permission']) == (REQUEST_USER, AccessControlPermission.READ)
    assert kwargs['as_dict'] is True


def test_the_projection_is_what_a_row_reads() -> None:
    """The identity, the type and the summary line's fields - not the interface rows"""
    assert set(ASSIGNABLE_OBJECT_PROJECTION) == {'public_id', 'type_id', 'fields'}


def test_the_unsearched_count_is_acl_scoped_like_the_page(
    types_manager_two_capable_types: MagicMock, objects_manager_four_objects: MagicMock,
) -> None:
    """The total counts what the pages show"""
    read_unsearched_page(objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 1, 10, REQUEST_USER)

    objects_manager_four_objects.count_objects.assert_called_once_with(
        CRITERIA, user=REQUEST_USER, permission=AccessControlPermission.READ,
    )


def test_the_unsearched_page_is_clamped_before_it_is_cut(
    types_manager_two_capable_types: MagicMock, objects_manager_four_objects: MagicMock,
) -> None:
    """Page 99 of 2 rows a page is cut as page 2: skip 2, limit 2 - never a skip past the end"""
    total, page, size, rows = read_unsearched_page(
        objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 99, 2, REQUEST_USER,
    )

    kwargs: dict[str, Any] = objects_manager_four_objects.find_objects.call_args.kwargs
    assert (total, page, size) == (4, 2, 2)
    assert (kwargs['skip'], kwargs['limit']) == (2, 2)
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in rows] == [OBJECT_ID_C, OBJECT_ID_D]


def test_an_empty_unsearched_set_is_one_empty_page(types_manager_two_capable_types: MagicMock) -> None:
    """Count 0: the first page, nothing on it"""
    objects_manager = MagicMock()
    objects_manager.count_objects.return_value = 0
    objects_manager.find_objects.return_value = []

    total, page, _size, rows = read_unsearched_page(
        objects_manager, types_manager_two_capable_types, CRITERIA, 3, 10, REQUEST_USER,
    )

    assert (total, page, rows) == (0, 1, [])


def test_the_searched_page_is_cut_after_the_filter(
    types_manager_two_capable_types: MagicMock, objects_manager_four_objects: MagicMock,
) -> None:
    """Page 2 of the matching rows, one a page"""
    total, page, _size, rows = read_searched_page(
        objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 'router', 2, 1, REQUEST_USER,
    )

    assert (total, page) == (2, 2)
    assert [row[CmdbObjectKey.PUBLIC_ID] for row in rows] == [OBJECT_ID_D]


@pytest.mark.parametrize('reader', ['unsearched', 'searched'])
def test_both_paths_read_in_public_id_order(
    reader: str, types_manager_two_capable_types: MagicMock, objects_manager_four_objects: MagicMock,
) -> None:
    """The page order is defined - public_id ascending - on both paths"""
    if reader == 'unsearched':
        read_unsearched_page(objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 1, 10,
                             REQUEST_USER)
    else:
        read_searched_page(objects_manager_four_objects, types_manager_two_capable_types, CRITERIA, 'router', 1, 10,
                           REQUEST_USER)

    assert objects_manager_four_objects.find_objects.call_args.kwargs['sort'] == ASSIGNABLE_OBJECT_ORDER


def test_the_order_is_public_id_ascending() -> None:
    """Unique, so a total order: the same page is the same rows on every request"""
    assert ASSIGNABLE_OBJECT_ORDER == [('public_id', 1)]
