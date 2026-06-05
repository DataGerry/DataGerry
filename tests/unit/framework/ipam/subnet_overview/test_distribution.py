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
Unit tests for cmdb.framework.ipam.subnet_overview.distribution

Covers the IP-Verteilung grid math (format_ip, compute_grid_dimensions, _bucket_used_by_type,
_compose_sector_type_stats, _compose_sector, build_ip_distribution) and the whole-subnet type
pie (build_type_distribution), including the IPv4 / IPv6 family differences (null percentages,
omitted Free bucket) and the validity exclusion of out-of-CIDR rows
"""
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from typing import Any

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamBucketLabel
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.distribution import (
    format_ip,
    compute_grid_dimensions,
    _bucket_used_by_type,
    _compose_sector_type_stats,
    _compose_sector,
    build_ip_distribution,
    build_type_distribution,
)
# -------------------------------------------------------------------------------------------------------------------- #


OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_TYPE_ID: int = 51

SUBNET_RANGE_V6: str = '2001:db8::/64'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_assigned_entry(
    object_id: int,
    type_id: int | None,
    mac: str | None,
    is_valid: bool = True,
) -> dict[str, Any]:
    """Builds one value of the assigned map (the shape load_assigned_rows_map produces)."""
    return {
        AssignedField.OBJECT_ID: object_id,
        AssignedField.TYPE_ID: type_id,
        AssignedField.MAC: mac,
        AssignedField.IS_VALID: is_valid,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   format_ip                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_ip_renders_ipv4_and_ipv6_from_int() -> None:
    """format_ip picks the address family by the flag; IPv6 ints exceed the IPv4 range"""
    assert format_ip(int(IPv4Address('10.0.0.5')), is_ipv6=False) == '10.0.0.5'
    assert format_ip(0, is_ipv6=False) == '0.0.0.0'
    assert format_ip(int(IPv6Network(SUBNET_RANGE_V6).network_address), is_ipv6=True) == '2001:db8::'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            compute_grid_dimensions                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_grid_dimensions_returns_zeros_for_zero_total() -> None:
    """A subnet with zero total addresses yields the zero layout (ranges=0, sectors=0, size=0)"""
    assert compute_grid_dimensions(0) == (0, 0, 0)


def test_compute_grid_dimensions_emits_full_grid_for_slash_24() -> None:
    """/24 (256 addresses) → full 4 ranges × 16 sectors × 4 addresses per sector"""
    assert compute_grid_dimensions(256) == (4, 16, 4)


def test_compute_grid_dimensions_emits_full_grid_for_slash_26() -> None:
    """/26 (64 addresses) → 4 ranges × 16 sectors × 1 address per sector (the minimum)"""
    assert compute_grid_dimensions(64) == (4, 16, 1)


def test_compute_grid_dimensions_shrinks_sector_count_below_slash_26() -> None:
    """/27 (32 addresses) → 4 ranges × 8 sectors × 1 address per sector (sectors halve)"""
    assert compute_grid_dimensions(32) == (4, 8, 1)


def test_compute_grid_dimensions_shrinks_to_one_by_one_for_single_address() -> None:
    """/32 (1 address) → 1 range × 1 sector × 1 address per sector"""
    assert compute_grid_dimensions(1) == (1, 1, 1)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _bucket_used_by_type                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_bucket_used_by_type_returns_empty_breakdowns_for_empty_assigned_map() -> None:
    """An empty assigned map produces a list of empty breakdowns of the requested length"""
    breakdowns = _bucket_used_by_type({}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns == [{}] * 64


def test_bucket_used_by_type_returns_empty_list_when_total_cells_is_zero() -> None:
    """No cells → no breakdowns (guard against division by zero downstream)"""
    breakdowns = _bucket_used_by_type(
        {'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=0,
    )

    assert breakdowns == []


def test_bucket_used_by_type_short_circuits_when_sector_size_is_zero() -> None:
    """Zero sector_size cannot index any cell; the helper returns empty breakdowns without raising"""
    breakdowns = _bucket_used_by_type(
        {'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=0, total_cells=4,
    )

    assert breakdowns == [{}, {}, {}, {}]


def test_bucket_used_by_type_increments_correct_cell_for_assigned_ip() -> None:
    """An IP at offset 5 with sector_size=4 lands in cell index 1 (5 // 4)"""
    breakdowns = _bucket_used_by_type(
        {'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64,
    )

    assert breakdowns[1] == {None: 1}
    assert sum(sum(b.values()) for b in breakdowns) == 1


def test_bucket_used_by_type_skips_ip_outside_the_subnet() -> None:
    """IPs whose offset falls outside the network's span are ignored"""
    breakdowns = _bucket_used_by_type(
        {'192.168.1.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64,
    )

    assert sum(sum(b.values()) for b in breakdowns) == 0


def test_bucket_used_by_type_skips_unparseable_ip_string() -> None:
    """An ip_str that parse_ip cannot parse is skipped without raising"""
    breakdowns = _bucket_used_by_type(
        {'not-an-ip': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64,
    )

    assert sum(sum(b.values()) for b in breakdowns) == 0


def test_bucket_used_by_type_distributes_multiple_assigned_ips_across_cells() -> None:
    """Multiple IPs land in distinct cells when their offsets are in different sector_size groups"""
    assigned = {'10.0.0.1': {}, '10.0.0.5': {}, '10.0.0.9': {}}

    breakdowns = _bucket_used_by_type(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns[0] == {None: 1}
    assert breakdowns[1] == {None: 1}
    assert breakdowns[2] == {None: 1}


def test_bucket_used_by_type_uses_int_type_id_as_bucket_key() -> None:
    """A row with an int type_id lands under that int key in the owning cell's breakdown"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    breakdowns = _bucket_used_by_type(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns[1] == {OWNER_TYPE_ID: 1}


def test_bucket_used_by_type_routes_non_int_type_id_to_none_key() -> None:
    """A non-int type_id (e.g. string) is bucketed under None, not its raw value"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, '50', None)}

    breakdowns = _bucket_used_by_type(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns[1] == {None: 1}


def test_bucket_used_by_type_coalesces_same_type_ips_in_same_cell() -> None:
    """Multiple IPs of the same type in one cell sum into a single bucket"""
    assigned = {
        '10.0.0.4': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
    }

    breakdowns = _bucket_used_by_type(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns[1] == {OWNER_TYPE_ID: 3}


def test_bucket_used_by_type_keeps_distinct_types_in_same_cell_separate() -> None:
    """Two different types in one cell produce two keys with their respective counts"""
    assigned = {
        '10.0.0.4': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID + 2, OTHER_OWNER_TYPE_ID, None),
    }

    breakdowns = _bucket_used_by_type(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert breakdowns[1] == {OWNER_TYPE_ID: 1, OTHER_OWNER_TYPE_ID: 2}


def test_bucket_used_by_type_rejects_ip_exactly_at_span_boundary() -> None:
    """An IP at offset == total_cells * sector_size is outside the grid and is skipped"""
    # network 10.0.0.0/24 has 256 addresses; with sector_size=4 and total_cells=64 the span is 256.
    # 10.0.1.0 has offset 256, which must be rejected (>= span).
    assigned = {'10.0.1.0': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    breakdowns = _bucket_used_by_type(
        assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64,
    )

    assert sum(sum(b.values()) for b in breakdowns) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _compose_sector_type_stats                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_sector_type_stats_returns_empty_list_for_empty_breakdown() -> None:
    """An empty breakdown (used_count == 0) → empty type_stats list"""
    assert _compose_sector_type_stats({}, {}) == []


def test_compose_sector_type_stats_emits_single_known_bucket_at_full_percentage() -> None:
    """One known type covering the whole used count → one bucket at 100%"""
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 4}, type_meta)

    assert stats == [
        {
            CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
            IpamOverviewKey.LABEL: 'Server',
            IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
            IpamOverviewKey.COUNT: 4,
            IpamOverviewKey.PERCENTAGE: 100.0,
        },
    ]


def test_compose_sector_type_stats_sorts_known_buckets_by_count_descending() -> None:
    """Known buckets are ordered count desc (dominant type first)"""
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1, OTHER_OWNER_TYPE_ID: 3}, type_meta)

    labels = [bucket[IpamOverviewKey.LABEL] for bucket in stats]
    assert labels == ['Printer', 'Server']


def test_compose_sector_type_stats_breaks_count_ties_by_public_id_ascending() -> None:
    """When counts tie, the smaller public_id comes first"""
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 2, OTHER_OWNER_TYPE_ID: 2}, type_meta)

    public_ids = [bucket[CmdbObjectKey.PUBLIC_ID] for bucket in stats]
    assert public_ids == [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID]


def test_compose_sector_type_stats_emits_unknown_bucket_last_even_when_largest() -> None:
    """The Unknown bucket is appended last regardless of how large its count is"""
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1, None: 9}, type_meta)

    labels = [bucket[IpamOverviewKey.LABEL] for bucket in stats]
    assert labels == ['Server', IpamBucketLabel.UNKNOWN]


