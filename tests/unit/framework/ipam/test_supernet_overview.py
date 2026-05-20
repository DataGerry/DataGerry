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
Unit tests for cmdb.framework.ipam.supernet_overview

Covers pure helpers (CIDR math, row shaping, parent linking, child indexing) and the two DB
orchestrators (build_supernet_overview, build_supernet_subnet_children). _network_sort_key is
intentionally not tested directly: it is a one-line stdlib delegation per the trivial-method
rule. Mongo query filter shapes are pinned via assert_called_once_with so a future refactor
that loosens them fails loudly. Flask aborts are exercised via pytest.raises(HTTPException)
without needing a request context. For the two orchestrators the internal helpers are patched
at the module path so each test verifies orchestration in isolation; each helper has its own
dedicated tests in this file
"""
from ipaddress import IPv4Network
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
    InterfaceField,
    VlanField,
    IpamSection,
    IpamPagination,
    IpamSearch,
    IpamOverviewKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.supernet_overview import (
    _annotate_has_children,
    _attach_vlans_to_rows,
    _build_linked_subnet_rows,
    _count_used_ips_per_subnet,
    _filter_rows_by_network_substring,
    _index_children_by_parent,
    _ip_range,
    _load_subnets_for_supernet,
    _load_supernet_object,
    _load_vlans_by_subnet,
    _paginate_rows,
    _parse_supernet_cidr,
    _percent,
    _row_subnet_ref,
    _select_listed_rows,
    _summarize_supernet,
    build_supernet_overview,
    build_supernet_subnet_children,
    compute_subnet_row,
    compute_supernet_summary,
    sort_and_link_subnets,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
SUBNET_OBJECT_ID_NESTED_IN_A: int = 211
VLAN_OBJECT_ID_X: int = 501
VLAN_OBJECT_ID_Y: int = 502
VLAN_OBJECT_ID_Z: int = 503

SUPERNET_RANGE: str = '10.0.0.0/16'
SUBNET_RANGE_A: str = '10.0.0.0/24'
SUBNET_RANGE_B: str = '10.0.1.0/24'
NESTED_IN_A_RANGE: str = '10.0.0.0/25'

VLAN_NAME_X: str = 'VLAN-X'
VLAN_NAME_Y: str = 'VLAN-Y'
VLAN_NAME_Z: str = 'VLAN-Z'

PATH: str = 'cmdb.framework.ipam.supernet_overview'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_cmdb_object(public_id: int, type_id: int, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with an optional fields list."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: fields or [],
    }


def _make_subnet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field entry."""
    return _make_cmdb_object(
        public_id=public_id,
        type_id=SUBNET_TYPE_ID,
        fields=[{
            CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    )


def _make_supernet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a SUPERNET CmdbObject doc with a network-range field entry."""
    return _make_cmdb_object(
        public_id=public_id,
        type_id=SUPERNET_TYPE_ID,
        fields=[{
            CmdbObjectFieldKey.NAME: SupernetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    )


def _make_vlan_doc(public_id: int, subnet_ref: Any, name: Any) -> dict[str, Any]:
    """Builds a VLAN CmdbObject doc with subnet-ref and name field entries."""
    return _make_cmdb_object(
        public_id=public_id,
        type_id=VLAN_TYPE_ID,
        fields=[
            {CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF, CmdbObjectFieldKey.VALUE: subnet_ref},
            {CmdbObjectFieldKey.NAME: VlanField.NAME, CmdbObjectFieldKey.VALUE: name},
        ],
    )


def _make_interface_carrier(public_id: int, subnet_refs: list[int]) -> dict[str, Any]:
    """Builds a CmdbObject doc with one dg-ipam-interface MDS section referencing the given subnets."""
    rows = [
        {
            CmdbObjectMdsRowKey.DATA: [
                {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: sid},
            ],
        }
        for sid in subnet_refs
    ]

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: 99,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: rows,
            },
        ],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    _ip_range                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ip_range_returns_first_and_last_address_strings() -> None:
    """The dict pins the network and broadcast addresses under FIRST / LAST"""
    result = _ip_range(IPv4Network('10.0.0.0/24'))

    assert result == {
        IpamOverviewKey.FIRST: '10.0.0.0',
        IpamOverviewKey.LAST: '10.0.0.255',
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    _percent                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_percent_computes_value_rounded_to_two_decimals() -> None:
    """Standard case: numerator over positive denominator, rounded to 2 decimals"""
    assert _percent(1, 3) == 33.33


def test_percent_returns_full_hundred_when_numerator_equals_denominator() -> None:
    """All-used case yields 100.0"""
    assert _percent(50, 50) == 100.0


@pytest.mark.parametrize('denominator', [0, -1, -100])
def test_percent_returns_zero_for_non_positive_denominator(denominator: int) -> None:
    """Zero or negative denominator short-circuits with 0.0 (no DivisionByZero)"""
    assert _percent(5, denominator) == 0.0


# -------------------------------------------------------------------------------------------------------------------- #
#                                               compute_subnet_row                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_subnet_row_emits_expected_keys_for_valid_subnet() -> None:
    """A parsable subnet yields the full row with the standard key set"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)

    row = compute_subnet_row(subnet, used_count=10)

    assert set(row.keys()) == {
        CmdbObjectKey.PUBLIC_ID,
        IpamOverviewKey.CIDR,
        IpamOverviewKey.USED_IPS,
        IpamOverviewKey.FREE_IPS,
        IpamOverviewKey.USAGE_PERCENT,
    }


def test_compute_subnet_row_computes_used_and_free_against_total_address_count() -> None:
    """free_ips = total - used; usage_percent computed against total (network+broadcast included)"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)

    row = compute_subnet_row(subnet, used_count=10)

    assert row[IpamOverviewKey.CIDR] == SUBNET_RANGE_A
    assert row[IpamOverviewKey.USED_IPS] == 10
    assert row[IpamOverviewKey.FREE_IPS] == 256 - 10
    assert row[IpamOverviewKey.USAGE_PERCENT] == round(10 / 256 * 100, 2)


def test_compute_subnet_row_clamps_free_to_zero_when_used_exceeds_total() -> None:
    """A used_count larger than the subnet's total saturates free at 0"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)

    row = compute_subnet_row(subnet, used_count=10000)

    assert row[IpamOverviewKey.FREE_IPS] == 0


def test_compute_subnet_row_returns_degenerate_row_for_unparsable_cidr() -> None:
    """An unparsable CIDR yields zeroed counts and preserves the raw string under CIDR"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID_A, 'not-a-cidr')

    row = compute_subnet_row(subnet, used_count=5)

    assert row[IpamOverviewKey.CIDR] == 'not-a-cidr'
    assert row[IpamOverviewKey.USED_IPS] == 0
    assert row[IpamOverviewKey.FREE_IPS] == 0
    assert row[IpamOverviewKey.USAGE_PERCENT] == 0.0


def test_compute_subnet_row_returns_degenerate_row_with_null_cidr_for_non_string_value() -> None:
    """A non-string range value (e.g. None / int) yields CIDR=None to drop the broken value"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID_A, None)

    row = compute_subnet_row(subnet, used_count=5)

    assert row[IpamOverviewKey.CIDR] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          compute_supernet_summary                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_supernet_summary_returns_degenerate_block_when_network_is_none() -> None:
    """Missing/unparsable supernet CIDR yields zeroed totals; subnet_count still propagated"""
    summary = compute_supernet_summary(supernet_network=None, total_used=7, subnet_count=3)

    assert summary[IpamOverviewKey.CIDR] is None
    assert summary[IpamOverviewKey.IP_RANGE] is None
    assert summary[IpamOverviewKey.TOTAL_IPS] == 0
    assert summary[IpamOverviewKey.FREE_IPS] == 0
    assert summary[IpamOverviewKey.USED_PERCENT] == 0.0
    assert summary[IpamOverviewKey.SUBNET_COUNT] == 3
    assert summary[IpamOverviewKey.USED_IPS] == 7


def test_compute_supernet_summary_computes_totals_for_parsable_network() -> None:
    """Standard case: all percentages and counts computed against total address count"""
    summary = compute_supernet_summary(
        supernet_network=IPv4Network('10.0.0.0/24'),
        total_used=64,
        subnet_count=4,
    )

    assert summary[IpamOverviewKey.CIDR] == '10.0.0.0/24'
    assert summary[IpamOverviewKey.TOTAL_IPS] == 256
    assert summary[IpamOverviewKey.USED_IPS] == 64
    assert summary[IpamOverviewKey.FREE_IPS] == 192
    assert summary[IpamOverviewKey.USED_PERCENT] == 25.0
    assert summary[IpamOverviewKey.FREE_PERCENT] == 75.0
    assert summary[IpamOverviewKey.SUBNET_COUNT] == 4


def test_compute_supernet_summary_aliases_utilization_percent_to_used_percent() -> None:
    """The utilization_percent metric is intentionally identical to used_percent"""
    summary = compute_supernet_summary(
        supernet_network=IPv4Network('10.0.0.0/24'),
        total_used=64,
        subnet_count=4,
    )

    assert summary[IpamOverviewKey.UTILIZATION_PERCENT] == summary[IpamOverviewKey.USED_PERCENT]


def test_compute_supernet_summary_clamps_free_when_total_used_exceeds_capacity() -> None:
    """An over-counted total_used still produces a non-negative free_ips"""
    summary = compute_supernet_summary(
        supernet_network=IPv4Network('10.0.0.0/24'),
        total_used=10000,
        subnet_count=4,
    )

    assert summary[IpamOverviewKey.FREE_IPS] == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                             sort_and_link_subnets                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_row(public_id: int, cidr: str | None) -> dict[str, Any]:
    """Builds an overview row in the same shape compute_subnet_row would produce."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        IpamOverviewKey.CIDR: cidr,
        IpamOverviewKey.USED_IPS: 0,
        IpamOverviewKey.FREE_IPS: 0,
        IpamOverviewKey.USAGE_PERCENT: 0.0,
    }


def test_sort_and_link_subnets_returns_empty_for_empty_input() -> None:
    """An empty input list yields an empty result"""
    assert sort_and_link_subnets([]) == []


def test_sort_and_link_subnets_returns_rows_in_ascending_cidr_order() -> None:
    """Rows are emitted in ascending network-address order"""
    rows = [
        _make_row(SUBNET_OBJECT_ID_B, '10.0.1.0/24'),
        _make_row(SUBNET_OBJECT_ID_A, '10.0.0.0/24'),
    ]

    result = sort_and_link_subnets(rows)

    public_ids = [r[CmdbObjectKey.PUBLIC_ID] for r in result]
    assert public_ids == [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]


def test_sort_and_link_subnets_marks_top_level_rows_with_parent_id_none() -> None:
    """Rows whose CIDR is not strictly contained by any sibling get parent_id=None"""
    rows = [
        _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B),
    ]

    result = sort_and_link_subnets(rows)

    assert all(r[IpamOverviewKey.PARENT_ID] is None for r in result)


def test_sort_and_link_subnets_links_nested_subnet_to_enclosing_sibling() -> None:
    """A subnet strictly contained by a sibling gets that sibling's id as parent_id"""
    rows = [
        _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
    ]

    result = sort_and_link_subnets(rows)

    by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in result}
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.PARENT_ID] is None
    assert by_id[SUBNET_OBJECT_ID_NESTED_IN_A][IpamOverviewKey.PARENT_ID] == SUBNET_OBJECT_ID_A


