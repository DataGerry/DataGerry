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
Unit tests for cmdb.framework.ipam.subnet_overview.candidates

Covers the route-parameter parsers (parse_sort_args, parse_filter_args), the candidate filter
and sort helpers, the assignable-IP enumeration / page slice / substring matcher, the lazy-vs-
materialized policy of resolve_candidate_ips, and the MAX_MATERIALIZED_CANDIDATES size guard
(abort 400 on search / sort / filter over an oversized subnet; lazy fallback when only invalid
rows would force materialization)
"""
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamRowStatus,
    IpamSortColumn,
    IpamSortDirection,
)
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.candidates import (
    page_slice_ips,
    list_all_assignable_ips,
    list_assignable_ips_matching_substring,
    _compute_sort_key,
    _sort_candidate_ips,
    _apply_candidate_filter,
    resolve_candidate_ips,
    parse_filter_args,
    parse_sort_args,
)
# -------------------------------------------------------------------------------------------------------------------- #


OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_TYPE_ID: int = 51

SUBNET_RANGE_V6: str = '2001:db8::/64'
# A /8 has ~16M assignable addresses, far above MAX_MATERIALIZED_CANDIDATES (2**20)
OVERSIZED_RANGE: str = '10.0.0.0/8'


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
#                                                parse_sort_args                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_sort_args_returns_none_when_sort_is_empty() -> None:
    """Empty sort yields (None, ASC) so the orchestrator stays on the lazy path"""
    assert parse_sort_args('', '') == (None, IpamSortDirection.ASC)


def test_parse_sort_args_returns_none_for_whitespace_only_sort() -> None:
    """A whitespace-only sort value strips to empty and is treated as no sort"""
    assert parse_sort_args('   ', '-1') == (None, IpamSortDirection.ASC)


def test_parse_sort_args_returns_asc_default_when_order_is_empty() -> None:
    """sort present, order missing → defaults to ASC"""
    assert parse_sort_args('ip', '') == (IpamSortColumn.IP, IpamSortDirection.ASC)


def test_parse_sort_args_returns_explicit_direction_when_order_is_desc() -> None:
    """sort + explicit '-1' parses to the DESC direction (Mongo convention)"""
    assert parse_sort_args('ip', '-1') == (IpamSortColumn.IP, IpamSortDirection.DESC)


@pytest.mark.parametrize('col', list(IpamSortColumn))
def test_parse_sort_args_accepts_every_sort_column(col: IpamSortColumn) -> None:
    """Every IpamSortColumn member is accepted by the parser"""
    parsed_col, parsed_dir = parse_sort_args(col.value, '1')
    assert parsed_col == col
    assert parsed_dir == IpamSortDirection.ASC


def test_parse_sort_args_aborts_400_for_unknown_sort_column() -> None:
    """Unknown sort column → HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        parse_sort_args('foo', '1')

    assert exc_info.value.code == 400