def test_compose_sector_type_stats_routes_orphaned_int_type_id_to_unknown() -> None:
    """An int type_id not present in type_meta is folded into the Unknown bucket"""
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1, 9_999: 2}, type_meta)

    unknown = next(b for b in stats if b[IpamOverviewKey.LABEL] == IpamBucketLabel.UNKNOWN)
    assert unknown[CmdbObjectKey.PUBLIC_ID] is None
    assert unknown[IpamOverviewKey.COUNT] == 2


def test_compose_sector_type_stats_routes_none_key_to_unknown() -> None:
    """A None key in the breakdown is folded into the Unknown bucket"""
    stats = _compose_sector_type_stats({None: 3}, type_meta={})

    assert stats == [
        {
            CmdbObjectKey.PUBLIC_ID: None,
            IpamOverviewKey.LABEL: IpamBucketLabel.UNKNOWN,
            IpamOverviewKey.CI_EXPLORER_COLOR: None,
            IpamOverviewKey.COUNT: 3,
            IpamOverviewKey.PERCENTAGE: 100.0,
        },
    ]


def test_compose_sector_type_stats_unknown_sums_orphans_and_none_keys() -> None:
    """Unknown.count is the sum of None-keyed rows and unresolvable int type_ids"""
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1, None: 2, 9_999: 3}, type_meta)

    unknown = next(b for b in stats if b[IpamOverviewKey.LABEL] == IpamBucketLabel.UNKNOWN)
    assert unknown[IpamOverviewKey.COUNT] == 5