def test_sort_and_link_subnets_links_to_most_specific_enclosing_sibling() -> None:
    """Three-level nesting: each row links to its closest CIDR-enclosing sibling"""
    deeper_id: int = 221
    rows = [
        _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
        _make_row(deeper_id, '10.0.0.0/26'),
    ]

    result = sort_and_link_subnets(rows)

    by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in result}
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.PARENT_ID] is None
    assert by_id[SUBNET_OBJECT_ID_NESTED_IN_A][IpamOverviewKey.PARENT_ID] == SUBNET_OBJECT_ID_A
    assert by_id[deeper_id][IpamOverviewKey.PARENT_ID] == SUBNET_OBJECT_ID_NESTED_IN_A


def test_sort_and_link_subnets_pops_stack_when_walking_away_from_parent() -> None:
    """A new branch (not enclosed by the prior subnet) clears the stack back to its own parent"""
    rows = [
        _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
        _make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B),
    ]

    result = sort_and_link_subnets(rows)

    by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in result}
    assert by_id[SUBNET_OBJECT_ID_B][IpamOverviewKey.PARENT_ID] is None


def test_sort_and_link_subnets_appends_unsortable_rows_after_sorted_block() -> None:
    """Rows with unparsable CIDRs trail the sorted block, with parent_id=None"""
    rows = [
        _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_row(999, 'not-a-cidr'),
    ]

    result = sort_and_link_subnets(rows)

    assert result[0][CmdbObjectKey.PUBLIC_ID] == SUBNET_OBJECT_ID_A
    assert result[-1][CmdbObjectKey.PUBLIC_ID] == 999
    assert result[-1][IpamOverviewKey.PARENT_ID] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _index_children_by_parent                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_index_children_by_parent_returns_empty_dict_for_empty_input() -> None:
    """No rows → no index entries"""
    assert _index_children_by_parent([]) == {}