def test_parse_sort_args_aborts_400_for_unknown_sort_direction() -> None:
    """Unknown order value → HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        parse_sort_args('ip', 'sideways')

    assert exc_info.value.code == 400


def test_parse_sort_args_ignores_unknown_order_when_sort_is_empty() -> None:
    """When sort is empty the order is irrelevant and never validated"""
    assert parse_sort_args('', 'sideways') == (None, IpamSortDirection.ASC)


# -------------------------------------------------------------------------------------------------------------------- #
#                                               parse_filter_args                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_filter_args_returns_none_and_empty_list_when_both_empty() -> None:
    """Both inputs empty → (None, []) and the orchestrator skips filtering"""
    assert parse_filter_args('', '') == (None, [])


def test_parse_filter_args_treats_whitespace_only_values_as_empty() -> None:
    """Whitespace-only strings strip to empty and are treated as 'no filter'"""
    assert parse_filter_args('   ', '   ') == (None, [])


def test_parse_filter_args_parses_assigned_status() -> None:
    """A valid 'assigned' status value parses to IpamRowStatus.ASSIGNED"""
    status_filter, type_filter = parse_filter_args('assigned', '')

    assert status_filter == IpamRowStatus.ASSIGNED
    assert type_filter == []


def test_parse_filter_args_parses_free_status() -> None:
    """A valid 'free' status value parses to IpamRowStatus.FREE"""
    status_filter, type_filter = parse_filter_args('free', '')

    assert status_filter == IpamRowStatus.FREE
    assert type_filter == []


def test_parse_filter_args_parses_single_type_as_list_of_one_int() -> None:
    """A single numeric value wraps in a one-element list"""
    status_filter, type_filter = parse_filter_args('', '50')

    assert status_filter is None
    assert type_filter == [50]


def test_parse_filter_args_parses_multi_type_preserving_input_order() -> None:
    """Comma-separated values produce a list in input order"""
    _, type_filter = parse_filter_args('', '50,51,52')

    assert type_filter == [50, 51, 52]


def test_parse_filter_args_strips_whitespace_around_type_elements() -> None:
    """Whitespace around each comma-separated element is stripped before parsing"""
    _, type_filter = parse_filter_args('', '  50 , 51 ,52  ')

    assert type_filter == [50, 51, 52]


def test_parse_filter_args_skips_empty_type_elements() -> None:
    """Empty elements from doubled commas / trailing commas are silently skipped"""
    _, type_filter = parse_filter_args('', '50,,51,')

    assert type_filter == [50, 51]


def test_parse_filter_args_dedupes_repeated_type_elements_preserving_first_position() -> None:
    """Duplicates are collapsed and the first occurrence's position is preserved"""
    _, type_filter = parse_filter_args('', '52,50,52,51,50')

    assert type_filter == [52, 50, 51]


def test_parse_filter_args_returns_both_when_both_provided() -> None:
    """Status and type are independent; both populated produces both populated"""
    status_filter, type_filter = parse_filter_args('assigned', '50,51')

    assert status_filter == IpamRowStatus.ASSIGNED
    assert type_filter == [50, 51]


def test_parse_filter_args_aborts_400_on_unknown_status() -> None:
    """An unknown status value aborts HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        parse_filter_args('partial', '')

    assert exc_info.value.code == 400


def test_parse_filter_args_aborts_400_on_non_integer_type_element() -> None:
    """A non-integer element anywhere in the comma-separated list aborts HTTP 400"""
    with pytest.raises(HTTPException) as exc_info:
        parse_filter_args('', '50,server,52')

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _apply_candidate_filter                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_apply_candidate_filter_returns_input_when_both_filters_inactive() -> None:
    """No status and no type → list passes through unchanged (no copy required)"""
    candidates = ['10.0.0.1', '10.0.0.2']

    assert _apply_candidate_filter(candidates, None, [], {}) is candidates


def test_apply_candidate_filter_status_assigned_keeps_only_assigned_ips() -> None:
    """status=ASSIGNED keeps IPs present in the assigned map; free IPs drop"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _apply_candidate_filter(['10.0.0.1', '10.0.0.2'], IpamRowStatus.ASSIGNED, [], assigned)

    assert result == ['10.0.0.1']


def test_apply_candidate_filter_status_free_keeps_only_unassigned_ips() -> None:
    """status=FREE keeps IPs absent from the assigned map; assigned IPs drop"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _apply_candidate_filter(['10.0.0.1', '10.0.0.2'], IpamRowStatus.FREE, [], assigned)

    assert result == ['10.0.0.2']


def test_apply_candidate_filter_single_type_keeps_only_assigned_rows_of_that_type() -> None:
    """type filter with one element keeps only IPs whose assigned owner type matches"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
    }

    result = _apply_candidate_filter(
        ['10.0.0.1', '10.0.0.2', '10.0.0.3'], None, [OWNER_TYPE_ID], assigned,
    )

    assert result == ['10.0.0.1']