def test_compose_sector_type_stats_rounds_percentages_to_two_decimals() -> None:
    """Percentages are computed against used_count and rounded to 2 decimals (1/3, 2/3 → 33.33, 66.67)"""
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1, OTHER_OWNER_TYPE_ID: 2}, type_meta)

    by_label = {bucket[IpamOverviewKey.LABEL]: bucket[IpamOverviewKey.PERCENTAGE] for bucket in stats}
    assert by_label == {'Server': 33.33, 'Printer': 66.67}


def test_compose_sector_type_stats_emits_none_color_when_type_meta_omits_it() -> None:
    """A type_meta entry without ci_explorer_color yields None on the bucket, not a KeyError"""
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server'}}

    stats = _compose_sector_type_stats({OWNER_TYPE_ID: 1}, type_meta)

    assert stats[0][IpamOverviewKey.CI_EXPLORER_COLOR] is None


def test_compose_sector_type_stats_ipv6_nulls_percentage() -> None:
    """IPv6 sector type-stats keep counts but null the percentage"""
    stats = _compose_sector_type_stats({None: 3}, type_meta={}, is_ipv6=True)

    assert stats[0][IpamOverviewKey.COUNT] == 3
    assert stats[0][IpamOverviewKey.PERCENTAGE] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _compose_sector                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_sector_emits_full_shape_and_rounds_percentage_to_two_decimals() -> None:
    """Output pins ip_start/ip_end/used_count/percentage/type_stats; percentage rounded to 2 decimals"""
    first_int = int(IPv4Address('10.0.0.0'))

    sector = _compose_sector(first_int, sector_size=4, breakdown={None: 1}, type_meta={})

    assert sector == {
        IpamOverviewKey.IP_START: '10.0.0.0',
        IpamOverviewKey.IP_END: '10.0.0.3',
        IpamOverviewKey.USED_COUNT: 1,
        IpamOverviewKey.PERCENTAGE: 25.0,
        IpamOverviewKey.TYPE_STATS: [
            {
                CmdbObjectKey.PUBLIC_ID: None,
                IpamOverviewKey.LABEL: IpamBucketLabel.UNKNOWN,
                IpamOverviewKey.CI_EXPLORER_COLOR: None,
                IpamOverviewKey.COUNT: 1,
                IpamOverviewKey.PERCENTAGE: 100.0,
            },
        ],
    }