def test_index_children_by_parent_groups_rows_by_parent_id() -> None:
    """Each parent_id becomes a key whose value is the list of rows referencing it"""
    rows = [
        {**_make_row(1, '10.0.0.0/24'), IpamOverviewKey.PARENT_ID: None},
        {**_make_row(2, '10.0.0.0/25'), IpamOverviewKey.PARENT_ID: 1},
        {**_make_row(3, '10.0.0.128/25'), IpamOverviewKey.PARENT_ID: 1},
        {**_make_row(4, '10.0.1.0/24'), IpamOverviewKey.PARENT_ID: None},
    ]

    index = _index_children_by_parent(rows)

    assert {r[CmdbObjectKey.PUBLIC_ID] for r in index[None]} == {1, 4}
    assert {r[CmdbObjectKey.PUBLIC_ID] for r in index[1]} == {2, 3}


def test_index_children_by_parent_preserves_per_bucket_order() -> None:
    """Within each bucket, rows keep their input order (children stay in CIDR order)"""
    rows = [
        {**_make_row(2, '10.0.0.0/25'), IpamOverviewKey.PARENT_ID: 1},
        {**_make_row(3, '10.0.0.128/25'), IpamOverviewKey.PARENT_ID: 1},
    ]

    index = _index_children_by_parent(rows)

    assert [r[CmdbObjectKey.PUBLIC_ID] for r in index[1]] == [2, 3]


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _annotate_has_children                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_annotate_has_children_sets_true_for_rows_appearing_as_parents() -> None:
    """A row whose public_id is a key in the children_index gets has_children=True"""
    parent_row = _make_row(1, '10.0.0.0/24')
    child_row = _make_row(2, '10.0.0.0/25')
    rows = [parent_row, child_row]
    index = {1: [child_row], None: [parent_row]}

    _annotate_has_children(rows, index)

    assert parent_row[IpamOverviewKey.HAS_CHILDREN] is True


def test_annotate_has_children_sets_false_for_leaf_rows() -> None:
    """A row whose public_id has no children gets has_children=False"""
    leaf_row = _make_row(2, '10.0.0.0/25')
    rows = [leaf_row]
    index: dict[Any, list[dict[str, Any]]] = {None: [leaf_row]}

    _annotate_has_children(rows, index)

    assert leaf_row[IpamOverviewKey.HAS_CHILDREN] is False


def test_annotate_has_children_sets_false_for_row_with_missing_public_id() -> None:
    """A row without a public_id can never be a parent and gets has_children=False"""
    row_without_id: dict[str, Any] = {IpamOverviewKey.CIDR: 'not-a-cidr'}
    rows = [row_without_id]
    index: dict[Any, list[dict[str, Any]]] = {}

    _annotate_has_children(rows, index)

    assert row_without_id[IpamOverviewKey.HAS_CHILDREN] is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                       _filter_rows_by_network_substring                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_filter_rows_by_network_substring_returns_empty_for_empty_input() -> None:
    """No rows in → empty list out, no errors"""
    assert _filter_rows_by_network_substring([], '10.0') == []


def test_filter_rows_by_network_substring_returns_empty_when_no_row_matches() -> None:
    """Zero matches yields an empty list, not None"""
    rows = [_make_row(1, '10.0.0.0/24'), _make_row(2, '10.1.0.0/24')]

    assert _filter_rows_by_network_substring(rows, '172.16') == []


def test_filter_rows_by_network_substring_returns_matches_in_input_order() -> None:
    """Match order tracks the input row order; matches across nesting depths surface together"""
    row_a = _make_row(1, '10.0.0.0/24')
    row_nested = _make_row(2, '10.0.0.0/25')
    row_b = _make_row(3, '192.168.1.0/24')
    rows = [row_a, row_nested, row_b]

    result = _filter_rows_by_network_substring(rows, '10.0')

    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result] == [1, 2]


def test_filter_rows_by_network_substring_is_case_insensitive() -> None:
    """Uppercase needle matches lowercase cidr and vice versa"""
    rows = [{CmdbObjectKey.PUBLIC_ID: 9, IpamOverviewKey.CIDR: '10.AbC.0.0/24'}]

    assert _filter_rows_by_network_substring(rows, 'abc') == rows
    assert _filter_rows_by_network_substring(rows, 'ABC') == rows


