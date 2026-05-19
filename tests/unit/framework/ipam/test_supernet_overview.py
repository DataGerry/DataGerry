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
    IpamSection,
    IpamPagination,
    IpamOverviewKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.supernet_overview import (
    _annotate_has_children,
    _build_linked_subnet_rows,
    _count_used_ips_per_subnet,
    _index_children_by_parent,
    _ip_range,
    _load_subnets_for_supernet,
    _load_supernet_object,
    _percent,
    _row_subnet_ref,
    build_supernet_overview,
    build_supernet_subnet_children,
    compute_subnet_row,
    compute_supernet_summary,
    sort_and_link_subnets,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
SUBNET_OBJECT_ID_NESTED_IN_A: int = 211

SUPERNET_RANGE: str = '10.0.0.0/16'
SUBNET_RANGE_A: str = '10.0.0.0/24'
SUBNET_RANGE_B: str = '10.0.1.0/24'
NESTED_IN_A_RANGE: str = '10.0.0.0/25'

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
                            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID_A},
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
    """Returned rows have parent_id annotations and reflect the sort/link pass"""
    subnet_objs = [
        _make_subnet_doc(SUBNET_OBJECT_ID_A, SUBNET_RANGE_A),
        _make_subnet_doc(SUBNET_OBJECT_ID_NESTED_IN_A, NESTED_IN_A_RANGE),
    ]
    used_counts = {SUBNET_OBJECT_ID_A: 5, SUBNET_OBJECT_ID_NESTED_IN_A: 1}

    with patch(f'{PATH}._load_subnets_for_supernet', return_value=subnet_objs), \
         patch(f'{PATH}._count_used_ips_per_subnet', return_value=used_counts):
        result = _build_linked_subnet_rows(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    by_id = {r[CmdbObjectKey.PUBLIC_ID]: r for r in result}
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.PARENT_ID] is None
    assert by_id[SUBNET_OBJECT_ID_NESTED_IN_A][IpamOverviewKey.PARENT_ID] == SUBNET_OBJECT_ID_A
    assert by_id[SUBNET_OBJECT_ID_A][IpamOverviewKey.USED_IPS] == 5


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