def test_apply_candidate_filter_multi_type_keeps_rows_in_the_set_via_or() -> None:
    """type filter with multiple elements is OR-combined: any matching type passes"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
        '10.0.0.4': _make_assigned_entry(OWNER_OBJECT_ID + 2, 9_999, None),
    }

    result = _apply_candidate_filter(
        ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4'],
        None, [OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID], assigned,
    )

    assert result == ['10.0.0.1', '10.0.0.2']


def test_apply_candidate_filter_combines_status_and_type_via_and() -> None:
    """Both filters apply together: only assigned IPs of one of the named types pass"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
    }

    result = _apply_candidate_filter(
        ['10.0.0.1', '10.0.0.2', '10.0.0.3'],
        IpamRowStatus.ASSIGNED, [OWNER_TYPE_ID], assigned,
    )

    assert result == ['10.0.0.1']


def test_apply_candidate_filter_free_with_type_is_always_empty() -> None:
    """status=FREE + any non-empty type filter yields an empty list (free rows have no type)"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _apply_candidate_filter(
        ['10.0.0.1', '10.0.0.2'], IpamRowStatus.FREE, [OWNER_TYPE_ID], assigned,
    )

    assert result == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                page_slice_ips                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_page_slice_ips_returns_first_page_of_assignable_addresses_for_slash_24() -> None:
    """A /24 first page yields hosts starting at .1 (network address excluded)"""
    ips = page_slice_ips(IPv4Network('10.0.0.0/24'), page=1, page_size=5)

    assert ips == ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5']


def test_page_slice_ips_returns_last_page_partially_when_size_exceeds_remainder() -> None:
    """A page that runs past the last assignable address yields only the remaining IPs"""
    ips = page_slice_ips(IPv4Network('10.0.0.0/30'), page=1, page_size=10)

    # /30 has 2 assignable addresses (.1, .2)
    assert ips == ['10.0.0.1', '10.0.0.2']


def test_page_slice_ips_returns_empty_when_start_offset_past_end() -> None:
    """Requesting a page past the assignable range yields an empty list"""
    ips = page_slice_ips(IPv4Network('10.0.0.0/24'), page=100, page_size=50)

    assert ips == []


def test_page_slice_ips_includes_both_endpoints_for_slash_31() -> None:
    """/31 has 2 assignable hosts (RFC 3021 point-to-point — no network/broadcast reservation)"""
    ips = page_slice_ips(IPv4Network('10.0.0.0/31'), page=1, page_size=5)

    assert ips == ['10.0.0.0', '10.0.0.1']


def test_page_slice_ips_returns_single_address_for_slash_32() -> None:
    """/32 has 1 assignable host (the network address itself, host-route policy)"""
    ips = page_slice_ips(IPv4Network('10.0.0.5/32'), page=1, page_size=5)

    assert ips == ['10.0.0.5']


# -------------------------------------------------------------------------------------------------------------------- #
#                                          list_all_assignable_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_list_all_assignable_ips_returns_full_range_for_slash_24() -> None:
    """A /24 yields 254 entries (.0 and .255 skipped) in ascending integer order"""
    result = list_all_assignable_ips(IPv4Network('10.0.0.0/24'))

    assert len(result) == 254
    assert result[0] == '10.0.0.1'
    assert result[-1] == '10.0.0.254'


def test_list_all_assignable_ips_includes_both_endpoints_for_slash_31() -> None:
    """/31 includes both endpoints (RFC 3021 point-to-point)"""
    assert list_all_assignable_ips(IPv4Network('10.0.0.0/31')) == ['10.0.0.0', '10.0.0.1']


def test_list_all_assignable_ips_includes_single_host_for_slash_32() -> None:
    """/32 covers exactly the one host address"""
    assert list_all_assignable_ips(IPv4Network('10.0.0.5/32')) == ['10.0.0.5']


def test_list_all_assignable_ips_skips_network_and_broadcast_for_slash_30() -> None:
    """/30 has 4 addresses but only 2 assignable; .0 and .3 are skipped"""
    assert list_all_assignable_ips(IPv4Network('10.0.0.0/30')) == ['10.0.0.1', '10.0.0.2']


# -------------------------------------------------------------------------------------------------------------------- #
#                                    list_assignable_ips_matching_substring                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_list_assignable_ips_matching_substring_returns_empty_when_no_ip_matches() -> None:
    """A needle with no occurrences in the assignable range yields an empty list"""
    network = IPv4Network('10.0.0.0/24')

    assert list_assignable_ips_matching_substring(network, '99.99') == []


def test_list_assignable_ips_matching_substring_returns_all_matching_in_ascending_order() -> None:
    """A common-prefix needle returns every match in ascending IP order"""
    network = IPv4Network('10.0.0.0/24')

    result = list_assignable_ips_matching_substring(network, '10.0.0.1')

    assert result[:3] == ['10.0.0.1', '10.0.0.10', '10.0.0.11']
    assert all(ip.startswith('10.0.0.') for ip in result)


def test_list_assignable_ips_matching_substring_matches_anywhere_in_the_canonical_string() -> None:
    """Substring is matched anywhere in the dotted-quad string, not just as a prefix"""
    network = IPv4Network('10.0.0.0/24')

    result = list_assignable_ips_matching_substring(network, '.0.42')

    assert result == ['10.0.0.42']


def test_list_assignable_ips_matching_substring_is_case_insensitive() -> None:
    """Both the needle and the IP string are lowered before the substring check"""
    network = IPv4Network('10.0.0.0/24')

    result_lower = list_assignable_ips_matching_substring(network, '10.0.0.5')
    result_upper = list_assignable_ips_matching_substring(network, '10.0.0.5'.upper())

    assert result_lower == result_upper == ['10.0.0.5', '10.0.0.50', '10.0.0.51', '10.0.0.52', '10.0.0.53',
                                            '10.0.0.54', '10.0.0.55', '10.0.0.56', '10.0.0.57', '10.0.0.58',
                                            '10.0.0.59']


def test_list_assignable_ips_matching_substring_skips_network_and_broadcast_for_slash_24() -> None:
    """The same address-skipping policy page_slice_ips uses: /24 skips .0 and .255"""
    network = IPv4Network('10.0.0.0/24')

    result = list_assignable_ips_matching_substring(network, '10.0.0.')

    assert '10.0.0.0' not in result
    assert '10.0.0.255' not in result
    assert '10.0.0.1' in result
    assert '10.0.0.254' in result


def test_list_assignable_ips_matching_substring_includes_both_endpoints_for_slash_31() -> None:
    """/31 includes both endpoints (RFC 3021 point-to-point)"""
    network = IPv4Network('10.0.0.0/31')

    result = list_assignable_ips_matching_substring(network, '10.0.0.')

    assert result == ['10.0.0.0', '10.0.0.1']


def test_list_assignable_ips_matching_substring_includes_single_host_for_slash_32() -> None:
    """/32 covers exactly one address; a matching needle includes it"""
    network = IPv4Network('10.0.0.5/32')

    assert list_assignable_ips_matching_substring(network, '10.0.0.5') == ['10.0.0.5']


def test_list_assignable_ips_matching_substring_returns_empty_for_unmatched_single_host() -> None:
    """A /32 whose single address does not contain the needle yields an empty list"""
    network = IPv4Network('10.0.0.5/32')

    assert list_assignable_ips_matching_substring(network, '99') == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _compute_sort_key                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_sort_key_returns_integer_for_ip_column() -> None:
    """The IP column returns the integer value of the address for numeric sorting"""
    result = _compute_sort_key('10.0.0.5', IpamSortColumn.IP, assigned={}, type_meta={}, summary_lines={})

    assert result == int(IPv4Address('10.0.0.5'))


def test_compute_sort_key_returns_assigned_status_for_assigned_ip() -> None:
    """STATUS column returns 'assigned' when the IP is in the assigned map"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _compute_sort_key('10.0.0.1', IpamSortColumn.STATUS, assigned=assigned, type_meta={}, summary_lines={})

    assert result == IpamRowStatus.ASSIGNED