def test_filter_rows_by_network_substring_skips_rows_with_non_string_cidr() -> None:
    """A row whose cidr is None or non-string never matches, even for the empty needle"""
    rows = [
        {CmdbObjectKey.PUBLIC_ID: 1, IpamOverviewKey.CIDR: None},
        {CmdbObjectKey.PUBLIC_ID: 2, IpamOverviewKey.CIDR: 12345},
        {CmdbObjectKey.PUBLIC_ID: 3, IpamOverviewKey.CIDR: '10.0.0.0/24'},
    ]

    result = _filter_rows_by_network_substring(rows, '10')

    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result] == [3]


def test_filter_rows_by_network_substring_matches_unparsable_string_cidr() -> None:
    """A degenerate row whose raw cidr is still a string is searchable by that string"""
    rows = [{CmdbObjectKey.PUBLIC_ID: 1, IpamOverviewKey.CIDR: 'not-a-cidr'}]

    assert _filter_rows_by_network_substring(rows, 'cidr') == rows


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _select_listed_rows                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_top_level_row(public_id: int, cidr: str) -> dict[str, Any]:
    """Returns an overview row marked as top-level (parent_id=None) for selection tests."""
    return {**_make_row(public_id, cidr), IpamOverviewKey.PARENT_ID: None}


def _make_nested_row(public_id: int, cidr: str, parent_id: int) -> dict[str, Any]:
    """Returns an overview row marked as nested under the given parent for selection tests."""
    return {**_make_row(public_id, cidr), IpamOverviewKey.PARENT_ID: parent_id}


def test_select_listed_rows_returns_top_level_rows_for_empty_search() -> None:
    """No search → only rows whose parent_id is None pass through, in input order"""
    top_a = _make_top_level_row(1, '10.0.0.0/24')
    nested = _make_nested_row(2, '10.0.0.0/25', parent_id=1)
    top_b = _make_top_level_row(3, '192.168.1.0/24')

    assert _select_listed_rows([top_a, nested, top_b], '') == [top_a, top_b]


def test_select_listed_rows_returns_top_level_rows_for_whitespace_only_search() -> None:
    """A search of only whitespace strips to empty and falls back to top-level"""
    top_a = _make_top_level_row(1, '10.0.0.0/24')
    nested = _make_nested_row(2, '10.0.0.0/25', parent_id=1)

    assert _select_listed_rows([top_a, nested], '   ') == [top_a]


def test_select_listed_rows_falls_back_to_top_level_when_search_below_min_length() -> None:
    """A 1-char search (below IpamSearch.MIN_QUERY_LENGTH=2) is treated as no filter"""
    assert IpamSearch.MIN_QUERY_LENGTH == 2  # pinning the policy this test depends on
    top = _make_top_level_row(1, '10.0.0.0/24')
    nested = _make_nested_row(2, '10.0.0.0/25', parent_id=1)

    assert _select_listed_rows([top, nested], '1') == [top]


def test_select_listed_rows_filters_across_nesting_depths_when_search_is_active() -> None:
    """At-or-above MIN_QUERY_LENGTH the result is the substring match across all rows"""
    top_a = _make_top_level_row(1, '10.0.0.0/24')
    nested = _make_nested_row(2, '10.0.0.0/25', parent_id=1)
    top_b = _make_top_level_row(3, '192.168.1.0/24')

    result = _select_listed_rows([top_a, nested, top_b], '10.0')

    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result] == [1, 2]


def test_select_listed_rows_strips_search_before_min_length_check() -> None:
    """Surrounding whitespace must not push a sub-min-length query past the threshold"""
    top = _make_top_level_row(1, '10.0.0.0/24')
    nested = _make_nested_row(2, '10.0.0.0/25', parent_id=1)

    assert _select_listed_rows([top, nested], '  1  ') == [top]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _paginate_rows                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_paginate_rows_returns_full_input_when_page_size_exceeds_total() -> None:
    """page_size larger than the row count yields the whole list on page 1"""
    rows = [_make_row(i, f'10.0.{i}.0/24') for i in (1, 2, 3)]

    safe_page, safe_size, page_rows = _paginate_rows(rows, page=1, page_size=10)

    assert (safe_page, safe_size, page_rows) == (1, 10, rows)


def test_paginate_rows_slices_one_page_when_page_size_smaller_than_total() -> None:
    """page_size of 1 over 3 rows yields one row on page 2 (the middle entry)"""
    rows = [_make_row(i, f'10.0.{i}.0/24') for i in (1, 2, 3)]

    safe_page, safe_size, page_rows = _paginate_rows(rows, page=2, page_size=1)

    assert safe_page == 2
    assert safe_size == 1
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in page_rows] == [2]


def test_paginate_rows_clamps_page_past_end_to_last_valid_page() -> None:
    """A page number beyond the last yields the last valid page, not an empty slice"""
    rows = [_make_row(i, f'10.0.{i}.0/24') for i in (1, 2, 3)]

    safe_page, safe_size, page_rows = _paginate_rows(rows, page=99, page_size=2)

    assert safe_size == 2
    assert safe_page == 2
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in page_rows] == [3]