def test_compose_sector_ipv6_renders_ipv6_labels_and_nulls_percentage() -> None:
    """IPv6 sector renders IPv6 ip_start/ip_end, keeps used_count, nulls percentage + type_stats %"""
    first_int = int(IPv6Network(SUBNET_RANGE_V6).network_address)

    sector = _compose_sector(first_int, sector_size=2 ** 58, breakdown={None: 1}, type_meta={}, is_ipv6=True)

    expected_end: str = str(IPv6Network(SUBNET_RANGE_V6).network_address + (2 ** 58 - 1))
    assert sector[IpamOverviewKey.IP_START] == '2001:db8::'
    assert sector[IpamOverviewKey.IP_END] == expected_end
    assert sector[IpamOverviewKey.USED_COUNT] == 1
    assert sector[IpamOverviewKey.PERCENTAGE] is None
    assert sector[IpamOverviewKey.TYPE_STATS][0][IpamOverviewKey.PERCENTAGE] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_ip_distribution                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_ip_distribution_returns_empty_dict_when_network_is_none() -> None:
    """A missing/unparsable subnet network → grid suppressed (empty dict)"""
    assert build_ip_distribution(None, {}, {}) == {}


def test_build_ip_distribution_returns_empty_dict_when_subnet_too_small_for_full_grid() -> None:
    """/27 (32 addresses → 4×8 cells) is below the full 4×16 = 64-cell cap and is suppressed"""
    assert build_ip_distribution(IPv4Network('10.0.0.0/27'), {}, {}) == {}


def test_build_ip_distribution_emits_full_grid_for_slash_24() -> None:
    """A /24 yields the full grid: sector_size=4, 4 ranges, each with 16 sectors"""
    grid = build_ip_distribution(IPv4Network('10.0.0.0/24'), {}, {})

    assert grid[IpamOverviewKey.SECTOR_SIZE] == 4
    assert len(grid[IpamOverviewKey.RANGES]) == 4
    for range_block in grid[IpamOverviewKey.RANGES]:
        assert len(range_block[IpamOverviewKey.SECTORS]) == 16


def test_build_ip_distribution_reflects_assigned_counts_in_correct_cells() -> None:
    """An assigned IP appears in its sector's used_count and not in others"""
    assigned: dict[str, dict[str, Any]] = {'10.0.0.5': {}}

    grid = build_ip_distribution(IPv4Network('10.0.0.0/24'), assigned, {})

    # Sector index 1 of range 0 covers 10.0.0.4-10.0.0.7
    first_range = grid[IpamOverviewKey.RANGES][0]
    assert first_range[IpamOverviewKey.SECTORS][1][IpamOverviewKey.USED_COUNT] == 1
    assert first_range[IpamOverviewKey.SECTORS][0][IpamOverviewKey.USED_COUNT] == 0