def test_compute_sort_key_returns_free_status_for_unassigned_ip() -> None:
    """STATUS column returns 'free' when the IP is NOT in the assigned map"""
    result = _compute_sort_key('10.0.0.1', IpamSortColumn.STATUS, assigned={}, type_meta={}, summary_lines={})

    assert result == IpamRowStatus.FREE


def test_compute_sort_key_returns_lowercased_label_for_type_column() -> None:
    """TYPE column returns the lowercase type label so the sort is case-insensitive"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    result = _compute_sort_key(
        '10.0.0.1', IpamSortColumn.TYPE,
        assigned=assigned, type_meta=type_meta, summary_lines={},
    )

    assert result == 'server'


def test_compute_sort_key_returns_none_for_type_on_free_ip() -> None:
    """A free IP has no type → key is None (NULLS LAST partition)"""
    result = _compute_sort_key('10.0.0.1', IpamSortColumn.TYPE, assigned={}, type_meta={}, summary_lines={})

    assert result is None


def test_compute_sort_key_returns_none_for_type_when_type_meta_missing() -> None:
    """Assigned IP whose type_id has no meta entry → None (treated as NULL)"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _compute_sort_key('10.0.0.1', IpamSortColumn.TYPE, assigned=assigned, type_meta={}, summary_lines={})

    assert result is None