def test_paginate_rows_returns_empty_page_for_empty_input() -> None:
    """An empty row list yields an empty page; page / page_size still come back clamped"""
    safe_page, safe_size, page_rows = _paginate_rows([], page=1, page_size=10)

    assert page_rows == []
    assert safe_size == 10
    assert safe_page >= IpamPagination.MIN_PAGE


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _load_supernet_object                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_supernet_object_aborts_400_when_supernet_type_not_defined() -> None:
    """No SUPERNET CmdbType → HTTP 400; no object query is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        _load_supernet_object(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 400
    objects_manager.find_objects.assert_not_called()


def test_load_supernet_object_aborts_404_when_object_not_found() -> None:
    """find_objects returns empty → HTTP 404"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        _load_supernet_object(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_load_supernet_object_aborts_400_when_object_is_not_a_supernet() -> None:
    """Found object exists but has a different type_id → HTTP 400"""
    wrong_type_doc = _make_cmdb_object(SUPERNET_OBJECT_ID, type_id=SUPERNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        _load_supernet_object(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_load_supernet_object_returns_candidate_on_happy_path() -> None:
    """A correct SUPERNET object id returns the loaded doc"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [supernet_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    result = _load_supernet_object(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result is supernet_doc
    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUPERNET_OBJECT_ID}, as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _parse_supernet_cidr                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_supernet_cidr_returns_ipv4network_for_valid_cidr() -> None:
    """A supernet doc with a valid CIDR string parses to the corresponding IPv4Network"""
    doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)

    result = _parse_supernet_cidr(doc)

    assert isinstance(result, IPv4Network)
    assert str(result) == SUPERNET_RANGE


def test_parse_supernet_cidr_returns_none_when_field_missing() -> None:
    """A supernet doc without the network-range field yields None, not an error"""
    doc = _make_cmdb_object(SUPERNET_OBJECT_ID, SUPERNET_TYPE_ID, fields=[])

    assert _parse_supernet_cidr(doc) is None


def test_parse_supernet_cidr_returns_none_for_non_string_value() -> None:
    """A network-range field carrying a non-string value (e.g. None, dict) yields None"""
    doc = _make_supernet_doc(SUPERNET_OBJECT_ID, network_range=None)

    assert _parse_supernet_cidr(doc) is None


def test_parse_supernet_cidr_returns_none_for_unparsable_string() -> None:
    """A garbled CIDR string yields None rather than raising"""
    doc = _make_supernet_doc(SUPERNET_OBJECT_ID, network_range='not-a-cidr')

    assert _parse_supernet_cidr(doc) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _load_subnets_for_supernet                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_subnets_for_supernet_returns_empty_when_subnet_type_not_defined() -> None:
    """No SUBNET CmdbType → empty list, no DB query"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = _load_subnets_for_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result == []
    objects_manager.find_objects.assert_not_called()


def test_load_subnets_for_supernet_returns_manager_result_when_type_defined() -> None:
    """SUBNET type defined → result of objects_manager.find_objects is returned verbatim"""
    subnet_docs = [_make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = subnet_docs
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = _load_subnets_for_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert result is subnet_docs


def test_load_subnets_for_supernet_queries_with_parent_supernet_field_filter() -> None:
    """Mongo filter pins TYPE_ID plus FIELDS $elemMatch on PARENT_SUPERNET/supernet id"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    _load_subnets_for_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                    CmdbObjectFieldKey.VALUE: SUPERNET_OBJECT_ID,
                },
            },
        },
        as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                        _count_used_ips_per_subnet                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_count_used_ips_per_subnet_returns_empty_counts_for_empty_subnet_ids() -> None:
    """An empty subnet_ids list yields an empty counts dict and no DB query"""
    objects_manager = MagicMock()

    counts = _count_used_ips_per_subnet(objects_manager, [])

    assert counts == {}
    objects_manager.find_objects.assert_not_called()


def test_count_used_ips_per_subnet_initializes_all_ids_to_zero() -> None:
    """Every requested subnet id appears in the counts dict, even when zero interface rows reference it"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    counts = _count_used_ips_per_subnet(objects_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B])

    assert counts == {SUBNET_OBJECT_ID_A: 0, SUBNET_OBJECT_ID_B: 0}


def test_count_used_ips_per_subnet_counts_one_row_per_matching_interface_reference() -> None:
    """Each matching dg-ipam-interface row increments the count for its referenced subnet"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_interface_carrier(public_id=701, subnet_refs=[SUBNET_OBJECT_ID_A]),
        _make_interface_carrier(public_id=702, subnet_refs=[SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]),
    ]

    counts = _count_used_ips_per_subnet(objects_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B])

    assert counts[SUBNET_OBJECT_ID_A] == 2
    assert counts[SUBNET_OBJECT_ID_B] == 1


def test_count_used_ips_per_subnet_skips_non_interface_mds_sections() -> None:
    """Sections whose section_id is not the interface template are ignored"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [{
        CmdbObjectKey.PUBLIC_ID: 701,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
                CmdbObjectMdsKey.VALUES: [
                    {
                        CmdbObjectMdsRowKey.DATA: [
                            {
                                CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID_A,
                            },
                        ],
                    },
                ],
            },
        ],
    }]

    counts = _count_used_ips_per_subnet(objects_manager, [SUBNET_OBJECT_ID_A])

    assert counts[SUBNET_OBJECT_ID_A] == 0


def test_count_used_ips_per_subnet_ignores_subnet_refs_not_in_target_list() -> None:
    """Rows referencing subnets outside the requested id set do not increment any count"""
    other_subnet_id: int = 999
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        _make_interface_carrier(public_id=701, subnet_refs=[other_subnet_id]),
    ]

    counts = _count_used_ips_per_subnet(objects_manager, [SUBNET_OBJECT_ID_A])

    assert counts[SUBNET_OBJECT_ID_A] == 0


def test_count_used_ips_per_subnet_uses_in_filter_to_scope_the_db_query() -> None:
    """Mongo filter pins the nested $elemMatch chain with $in over the subnet id list"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    _count_used_ips_per_subnet(objects_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B])

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {
                    CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                    CmdbObjectMdsKey.VALUES: {
                        '$elemMatch': {
                            CmdbObjectMdsRowKey.DATA: {
                                '$elemMatch': {
                                    CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                    CmdbObjectFieldKey.VALUE: {
                                        '$in': [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _row_subnet_ref                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_row_subnet_ref_returns_subnet_value_when_present() -> None:
    """A row containing the subnet field returns its value"""
    row = {
        CmdbObjectMdsRowKey.DATA: [
            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID_A},
        ],
    }

    assert _row_subnet_ref(row) == SUBNET_OBJECT_ID_A


def test_row_subnet_ref_returns_none_when_subnet_field_absent() -> None:
    """A row with no subnet field entry returns None"""
    row = {
        CmdbObjectMdsRowKey.DATA: [
            {CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: '10.0.0.5'},
        ],
    }

    assert _row_subnet_ref(row) is None


def test_row_subnet_ref_returns_none_when_data_key_missing() -> None:
    """A row missing the 'data' key is treated as empty, returning None"""
    assert _row_subnet_ref({}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _load_vlans_by_subnet                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_vlans_by_subnet_returns_empty_dict_for_empty_subnet_ids() -> None:
    """No subnet ids in → empty dict, no DB query, no type lookup"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    result = _load_vlans_by_subnet(objects_manager, types_manager, [])

    assert result == {}
    objects_manager.find_objects.assert_not_called()
    types_manager.get_one_by.assert_not_called()