def test_build_ip_distribution_ipv6_buckets_assigned_ip_into_correct_sector() -> None:
    """An assigned IPv6 address increments exactly its sector's used_count (128-bit bucketing math)"""
    assigned = {'2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)}

    grid = build_ip_distribution(IPv6Network(SUBNET_RANGE_V6), assigned, {})

    # offset 5 // sector_size(2**58) == 0, so range 0 / sector 0 holds the single assigned IP
    first_range = grid[IpamOverviewKey.RANGES][0]
    assert first_range[IpamOverviewKey.SECTORS][0][IpamOverviewKey.USED_COUNT] == 1
    total_used = sum(
        sector[IpamOverviewKey.USED_COUNT]
        for range_block in grid[IpamOverviewKey.RANGES]
        for sector in range_block[IpamOverviewKey.SECTORS]
    )
    assert total_used == 1


def test_build_ip_distribution_ipv6_emits_grid_with_ipv6_labels_and_null_percentages() -> None:
    """An IPv6 /64 still emits the full grid, but with IPv6 boundary labels and null percentages"""
    assigned = {'2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)}

    grid = build_ip_distribution(IPv6Network(SUBNET_RANGE_V6), assigned, {})

    assert grid[IpamOverviewKey.SECTOR_SIZE] == 2 ** 64 // 64
    first_range = grid[IpamOverviewKey.RANGES][0]
    assert first_range[IpamOverviewKey.IP_START] == '2001:db8::'
    assert all(
        sector[IpamOverviewKey.PERCENTAGE] is None
        for range_block in grid[IpamOverviewKey.RANGES]
        for sector in range_block[IpamOverviewKey.SECTORS]
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                         build_type_distribution                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_type_distribution_returns_empty_list_when_total_is_zero() -> None:
    """Zero assignable addresses (e.g. unparsable CIDR) → empty distribution"""
    assert build_type_distribution({}, {}, total=0) == []


def test_build_type_distribution_emits_single_type_bucket_plus_free() -> None:
    """One type covering all assigned IPs → 1 type bucket + Free bucket"""
    assigned = {
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}

    distribution = build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert labels == ['Server', IpamBucketLabel.FREE]


def test_build_type_distribution_emits_unknown_bucket_for_orphaned_type_ids() -> None:
    """Assigned rows whose type_id is absent from type_meta are routed to Unknown"""
    assigned = {
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),  # resolvable
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID, 999, None),             # orphan
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert labels == ['Server', IpamBucketLabel.UNKNOWN, IpamBucketLabel.FREE]


def test_build_type_distribution_routes_non_int_type_id_to_unknown_bucket() -> None:
    """A None/non-int type_id on an assigned row falls into the Unknown bucket"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, None, None)}

    distribution = build_type_distribution(assigned, {}, total=10)

    unknown = next(b for b in distribution if b[IpamOverviewKey.LABEL] == IpamBucketLabel.UNKNOWN)
    assert unknown[IpamOverviewKey.COUNT] == 1


def test_build_type_distribution_omits_unknown_bucket_when_empty() -> None:
    """When every assigned row resolves to a known type, no Unknown bucket appears"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert IpamBucketLabel.UNKNOWN not in labels


def test_build_type_distribution_computes_percentages_against_total() -> None:
    """Percentages are computed against the supplied total and rounded to 2 decimals"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = build_type_distribution(assigned, type_meta, total=100)

    by_label = {b[IpamOverviewKey.LABEL]: b for b in distribution}
    assert by_label['Server'][IpamOverviewKey.PERCENTAGE] == 1.0
    assert by_label[IpamBucketLabel.FREE][IpamOverviewKey.PERCENTAGE] == 99.0


def test_build_type_distribution_excludes_invalid_rows_from_type_counts() -> None:
    """Invalid (out-of-CIDR) rows do not contribute to any type bucket - percentages stay bounded"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = build_type_distribution(assigned, type_meta, total=254)

    server_bucket = next(b for b in distribution if b[CmdbObjectKey.PUBLIC_ID] == OWNER_TYPE_ID)
    free_bucket = next(b for b in distribution if b[IpamOverviewKey.LABEL] == IpamBucketLabel.FREE)
    assert server_bucket[IpamOverviewKey.COUNT] == 1
    assert free_bucket[IpamOverviewKey.COUNT] == 253


def test_build_type_distribution_ipv6_drops_free_bucket_and_nulls_percentage() -> None:
    """IPv6: per-type + Unknown counts only, no Free bucket, percentage None on every bucket"""
    assigned = {
        '2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '2001:db8::6': _make_assigned_entry(OWNER_OBJECT_ID, 999, None),  # orphan -> Unknown
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = build_type_distribution(assigned, type_meta, total=2 ** 64, is_ipv6=True)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert labels == ['Server', IpamBucketLabel.UNKNOWN]
    assert IpamBucketLabel.FREE not in labels
    assert all(b[IpamOverviewKey.PERCENTAGE] is None for b in distribution)
    assert all(b[IpamOverviewKey.COUNT] == 1 for b in distribution)