def test_compute_sort_key_returns_lowercased_summary_for_assigned_to_column() -> None:
    """ASSIGNED_TO column reads the lowercase summary line from summary_lines"""
    result = _compute_sort_key(
        '10.0.0.1', IpamSortColumn.ASSIGNED_TO,
        assigned={'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)},
        type_meta={},
        summary_lines={'10.0.0.1': 'Server: WEB01'},
    )

    assert result == 'server: web01'


def test_compute_sort_key_returns_none_for_assigned_to_when_summary_missing() -> None:
    """No summary line for the IP → None (NULLS LAST partition)"""
    result = _compute_sort_key(
        '10.0.0.1', IpamSortColumn.ASSIGNED_TO, assigned={}, type_meta={}, summary_lines={},
    )

    assert result is None


def test_compute_sort_key_returns_lowercased_mac_for_mac_address_column() -> None:
    """MAC_ADDRESS column returns the lowercase MAC string"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'AA:BB:CC:DD:EE:FF')}

    result = _compute_sort_key(
        '10.0.0.1', IpamSortColumn.MAC_ADDRESS, assigned=assigned, type_meta={}, summary_lines={},
    )

    assert result == 'aa:bb:cc:dd:ee:ff'


def test_compute_sort_key_returns_none_for_mac_when_assigned_entry_lacks_mac() -> None:
    """An assigned IP without a MAC value yields None for MAC_ADDRESS sort"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    result = _compute_sort_key(
        '10.0.0.1', IpamSortColumn.MAC_ADDRESS, assigned=assigned, type_meta={}, summary_lines={},
    )

    assert result is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _sort_candidate_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_sort_candidate_ips_ip_asc_uses_numeric_order_not_lexicographic() -> None:
    """IP+ASC sorts by integer value: 10.0.0.2 < 10.0.0.10 numerically (vs lexicographic)"""
    candidates = ['10.0.0.10', '10.0.0.2', '10.0.0.1']

    result = _sort_candidate_ips(
        candidates, IpamSortColumn.IP, IpamSortDirection.ASC,
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result == ['10.0.0.1', '10.0.0.2', '10.0.0.10']


def test_sort_candidate_ips_ip_desc_reverses_numeric_order() -> None:
    """IP+DESC reverses the numeric IP order"""
    candidates = ['10.0.0.1', '10.0.0.10', '10.0.0.2']

    result = _sort_candidate_ips(
        candidates, IpamSortColumn.IP, IpamSortDirection.DESC,
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result == ['10.0.0.10', '10.0.0.2', '10.0.0.1']


def test_sort_candidate_ips_ip_path_does_not_call_resolve_summary_lines() -> None:
    """The IP fast path bypasses both the partition and the summary-line batch"""
    candidates = ['10.0.0.2', '10.0.0.1']
    objects_manager = MagicMock()

    _sort_candidate_ips(
        candidates, IpamSortColumn.IP, IpamSortDirection.ASC,
        assigned={}, type_meta={}, objects_manager=objects_manager,
    )

    objects_manager.get_summary_lines_lookup.assert_not_called()


def test_sort_candidate_ips_type_places_assigned_before_free_in_asc() -> None:
    """Assigned IPs with a type label sort before free IPs (NULLS LAST in ASC)"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    result = _sort_candidate_ips(
        ['10.0.0.1', '10.0.0.5'], IpamSortColumn.TYPE, IpamSortDirection.ASC,
        assigned=assigned, type_meta=type_meta, objects_manager=MagicMock(),
    )

    assert result == ['10.0.0.5', '10.0.0.1']


def test_sort_candidate_ips_type_places_null_keyed_rows_last_in_desc_too() -> None:
    """NULLS always trail - even in DESC the assigned IPs come before the free ones"""
    assigned = {
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
    }
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }

    result = _sort_candidate_ips(
        ['10.0.0.5', '10.0.0.6', '10.0.0.1'], IpamSortColumn.TYPE, IpamSortDirection.DESC,
        assigned=assigned, type_meta=type_meta, objects_manager=MagicMock(),
    )

    # 'server' > 'printer' lexicographically (case-insensitive), so DESC puts server first
    assert result == ['10.0.0.5', '10.0.0.6', '10.0.0.1']


def test_sort_candidate_ips_assigned_to_short_circuits_when_no_candidate_is_assigned() -> None:
    """When no candidate is in the assigned map, the summary-line batch is never called"""
    objects_manager = MagicMock()

    result = _sort_candidate_ips(
        ['10.0.0.1', '10.0.0.2'], IpamSortColumn.ASSIGNED_TO, IpamSortDirection.ASC,
        assigned={}, type_meta={}, objects_manager=objects_manager,
    )

    objects_manager.get_summary_lines_lookup.assert_not_called()
    # All NULL keys → preserves input order
    assert result == ['10.0.0.1', '10.0.0.2']


def test_sort_candidate_ips_assigned_to_calls_summary_batch_when_assigned_present() -> None:
    """An assigned candidate IP triggers the summary-line batch fetch"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    _sort_candidate_ips(
        ['10.0.0.1', '10.0.0.2'], IpamSortColumn.ASSIGNED_TO, IpamSortDirection.ASC,
        assigned=assigned, type_meta={}, objects_manager=objects_manager,
    )

    objects_manager.get_summary_lines_lookup.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            resolve_candidate_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_candidate_ips_returns_none_for_no_search_and_no_sort() -> None:
    """No search and no sort → None signals the lazy path"""
    network = IPv4Network('10.0.0.0/24')

    result = resolve_candidate_ips(
        network, search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is None


def test_resolve_candidate_ips_returns_none_for_default_ip_asc_sort_with_no_search() -> None:
    """Default ip+asc with no search is equivalent to no sort - lazy path still applies"""
    network = IPv4Network('10.0.0.0/24')

    result = resolve_candidate_ips(
        network, search='', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is None


def test_resolve_candidate_ips_returns_full_list_for_ip_desc_with_no_search() -> None:
    """Non-default sort forces materialization even without an active search"""
    network = IPv4Network('10.0.0.0/30')

    result = resolve_candidate_ips(
        network, search='', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.DESC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result == ['10.0.0.2', '10.0.0.1']


def test_resolve_candidate_ips_filters_by_search_then_sorts() -> None:
    """Active search builds the matching list which is then sorted (search ∩ sort)"""
    network = IPv4Network('10.0.0.0/24')

    result = resolve_candidate_ips(
        network, search='10.0.0.5', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.DESC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    # Same set as no-sort search result, but reversed
    assert result[0] == '10.0.0.59'
    assert result[-1] == '10.0.0.5'


def test_resolve_candidate_ips_returns_matching_list_for_search_with_no_sort() -> None:
    """Search active but no sort → returns the substring-matched list in natural order"""
    network = IPv4Network('10.0.0.0/24')

    result = resolve_candidate_ips(
        network, search='10.0.0.5', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is not None
    assert all('10.0.0.5' in ip for ip in result)
    assert result[0] == '10.0.0.5'


# -------------------------------------------------------------------------------------------------------------------- #
#                              resolve_candidate_ips - MAX_MATERIALIZED_CANDIDATES guard                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_candidate_ips_aborts_400_when_oversized_subnet_is_searched() -> None:
    """An active search over a subnet above the materialization cap aborts HTTP 400"""
    network = IPv4Network(OVERSIZED_RANGE)

    with pytest.raises(HTTPException) as exc_info:
        resolve_candidate_ips(
            network, search='10.0.0.5', sort_col=None, sort_dir=IpamSortDirection.ASC,
            status_filter=None, type_filter=[],
            assigned={}, type_meta={}, objects_manager=MagicMock(),
        )

    assert exc_info.value.code == 400


def test_resolve_candidate_ips_aborts_400_when_oversized_subnet_is_sorted_non_natural() -> None:
    """A non-natural sort over an oversized subnet aborts HTTP 400"""
    network = IPv4Network(OVERSIZED_RANGE)

    with pytest.raises(HTTPException) as exc_info:
        resolve_candidate_ips(
            network, search='', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.DESC,
            status_filter=None, type_filter=[],
            assigned={}, type_meta={}, objects_manager=MagicMock(),
        )

    assert exc_info.value.code == 400


def test_resolve_candidate_ips_aborts_400_when_oversized_subnet_is_filtered() -> None:
    """A status / type filter over an oversized subnet aborts HTTP 400"""
    network = IPv4Network(OVERSIZED_RANGE)

    with pytest.raises(HTTPException) as exc_info:
        resolve_candidate_ips(
            network, search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
            status_filter=IpamRowStatus.ASSIGNED, type_filter=[],
            assigned={}, type_meta={}, objects_manager=MagicMock(),
        )

    assert exc_info.value.code == 400


def test_resolve_candidate_ips_lazy_fallback_when_only_invalid_rows_force_materialization() -> None:
    """Oversized subnet + only invalid rows (no search/sort/filter) → None (lazy fallback)"""
    network = IPv4Network(OVERSIZED_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }

    result = resolve_candidate_ips(
        network, search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned=assigned, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                       resolve_candidate_ips - IPv6                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_candidate_ips_ipv6_lists_assigned_only_never_enumerates() -> None:
    """For IPv6 the candidates are the assigned IPs only (valid first, invalid trailing); no free space"""
    assigned = {
        '2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '2001:db8::2': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '2001:dead::9': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }

    result = resolve_candidate_ips(
        IPv6Network(SUBNET_RANGE_V6), search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[], assigned=assigned, type_meta={},
        objects_manager=MagicMock(), is_ipv6=True,
    )

    assert result == ['2001:db8::2', '2001:db8::5', '2001:dead::9']


def test_resolve_candidate_ips_ipv6_search_filters_within_assigned() -> None:
    """An active search narrows the assigned-only candidate list by substring"""
    assigned = {
        '2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '2001:db8::beef': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
    }

    result = resolve_candidate_ips(
        IPv6Network(SUBNET_RANGE_V6), search='beef', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[], assigned=assigned, type_meta={},
        objects_manager=MagicMock(), is_ipv6=True,
    )

    assert result == ['2001:db8::beef']


def test_resolve_candidate_ips_ipv6_status_free_yields_empty() -> None:
    """status=free has no free rows to return for IPv6 (assigned-only), so the page is empty"""
    assigned = {'2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)}

    result = resolve_candidate_ips(
        IPv6Network(SUBNET_RANGE_V6), search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=IpamRowStatus.FREE, type_filter=[], assigned=assigned, type_meta={},
        objects_manager=MagicMock(), is_ipv6=True,
    )

    assert result == []