def test_load_vlans_by_subnet_returns_empty_dict_when_vlan_type_not_defined() -> None:
    """No VLAN CmdbType → empty dict, no DB query against objects"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = _load_vlans_by_subnet(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    assert result == {}
    objects_manager.find_objects.assert_not_called()


def test_load_vlans_by_subnet_buckets_vlans_under_their_referenced_subnet() -> None:
    """Each VLAN appears under the bucket for the subnet its dg-subnet-ref points at"""
    vlan_x = _make_vlan_doc(VLAN_OBJECT_ID_X, subnet_ref=SUBNET_OBJECT_ID_A, name=VLAN_NAME_X)
    vlan_y = _make_vlan_doc(VLAN_OBJECT_ID_Y, subnet_ref=SUBNET_OBJECT_ID_B, name=VLAN_NAME_Y)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [vlan_x, vlan_y]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = _load_vlans_by_subnet(
        objects_manager, types_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
    )

    assert result == {
        SUBNET_OBJECT_ID_A: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}],
        SUBNET_OBJECT_ID_B: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y}],
    }


def test_load_vlans_by_subnet_sorts_each_bucket_by_ascending_public_id() -> None:
    """Within a bucket, entries are ordered by ascending public_id regardless of DB order"""
    vlan_higher = _make_vlan_doc(VLAN_OBJECT_ID_Z, subnet_ref=SUBNET_OBJECT_ID_A, name=VLAN_NAME_Z)
    vlan_lower = _make_vlan_doc(VLAN_OBJECT_ID_X, subnet_ref=SUBNET_OBJECT_ID_A, name=VLAN_NAME_X)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [vlan_higher, vlan_lower]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = _load_vlans_by_subnet(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    public_ids = [entry[CmdbObjectKey.PUBLIC_ID] for entry in result[SUBNET_OBJECT_ID_A]]
    assert public_ids == [VLAN_OBJECT_ID_X, VLAN_OBJECT_ID_Z]


def test_load_vlans_by_subnet_ignores_vlans_whose_subnet_ref_is_outside_target_set() -> None:
    """A VLAN whose dg-subnet-ref drifts outside subnet_ids is dropped, not bucketed"""
    in_scope = _make_vlan_doc(VLAN_OBJECT_ID_X, subnet_ref=SUBNET_OBJECT_ID_A, name=VLAN_NAME_X)
    out_of_scope = _make_vlan_doc(VLAN_OBJECT_ID_Y, subnet_ref=9_999, name=VLAN_NAME_Y)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [in_scope, out_of_scope]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = _load_vlans_by_subnet(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    assert set(result.keys()) == {SUBNET_OBJECT_ID_A}
    assert [e[CmdbObjectKey.PUBLIC_ID] for e in result[SUBNET_OBJECT_ID_A]] == [VLAN_OBJECT_ID_X]


def test_load_vlans_by_subnet_uses_in_filter_to_scope_the_db_query() -> None:
    """Mongo filter pins TYPE_ID plus FIELDS $elemMatch on SUBNET_REF with $in over subnet ids"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    _load_vlans_by_subnet(
        objects_manager, types_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
    )

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: VlanField.SUBNET_REF,
                    CmdbObjectFieldKey.VALUE: {'$in': [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]},
                },
            },
        },
        as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN})


def test_load_vlans_by_subnet_preserves_null_vlan_name() -> None:
    """A VLAN object whose dg-name field is missing/None flows through as 'name': None"""
    vlan = _make_vlan_doc(VLAN_OBJECT_ID_X, subnet_ref=SUBNET_OBJECT_ID_A, name=None)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [vlan]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: VLAN_TYPE_ID}

    result = _load_vlans_by_subnet(objects_manager, types_manager, [SUBNET_OBJECT_ID_A])

    assert result[SUBNET_OBJECT_ID_A] == [{
        CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X,
        IpamOverviewKey.NAME: None,
    }]


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _attach_vlans_to_rows                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_attach_vlans_to_rows_copies_bucket_list_onto_matching_row() -> None:
    """A row whose public_id has a bucket gets the bucket's entries on its 'vlans' field"""
    row = _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)
    vlan_entry = {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}

    _attach_vlans_to_rows([row], {SUBNET_OBJECT_ID_A: [vlan_entry]})

    assert row[IpamOverviewKey.VLANS] == [vlan_entry]


def test_attach_vlans_to_rows_sets_empty_list_when_subnet_has_no_bucket() -> None:
    """A row with no matching bucket still gets a 'vlans' key set to an empty list"""
    row = _make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B)

    _attach_vlans_to_rows([row], {SUBNET_OBJECT_ID_A: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X}]})

    assert row[IpamOverviewKey.VLANS] == []


def test_attach_vlans_to_rows_isolates_each_rows_vlans_from_the_source_bucket() -> None:
    """Mutating one row's 'vlans' must not bleed into the source bucket or sibling rows"""
    row_a = _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)
    bucket: list[dict[str, Any]] = [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}]
    vlans_by_subnet = {SUBNET_OBJECT_ID_A: bucket}

    _attach_vlans_to_rows([row_a], vlans_by_subnet)
    row_a[IpamOverviewKey.VLANS].append({'mutated': True})

    assert bucket == [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}]


def test_attach_vlans_to_rows_returns_none_and_mutates_in_place() -> None:
    """The helper returns None; rows are mutated in place"""
    row = _make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A)

    result = _attach_vlans_to_rows([row], {})

    assert result is None
    assert IpamOverviewKey.VLANS in row


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _build_linked_subnet_rows                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_linked_subnet_rows_returns_empty_when_no_subnets_under_supernet() -> None:
    """No SUBNET docs → empty list (the count helper is also bypassed)"""
    with patch(f'{PATH}._load_subnets_for_supernet', return_value=[]), \
         patch(f'{PATH}._count_used_ips_per_subnet') as count_mock:
        result = _build_linked_subnet_rows(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert result == []
    count_mock.assert_called_once_with(any_value(), [])


def any_value() -> Any:
    """Returns an `ANY`-style matcher for MagicMock assertions on positional args we don't care about."""
    from unittest.mock import ANY
    return ANY


def test_build_linked_subnet_rows_shapes_rows_and_links_parents() -> None:
    """Returned rows have parent_id annotations, used_ips counts, and VLAN lists attached"""
    subnet_objs = [
        _make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_subnet_doc(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
    ]
    used_counts = {SUBNET_OBJECT_ID_A: 5, SUBNET_OBJECT_ID_NESTED_IN_A: 1}
    vlans_by_subnet = {
        SUBNET_OBJECT_ID_A: [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}],
    }

    with patch(f'{PATH}._load_subnets_for_supernet', return_value=subnet_objs), \
         patch(f'{PATH}._count_used_ips_per_subnet', return_value=used_counts), \
         patch(f'{PATH}._load_vlans_by_subnet', return_value=vlans_by_subnet):
        result = _build_linked_subnet_rows(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in result}
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.PARENT_ID] is None
    assert by_id[SUBNET_OBJECT_ID_NESTED_IN_A][IpamOverviewKey.PARENT_ID] == SUBNET_OBJECT_ID_A
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.USED_IPS] == 5
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.VLANS] == [
        {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X},
    ]
    assert by_id[SUBNET_OBJECT_ID_NESTED_IN_A][IpamOverviewKey.VLANS] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _summarize_supernet                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_summarize_supernet_sums_used_ips_and_forwards_to_compute_supernet_summary() -> None:
    """The summarize helper sums used_ips across rows and forwards (network, total, count)"""
    rows = [
        {**_make_row(1, '10.0.0.0/24'), IpamOverviewKey.USED_IPS: 3},
        {**_make_row(2, '10.0.1.0/24'), IpamOverviewKey.USED_IPS: 7},
    ]
    network = IPv4Network('10.0.0.0/16')
    sentinel: dict[str, Any] = {'sentinel': True}

    with patch(f'{PATH}.compute_supernet_summary', return_value=sentinel) as mock_compute:
        result = _summarize_supernet(rows, network)

    assert result is sentinel
    mock_compute.assert_called_once_with(network, 10, 2)


def test_summarize_supernet_passes_zero_total_used_and_zero_count_for_empty_rows() -> None:
    """No rows → sum of 0 and a count of 0 reach compute_supernet_summary"""
    network = IPv4Network('10.0.0.0/16')

    with patch(f'{PATH}.compute_supernet_summary', return_value={}) as mock_compute:
        _summarize_supernet([], network)

    mock_compute.assert_called_once_with(network, 0, 0)


def test_summarize_supernet_forwards_none_network_unchanged() -> None:
    """A None supernet_network flows through to compute_supernet_summary verbatim"""
    rows = [{**_make_row(1, '10.0.0.0/24'), IpamOverviewKey.USED_IPS: 4}]

    with patch(f'{PATH}.compute_supernet_summary', return_value={}) as mock_compute:
        _summarize_supernet(rows, None)

    mock_compute.assert_called_once_with(None, 4, 1)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_supernet_overview                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_supernet_overview_propagates_load_supernet_aborts() -> None:
    """An abort raised by _load_supernet_object propagates out of the orchestrator"""
    from werkzeug.exceptions import NotFound

    with patch(f'{PATH}._load_supernet_object', side_effect=NotFound('not found')), \
         pytest.raises(HTTPException) as exc_info:
        build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_build_supernet_overview_returns_payload_with_supernet_and_subnets_blocks() -> None:
    """Happy path payload carries supernet summary + paginated top-level rows + has_children"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 4}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 1}
    row_b = {**_make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 2}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a, row_nested, row_b]):
        payload = build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert set(payload.keys()) == {IpamOverviewKey.SUPERNET, IpamOverviewKey.SUBNETS}
    assert payload[IpamOverviewKey.SUPERNET][CmdbObjectKey.PUBLIC_ID] == SUPERNET_OBJECT_ID
    top_rows = payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS]
    top_ids = {r[CmdbObjectKey.PUBLIC_ID] for r in top_rows}
    assert top_ids == {SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B}


def test_build_supernet_overview_aggregates_total_used_across_all_subnets() -> None:
    """Summary.used_ips is the sum across nested and top-level subnets (subnet_count too)"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 4}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 1}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a, row_nested]):
        payload = build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert payload[IpamOverviewKey.SUPERNET][IpamOverviewKey.USED_IPS] == 5
    assert payload[IpamOverviewKey.SUPERNET][IpamOverviewKey.SUBNET_COUNT] == 2


def test_build_supernet_overview_annotates_has_children_on_top_level_rows() -> None:
    """A top-level row whose subnet has nested children has has_children=True"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}
    row_b = {**_make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a, row_nested, row_b]):
        payload = build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    top_rows_by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS]}
    assert top_rows_by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.HAS_CHILDREN] is True
    assert top_rows_by_id[SUBNET_OBJECT_ID_B][IpamOverviewKey.HAS_CHILDREN] is False


def test_build_supernet_overview_paginates_top_level_rows() -> None:
    """A page_size smaller than the top-level count yields a single-row page; total reflects all top-level"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}
    row_b = {**_make_row(SUBNET_OBJECT_ID_B, SUBNET_RANGE_B), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a, row_b]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, page=1, page_size=1,
        )

    subnets_block = payload[IpamOverviewKey.SUBNETS]
    assert subnets_block[IpamOverviewKey.PAGE_SIZE] == 1
    assert subnets_block[IpamOverviewKey.TOTAL] == 2
    assert len(subnets_block[IpamOverviewKey.ROWS]) == 1


def test_build_supernet_overview_returns_empty_rows_when_no_subnets_exist() -> None:
    """When the supernet has zero subnets, the payload still emits the expected envelope"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[]):
        payload = build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.TOTAL] == 0
    assert payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.SUPERNET][IpamOverviewKey.SUBNET_COUNT] == 0


def test_build_supernet_overview_returns_flat_rows_across_nesting_depths_when_search_active() -> None:
    """An active search drops the top-level filter and returns matching rows at any depth"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}
    row_top_b = {**_make_row(SUBNET_OBJECT_ID_B, '192.168.1.0/24'), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_top_a, row_nested, row_top_b]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, search='10.0.0',
        )

    row_ids = [r[CmdbObjectKey.PUBLIC_ID] for r in payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS]]
    assert row_ids == [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_NESTED_IN_A]
    assert payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.TOTAL] == 2


def test_build_supernet_overview_kpi_summary_is_invariant_under_search_filter() -> None:
    """KPI strip is computed over all subnets regardless of search; filtering doesn't shrink it"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 4}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 1}
    row_top_b = {**_make_row(SUBNET_OBJECT_ID_B, '192.168.1.0/24'), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 2}
    all_rows = [row_top_a, row_nested, row_top_b]

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=all_rows):
        no_search = build_supernet_overview(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)
        with_search = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, search='10.0',
        )

    assert no_search[IpamOverviewKey.SUPERNET] == with_search[IpamOverviewKey.SUPERNET]


def test_build_supernet_overview_falls_back_to_top_level_for_search_below_min_length() -> None:
    """A 1-char search (below IpamSearch.MIN_QUERY_LENGTH) restores the top-level tree view"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_top_a, row_nested]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, search='1',
        )

    row_ids = {r[CmdbObjectKey.PUBLIC_ID] for r in payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS]}
    assert row_ids == {SUBNET_OBJECT_ID_A}


def test_build_supernet_overview_treats_whitespace_only_search_as_no_filter() -> None:
    """A whitespace-only search behaves identically to an empty one - top-level tree restored"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_top_a, row_nested]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, search='   ',
        )

    row_ids = {r[CmdbObjectKey.PUBLIC_ID] for r in payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS]}
    assert row_ids == {SUBNET_OBJECT_ID_A}


def test_build_supernet_overview_returns_empty_rows_when_search_has_no_matches() -> None:
    """An active search with no matching subnets emits an empty rows list and total=0"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_top_a]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, search='172.16',
        )

    assert payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.TOTAL] == 0
    assert payload[IpamOverviewKey.SUBNETS][IpamOverviewKey.ROWS] == []


def test_build_supernet_overview_paginates_flat_search_results() -> None:
    """page_size constraints apply to the filtered flat list just as they do to top-level rows"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_top_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
                 IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_top_a, row_nested]):
        payload = build_supernet_overview(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, page=1, page_size=1, search='10.0',
        )

    subnets_block = payload[IpamOverviewKey.SUBNETS]
    assert subnets_block[IpamOverviewKey.PAGE_SIZE] == 1
    assert subnets_block[IpamOverviewKey.TOTAL] == 2
    assert len(subnets_block[IpamOverviewKey.ROWS]) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                       build_supernet_subnet_children                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_supernet_subnet_children_propagates_load_supernet_aborts() -> None:
    """An abort raised by _load_supernet_object propagates out of the children orchestrator"""
    from werkzeug.exceptions import NotFound

    with patch(f'{PATH}._load_supernet_object', side_effect=NotFound('not found')), \
         pytest.raises(HTTPException) as exc_info:
        build_supernet_subnet_children(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, SUBNET_OBJECT_ID_A)

    assert exc_info.value.code == 404


def test_build_supernet_subnet_children_aborts_400_when_parent_subnet_not_under_supernet() -> None:
    """A subnet id that doesn't appear among the supernet's linked rows → HTTP 400"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[]), \
         pytest.raises(HTTPException) as exc_info:
        build_supernet_subnet_children(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, SUBNET_OBJECT_ID_A,
        )

    assert exc_info.value.code == 400


def test_build_supernet_subnet_children_returns_direct_children_of_parent_subnet() -> None:
    """Happy path: returns the children rows whose parent_id is the requested subnet"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}
    row_nested = {**_make_row(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
                  IpamOverviewKey.PARENT_ID: SUBNET_OBJECT_ID_A, IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a, row_nested]):
        payload = build_supernet_subnet_children(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, SUBNET_OBJECT_ID_A,
        )

    assert payload[IpamOverviewKey.PARENT] == {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID_A}
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in payload[IpamOverviewKey.ROWS]] == [SUBNET_OBJECT_ID_NESTED_IN_A]


def test_build_supernet_subnet_children_returns_empty_rows_when_subnet_has_no_children() -> None:
    """A leaf subnet returns an empty rows list (still wrapping the parent envelope)"""
    supernet_doc = _make_supernet_doc(SUPERNET_OBJECT_ID, SUPERNET_RANGE)
    row_a = {**_make_row(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A), IpamOverviewKey.PARENT_ID: None,
             IpamOverviewKey.USED_IPS: 0}

    with patch(f'{PATH}._load_supernet_object', return_value=supernet_doc), \
         patch(f'{PATH}._build_linked_subnet_rows', return_value=[row_a]):
        payload = build_supernet_subnet_children(
            MagicMock(), MagicMock(), SUPERNET_OBJECT_ID, SUBNET_OBJECT_ID_A,
        )

    assert payload[IpamOverviewKey.ROWS] == []
