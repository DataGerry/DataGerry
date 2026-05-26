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
Unit tests for cmdb.framework.ipam.subnet_overview

Covers the pure helpers (page slicing, row composers, MDS row extraction, grid math, type
distribution math), the three DB loaders (_load_subnet_object, _load_assigned_rows_map,
_resolve_type_meta) and the build_subnet_overview orchestrator. Composers are exercised with
one shape-pinning test each since they form the row wire-contract that reaches the frontend
verbatim. Mongo filter shapes are pinned via assert_called_once_with so a future refactor that
loosens them fails loudly. Flask aborts are exercised via pytest.raises(HTTPException). For
orchestrator tests the internal loaders are patched at the module path; each loader has its
own dedicated tests in this file
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamOverviewKey,
    IpamRowStatus,
    IpamBucketLabel,
    IpamSortColumn,
    IpamSortDirection,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.subnet_overview import (
    _AssignedField,
    _apply_candidate_filter,
    _build_broken_state_payload,
    _bucket_used_counts,
    _build_ip_distribution,
    _build_ips_block,
    _build_type_distribution,
    _compose_assigned_row,
    _compose_free_row,
    _compose_ip_row,
    _compose_sector,
    _compute_grid_dimensions,
    _compute_sort_key,
    _extract_row_fields,
    _load_assigned_rows_map,
    _load_subnet_object,
    _page_slice_ips,
    _parse_filter_args,
    _parse_sort_args,
    _parse_subnet_network,
    _resolve_assigned_summary_lines,
    _resolve_candidate_ips,
    _resolve_type_meta,
    _sort_candidate_ips,
    _sorted_invalid_ips,
    build_invalid_subnet_overview,
    build_subnet_overview,
    list_all_assignable_ips,
    list_assignable_ips_matching_substring,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_TYPE_ID: int = 51

SUBNET_RANGE: str = '10.0.0.0/24'
PATH: str = 'cmdb.framework.ipam.subnet_overview'


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


def _make_interface_row(
    subnet_ref: int | None = None,
    ip: str | None = None,
    mac: str | None = None,
    include_extras: bool = False,
) -> dict[str, Any]:
    """Builds one dg-ipam-interface MDS row with the requested field entries."""
    data: list[dict[str, Any]] = []

    if subnet_ref is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: subnet_ref})

    if ip is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: ip})

    if mac is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.MAC, CmdbObjectFieldKey.VALUE: mac})

    if include_extras:
        data.append({CmdbObjectFieldKey.NAME: 'dg-unrelated-field', CmdbObjectFieldKey.VALUE: 'ignored'})

    return {CmdbObjectMdsRowKey.DATA: data}


def _make_interface_carrier(
    public_id: int,
    type_id: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Builds a CmdbObject doc with one dg-ipam-interface MDS section carrying the given rows."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: rows,
            },
        ],
    }


def _make_assigned_entry(
    object_id: int,
    type_id: int | None,
    mac: str | None,
    is_valid: bool = True,
) -> dict[str, Any]:
    """Builds one value of the assigned map (the shape _load_assigned_rows_map produces)."""
    return {
        _AssignedField.OBJECT_ID: object_id,
        _AssignedField.TYPE_ID: type_id,
        _AssignedField.MAC: mac,
        _AssignedField.IS_VALID: is_valid,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _parse_sort_args                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_sort_args_returns_none_when_sort_is_empty() -> None:
    """Empty sort yields (None, ASC) so the orchestrator stays on the lazy path"""
    assert _parse_sort_args('', '') == (None, IpamSortDirection.ASC)


def test_parse_sort_args_returns_none_for_whitespace_only_sort() -> None:
    """A whitespace-only sort value strips to empty and is treated as no sort"""
    assert _parse_sort_args('   ', '-1') == (None, IpamSortDirection.ASC)


def test_parse_sort_args_returns_asc_default_when_order_is_empty() -> None:
    """sort present, order missing → defaults to ASC"""
    assert _parse_sort_args('ip', '') == (IpamSortColumn.IP, IpamSortDirection.ASC)


def test_parse_sort_args_returns_explicit_direction_when_order_is_desc() -> None:
    """sort + explicit '-1' parses to the DESC direction (Mongo convention)"""
    assert _parse_sort_args('ip', '-1') == (IpamSortColumn.IP, IpamSortDirection.DESC)


@pytest.mark.parametrize('col', list(IpamSortColumn))
def test_parse_sort_args_accepts_every_sort_column(col: IpamSortColumn) -> None:
    """Every IpamSortColumn member is accepted by the parser"""
    parsed_col, parsed_dir = _parse_sort_args(col.value, '1')
    assert parsed_col == col
    assert parsed_dir == IpamSortDirection.ASC


def test_parse_sort_args_aborts_400_for_unknown_sort_column() -> None:
    """Unknown sort column → HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_sort_args('foo', '1')

    assert exc_info.value.code == 400


def test_parse_sort_args_aborts_400_for_unknown_sort_direction() -> None:
    """Unknown order value → HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_sort_args('ip', 'sideways')

    assert exc_info.value.code == 400


def test_parse_sort_args_ignores_unknown_order_when_sort_is_empty() -> None:
    """When sort is empty the order is irrelevant and never validated"""
    assert _parse_sort_args('', 'sideways') == (None, IpamSortDirection.ASC)


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _parse_filter_args                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_filter_args_returns_none_and_empty_list_when_both_empty() -> None:
    """Both inputs empty → (None, []) and the orchestrator skips filtering"""
    assert _parse_filter_args('', '') == (None, [])


def test_parse_filter_args_treats_whitespace_only_values_as_empty() -> None:
    """Whitespace-only strings strip to empty and are treated as 'no filter'"""
    assert _parse_filter_args('   ', '   ') == (None, [])


def test_parse_filter_args_parses_assigned_status() -> None:
    """A valid 'assigned' status value parses to IpamRowStatus.ASSIGNED"""
    status_filter, type_filter = _parse_filter_args('assigned', '')

    assert status_filter == IpamRowStatus.ASSIGNED
    assert type_filter == []


def test_parse_filter_args_parses_free_status() -> None:
    """A valid 'free' status value parses to IpamRowStatus.FREE"""
    status_filter, type_filter = _parse_filter_args('free', '')

    assert status_filter == IpamRowStatus.FREE
    assert type_filter == []


def test_parse_filter_args_parses_single_type_as_list_of_one_int() -> None:
    """A single numeric value wraps in a one-element list"""
    status_filter, type_filter = _parse_filter_args('', '50')

    assert status_filter is None
    assert type_filter == [50]


def test_parse_filter_args_parses_multi_type_preserving_input_order() -> None:
    """Comma-separated values produce a list in input order"""
    _, type_filter = _parse_filter_args('', '50,51,52')

    assert type_filter == [50, 51, 52]


def test_parse_filter_args_strips_whitespace_around_type_elements() -> None:
    """Whitespace around each comma-separated element is stripped before parsing"""
    _, type_filter = _parse_filter_args('', '  50 , 51 ,52  ')

    assert type_filter == [50, 51, 52]


def test_parse_filter_args_skips_empty_type_elements() -> None:
    """Empty elements from doubled commas / trailing commas are silently skipped"""
    _, type_filter = _parse_filter_args('', '50,,51,')

    assert type_filter == [50, 51]


def test_parse_filter_args_dedupes_repeated_type_elements_preserving_first_position() -> None:
    """Duplicates are collapsed and the first occurrence's position is preserved"""
    _, type_filter = _parse_filter_args('', '52,50,52,51,50')

    assert type_filter == [52, 50, 51]


def test_parse_filter_args_returns_both_when_both_provided() -> None:
    """Status and type are independent; both populated produces both populated"""
    status_filter, type_filter = _parse_filter_args('assigned', '50,51')

    assert status_filter == IpamRowStatus.ASSIGNED
    assert type_filter == [50, 51]


def test_parse_filter_args_aborts_400_on_unknown_status() -> None:
    """An unknown status value aborts HTTP 400 with the offending value in the message"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_filter_args('partial', '')

    assert exc_info.value.code == 400


def test_parse_filter_args_aborts_400_on_non_integer_type_element() -> None:
    """A non-integer element anywhere in the comma-separated list aborts HTTP 400"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_filter_args('', '50,server,52')

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
#                                                _page_slice_ips                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_page_slice_ips_returns_first_page_of_assignable_addresses_for_slash_24() -> None:
    """A /24 first page yields hosts starting at .1 (network address excluded)"""
    ips = _page_slice_ips(IPv4Network('10.0.0.0/24'), page=1, page_size=5)

    assert ips == ['10.0.0.1', '10.0.0.2', '10.0.0.3', '10.0.0.4', '10.0.0.5']


def test_page_slice_ips_returns_last_page_partially_when_size_exceeds_remainder() -> None:
    """A page that runs past the last assignable address yields only the remaining IPs"""
    ips = _page_slice_ips(IPv4Network('10.0.0.0/30'), page=1, page_size=10)

    # /30 has 2 assignable addresses (.1, .2)
    assert ips == ['10.0.0.1', '10.0.0.2']


def test_page_slice_ips_returns_empty_when_start_offset_past_end() -> None:
    """Requesting a page past the assignable range yields an empty list"""
    ips = _page_slice_ips(IPv4Network('10.0.0.0/24'), page=100, page_size=50)

    assert ips == []


def test_page_slice_ips_includes_both_endpoints_for_slash_31() -> None:
    """/31 has 2 assignable hosts (RFC 3021 point-to-point — no network/broadcast reservation)"""
    ips = _page_slice_ips(IPv4Network('10.0.0.0/31'), page=1, page_size=5)

    assert ips == ['10.0.0.0', '10.0.0.1']


def test_page_slice_ips_returns_single_address_for_slash_32() -> None:
    """/32 has 1 assignable host (the network address itself, host-route policy)"""
    ips = _page_slice_ips(IPv4Network('10.0.0.5/32'), page=1, page_size=5)

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
    """The same address-skipping policy _page_slice_ips uses: /24 skips .0 and .255"""
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
#                                            _compose_assigned_row                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_assigned_row_pins_full_shape() -> None:
    """Output dict carries ip, status, type_info, assigned_to, mac_address, is_valid keys"""
    type_info = {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: 'Server',
        IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
    }
    assigned_to = {CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID, IpamOverviewKey.SUMMARY_LINE: 'Server: web01'}

    row = _compose_assigned_row(
        '10.0.0.5', type_info, assigned_to, 'aa:bb:cc:dd:ee:ff', is_valid=True,
    )

    assert row == {
        IpamOverviewKey.IP: '10.0.0.5',
        IpamOverviewKey.STATUS: IpamRowStatus.ASSIGNED,
        IpamOverviewKey.TYPE_INFO: type_info,
        IpamOverviewKey.ASSIGNED_TO: assigned_to,
        IpamOverviewKey.MAC_ADDRESS: 'aa:bb:cc:dd:ee:ff',
        IpamOverviewKey.IS_VALID: True,
    }


def test_compose_assigned_row_carries_is_valid_false_when_ip_outside_cidr() -> None:
    """A row built from an out-of-CIDR row carries is_valid=False so the FE can flag the conflict"""
    type_info = {CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID, IpamOverviewKey.LABEL: None,
                 IpamOverviewKey.CI_EXPLORER_COLOR: None}
    assigned_to = {CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID, IpamOverviewKey.SUMMARY_LINE: 'x'}

    row = _compose_assigned_row('10.0.0.5', type_info, assigned_to, None, is_valid=False)

    assert row[IpamOverviewKey.IS_VALID] is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _compose_free_row                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_free_row_pins_full_shape_with_nulled_assignment_fields() -> None:
    """Output dict carries ip, status='free', and nulled type_info/assigned_to/mac_address"""
    row = _compose_free_row('10.0.0.1')

    assert row == {
        IpamOverviewKey.IP: '10.0.0.1',
        IpamOverviewKey.STATUS: IpamRowStatus.FREE,
        IpamOverviewKey.TYPE_INFO: None,
        IpamOverviewKey.ASSIGNED_TO: None,
        IpamOverviewKey.MAC_ADDRESS: None,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _compose_ip_row                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_ip_row_returns_free_row_when_ip_not_in_assigned_map() -> None:
    """An IP absent from the assigned map yields the free-row shape; no summary lookup happens"""
    objects_manager = MagicMock()

    row = _compose_ip_row('10.0.0.1', assigned={}, type_meta={}, objects_manager=objects_manager)

    assert row[IpamOverviewKey.STATUS] == IpamRowStatus.FREE
    assert row[IpamOverviewKey.ASSIGNED_TO] is None
    objects_manager.get_summary_line.assert_not_called()


def test_compose_ip_row_returns_assigned_row_with_resolved_type_info_and_summary() -> None:
    """An IP present in the assigned map resolves summary line and type metadata into the row"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:ff')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    row = _compose_ip_row('10.0.0.1', assigned=assigned, type_meta=type_meta, objects_manager=objects_manager)

    assert row[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED
    assert row[IpamOverviewKey.ASSIGNED_TO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID,
        IpamOverviewKey.SUMMARY_LINE: 'Server: web01',
    }
    assert row[IpamOverviewKey.TYPE_INFO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: 'Server',
        IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
    }
    assert row[IpamOverviewKey.MAC_ADDRESS] == 'aa:bb:cc:dd:ee:ff'
    objects_manager.get_summary_line.assert_called_once_with(OWNER_OBJECT_ID, with_type=True)


def test_compose_ip_row_sets_type_info_to_none_when_type_id_is_none() -> None:
    """An assigned entry whose type_id is None yields type_info=None on the row"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, None, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    row = _compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, objects_manager=objects_manager)

    assert row[IpamOverviewKey.TYPE_INFO] is None


def test_compose_ip_row_sets_type_info_with_none_label_and_color_when_type_meta_missing() -> None:
    """An assigned entry whose type_id has no entry in type_meta still emits the type_info envelope"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    row = _compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, objects_manager=objects_manager)

    assert row[IpamOverviewKey.TYPE_INFO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: None,
        IpamOverviewKey.CI_EXPLORER_COLOR: None,
    }


def test_compose_ip_row_carries_none_mac_when_assigned_entry_lacks_mac() -> None:
    """A MAC value of None in the assigned entry surfaces as mac_address=None on the row"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    row = _compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, objects_manager=objects_manager)

    assert row[IpamOverviewKey.MAC_ADDRESS] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                       _resolve_assigned_summary_lines                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_assigned_summary_lines_returns_empty_for_no_assigned_candidates() -> None:
    """When no candidate IP is in the assigned map, no batch call is issued"""
    objects_manager = MagicMock()

    result = _resolve_assigned_summary_lines(
        ['10.0.0.1', '10.0.0.2'], assigned={}, objects_manager=objects_manager,
    )

    assert result == {}
    objects_manager.get_summary_lines_lookup.assert_not_called()


def test_resolve_assigned_summary_lines_maps_summary_to_each_assigned_ip() -> None:
    """An assigned candidate IP gets the resolved summary line keyed by its IP"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {
        OWNER_OBJECT_ID: 'Server: web01',
        OWNER_OBJECT_ID + 1: 'Server: web02',
    }

    result = _resolve_assigned_summary_lines(
        ['10.0.0.1', '10.0.0.5'], assigned=assigned, objects_manager=objects_manager,
    )

    assert result == {'10.0.0.1': 'Server: web01', '10.0.0.5': 'Server: web02'}


def test_resolve_assigned_summary_lines_skips_free_candidates() -> None:
    """Candidates not present in the assigned map are absent from the result"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    result = _resolve_assigned_summary_lines(
        ['10.0.0.1', '10.0.0.2'], assigned=assigned, objects_manager=objects_manager,
    )

    assert '10.0.0.2' not in result
    assert result == {'10.0.0.1': 'Server: web01'}


def test_resolve_assigned_summary_lines_omits_ip_when_owner_unresolvable() -> None:
    """Owner missing from the manager's lookup → IP absent from the result (treated as NULL)"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {}

    result = _resolve_assigned_summary_lines(
        ['10.0.0.1'], assigned=assigned, objects_manager=objects_manager,
    )

    assert result == {}


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
#                                            _resolve_candidate_ips                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_candidate_ips_returns_none_for_no_search_and_no_sort() -> None:
    """No search and no sort → None signals the lazy path"""
    network = IPv4Network('10.0.0.0/24')

    result = _resolve_candidate_ips(
        network, search='', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is None


def test_resolve_candidate_ips_returns_none_for_default_ip_asc_sort_with_no_search() -> None:
    """Default ip+asc with no search is equivalent to no sort - lazy path still applies"""
    network = IPv4Network('10.0.0.0/24')

    result = _resolve_candidate_ips(
        network, search='', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is None


def test_resolve_candidate_ips_returns_full_list_for_ip_desc_with_no_search() -> None:
    """Non-default sort forces materialization even without an active search"""
    network = IPv4Network('10.0.0.0/30')

    result = _resolve_candidate_ips(
        network, search='', sort_col=IpamSortColumn.IP, sort_dir=IpamSortDirection.DESC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result == ['10.0.0.2', '10.0.0.1']


def test_resolve_candidate_ips_filters_by_search_then_sorts() -> None:
    """Active search builds the matching list which is then sorted (search ∩ sort)"""
    network = IPv4Network('10.0.0.0/24')

    result = _resolve_candidate_ips(
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

    result = _resolve_candidate_ips(
        network, search='10.0.0.5', sort_col=None, sort_dir=IpamSortDirection.ASC,
        status_filter=None, type_filter=[],
        assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert result is not None
    assert all('10.0.0.5' in ip for ip in result)
    assert result[0] == '10.0.0.5'


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _extract_row_fields                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_row_fields_returns_full_triple_when_all_fields_present() -> None:
    """A row with subnet, ip and mac entries yields the full (subnet, ip, mac) tuple"""
    row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.5', mac='aa:bb:cc:dd:ee:ff')

    assert _extract_row_fields(row) == (SUBNET_OBJECT_ID, '10.0.0.5', 'aa:bb:cc:dd:ee:ff')


def test_extract_row_fields_returns_none_for_each_missing_field() -> None:
    """A row missing a given InterfaceField yields None for that slot"""
    row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip=None, mac=None)

    assert _extract_row_fields(row) == (SUBNET_OBJECT_ID, None, None)


def test_extract_row_fields_returns_ip_only_when_subnet_and_mac_absent() -> None:
    """A row carrying only an IP entry leaves subnet_ref and mac as None"""
    row = _make_interface_row(subnet_ref=None, ip='10.0.0.5', mac=None)

    assert _extract_row_fields(row) == (None, '10.0.0.5', None)


def test_extract_row_fields_returns_mac_only_when_subnet_and_ip_absent() -> None:
    """A row carrying only a MAC entry leaves subnet_ref and ip as None"""
    row = _make_interface_row(subnet_ref=None, ip=None, mac='aa:bb:cc:dd:ee:ff')

    assert _extract_row_fields(row) == (None, None, 'aa:bb:cc:dd:ee:ff')


def test_extract_row_fields_ignores_unrelated_field_entries() -> None:
    """Entries whose 'name' is not an InterfaceField member do not affect the extracted triple"""
    row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.5', mac=None, include_extras=True)

    assert _extract_row_fields(row) == (SUBNET_OBJECT_ID, '10.0.0.5', None)


def test_extract_row_fields_returns_none_triple_for_empty_data() -> None:
    """A row with an empty data list yields (None, None, None)"""
    assert _extract_row_fields({CmdbObjectMdsRowKey.DATA: []}) == (None, None, None)


def test_extract_row_fields_returns_none_triple_when_data_key_missing() -> None:
    """A row missing the 'data' key is treated as empty rather than raising"""
    assert _extract_row_fields({}) == (None, None, None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _compute_grid_dimensions                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_grid_dimensions_returns_zeros_for_zero_total() -> None:
    """A subnet with zero total addresses yields the zero layout (ranges=0, sectors=0, size=0)"""
    assert _compute_grid_dimensions(0) == (0, 0, 0)


def test_compute_grid_dimensions_emits_full_grid_for_slash_24() -> None:
    """/24 (256 addresses) → full 4 ranges × 16 sectors × 4 addresses per sector"""
    assert _compute_grid_dimensions(256) == (4, 16, 4)


def test_compute_grid_dimensions_emits_full_grid_for_slash_26() -> None:
    """/26 (64 addresses) → 4 ranges × 16 sectors × 1 address per sector (the minimum)"""
    assert _compute_grid_dimensions(64) == (4, 16, 1)


def test_compute_grid_dimensions_shrinks_sector_count_below_slash_26() -> None:
    """/27 (32 addresses) → 4 ranges × 8 sectors × 1 address per sector (sectors halve)"""
    assert _compute_grid_dimensions(32) == (4, 8, 1)


def test_compute_grid_dimensions_shrinks_to_one_by_one_for_single_address() -> None:
    """/32 (1 address) → 1 range × 1 sector × 1 address per sector"""
    assert _compute_grid_dimensions(1) == (1, 1, 1)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _bucket_used_counts                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_bucket_used_counts_returns_zero_filled_list_for_empty_assigned_map() -> None:
    """An empty assigned map produces a counts list of the requested length with all zeros"""
    counts = _bucket_used_counts({}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert counts == [0] * 64


def test_bucket_used_counts_returns_empty_list_when_total_cells_is_zero() -> None:
    """No cells → no counts (guard against division by zero downstream)"""
    counts = _bucket_used_counts({'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=0)

    assert counts == []


def test_bucket_used_counts_short_circuits_when_sector_size_is_zero() -> None:
    """Zero sector_size cannot index any cell; the helper returns the zero-filled list without raising"""
    counts = _bucket_used_counts({'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=0, total_cells=4)

    assert counts == [0, 0, 0, 0]


def test_bucket_used_counts_increments_correct_cell_for_assigned_ip() -> None:
    """An IP at offset 5 with sector_size=4 lands in cell index 1 (5 // 4)"""
    counts = _bucket_used_counts({'10.0.0.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert counts[1] == 1
    assert sum(counts) == 1


def test_bucket_used_counts_skips_ip_outside_the_subnet() -> None:
    """IPs whose offset falls outside the network's span are ignored"""
    counts = _bucket_used_counts({'192.168.1.5': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert sum(counts) == 0


def test_bucket_used_counts_skips_unparseable_ip_string() -> None:
    """An ip_str that parse_ipv4 cannot parse is skipped without raising"""
    counts = _bucket_used_counts(
        {'not-an-ip': {}}, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64,
    )

    assert sum(counts) == 0


def test_bucket_used_counts_distributes_multiple_assigned_ips_across_cells() -> None:
    """Multiple IPs land in distinct cells when their offsets are in different sector_size groups"""
    assigned = {'10.0.0.1': {}, '10.0.0.5': {}, '10.0.0.9': {}}

    counts = _bucket_used_counts(assigned, IPv4Network('10.0.0.0/24'), sector_size=4, total_cells=64)

    assert counts[0] == 1
    assert counts[1] == 1
    assert counts[2] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _compose_sector                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_sector_emits_full_shape_and_rounds_percentage_to_two_decimals() -> None:
    """Output pins ip_start/ip_end/used_count/percentage; percentage rounded to 2 decimals"""
    first_int = int(IPv4Address('10.0.0.0'))

    sector = _compose_sector(first_int, sector_size=4, used_count=1)

    assert sector == {
        IpamOverviewKey.IP_START: '10.0.0.0',
        IpamOverviewKey.IP_END: '10.0.0.3',
        IpamOverviewKey.USED_COUNT: 1,
        IpamOverviewKey.PERCENTAGE: 25.0,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _build_ip_distribution                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_ip_distribution_returns_empty_dict_when_network_is_none() -> None:
    """A missing/unparsable subnet network → grid suppressed (empty dict)"""
    assert _build_ip_distribution(None, {}) == {}


def test_build_ip_distribution_returns_empty_dict_when_subnet_too_small_for_full_grid() -> None:
    """/27 (32 addresses → 4×8 cells) is below the full 4×16 = 64-cell cap and is suppressed"""
    assert _build_ip_distribution(IPv4Network('10.0.0.0/27'), {}) == {}


def test_build_ip_distribution_emits_full_grid_for_slash_24() -> None:
    """A /24 yields the full grid: sector_size=4, 4 ranges, each with 16 sectors"""
    grid = _build_ip_distribution(IPv4Network('10.0.0.0/24'), {})

    assert grid[IpamOverviewKey.SECTOR_SIZE] == 4
    assert len(grid[IpamOverviewKey.RANGES]) == 4
    for range_block in grid[IpamOverviewKey.RANGES]:
        assert len(range_block[IpamOverviewKey.SECTORS]) == 16


def test_build_ip_distribution_reflects_assigned_counts_in_correct_cells() -> None:
    """An assigned IP appears in its sector's used_count and not in others"""
    assigned: dict[str, dict[str, Any]] = {'10.0.0.5': {}}

    grid = _build_ip_distribution(IPv4Network('10.0.0.0/24'), assigned)

    # Sector index 1 of range 0 covers 10.0.0.4-10.0.0.7
    first_range = grid[IpamOverviewKey.RANGES][0]
    assert first_range[IpamOverviewKey.SECTORS][1][IpamOverviewKey.USED_COUNT] == 1
    assert first_range[IpamOverviewKey.SECTORS][0][IpamOverviewKey.USED_COUNT] == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _build_type_distribution                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_type_distribution_returns_empty_list_when_total_is_zero() -> None:
    """Zero assignable addresses (e.g. unparsable CIDR) → empty distribution"""
    assert _build_type_distribution({}, {}, total=0) == []


def test_build_type_distribution_emits_single_type_bucket_plus_free() -> None:
    """One type covering all assigned IPs → 1 type bucket + Free bucket"""
    assigned = {
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}

    distribution = _build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert labels == ['Server', IpamBucketLabel.FREE]


def test_build_type_distribution_emits_unknown_bucket_for_orphaned_type_ids() -> None:
    """Assigned rows whose type_id is absent from type_meta are routed to Unknown"""
    assigned = {
        '10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),  # resolvable
        '10.0.0.6': _make_assigned_entry(OWNER_OBJECT_ID, 999, None),             # orphan
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = _build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert labels == ['Server', IpamBucketLabel.UNKNOWN, IpamBucketLabel.FREE]


def test_build_type_distribution_routes_non_int_type_id_to_unknown_bucket() -> None:
    """A None/non-int type_id on an assigned row falls into the Unknown bucket"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, None, None)}

    distribution = _build_type_distribution(assigned, {}, total=10)

    unknown = next(b for b in distribution if b[IpamOverviewKey.LABEL] == IpamBucketLabel.UNKNOWN)
    assert unknown[IpamOverviewKey.COUNT] == 1


def test_build_type_distribution_omits_unknown_bucket_when_empty() -> None:
    """When every assigned row resolves to a known type, no Unknown bucket appears"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = _build_type_distribution(assigned, type_meta, total=10)

    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert IpamBucketLabel.UNKNOWN not in labels


def test_build_type_distribution_computes_percentages_against_total() -> None:
    """Percentages are computed against the supplied total and rounded to 2 decimals"""
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = _build_type_distribution(assigned, type_meta, total=100)

    by_label = {b[IpamOverviewKey.LABEL]: b for b in distribution}
    assert by_label['Server'][IpamOverviewKey.PERCENTAGE] == 1.0
    assert by_label[IpamBucketLabel.FREE][IpamOverviewKey.PERCENTAGE] == 99.0


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _load_subnet_object                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_subnet_object_aborts_400_when_subnet_cmdbtype_not_defined() -> None:
    """No SUBNET CmdbType → HTTP 400; no object query is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        _load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400
    objects_manager.find_objects.assert_not_called()


def test_load_subnet_object_aborts_404_when_object_not_found() -> None:
    """find_objects returns empty → HTTP 404"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        _load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_load_subnet_object_aborts_400_when_object_is_not_a_subnet() -> None:
    """Found object exists but has a different type_id → HTTP 400"""
    wrong_type_doc = _make_cmdb_object(SUBNET_OBJECT_ID, type_id=SUBNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        _load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_load_subnet_object_returns_candidate_on_happy_path() -> None:
    """A correct SUBNET object id returns the loaded doc with the expected filter"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [subnet_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = _load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert result is subnet_doc
    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID}, as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _load_assigned_rows_map                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_assigned_rows_map_returns_empty_when_no_objects_match() -> None:
    """No interface rows in the system → empty map"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_indexes_matching_rows_by_canonical_ip() -> None:
    """Each in-range matching row contributes one entry keyed by its parsed IP, tagged is_valid=True"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID, '10.0.0.5', 'aa:bb:cc:dd:ee:ff')],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {
        '10.0.0.5': {
            _AssignedField.OBJECT_ID: OWNER_OBJECT_ID,
            _AssignedField.TYPE_ID: OWNER_TYPE_ID,
            _AssignedField.MAC: 'aa:bb:cc:dd:ee:ff',
            _AssignedField.IS_VALID: True,
        },
    }


def test_load_assigned_rows_map_sets_mac_to_none_when_field_is_empty_string() -> None:
    """An empty-string MAC is normalized to None in the map entry"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID, '10.0.0.5', '')],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result['10.0.0.5'][_AssignedField.MAC] is None


def test_load_assigned_rows_map_skips_rows_referencing_a_different_subnet() -> None:
    """Rows whose subnet_ref doesn't match the target subnet are filtered out"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID + 1, '10.0.0.5', None)],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_skips_rows_with_unparseable_ip() -> None:
    """Rows whose IP cannot be parsed as canonical dotted-quad are skipped"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID, 'not-an-ip', None)],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


def test_load_assigned_rows_map_keeps_out_of_range_rows_tagged_is_valid_false() -> None:
    """Rows with IPs outside the given network are kept and tagged is_valid=False as conflicts"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID, '192.168.1.5', None)],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result['192.168.1.5'][_AssignedField.IS_VALID] is False
    assert result['192.168.1.5'][_AssignedField.OBJECT_ID] == OWNER_OBJECT_ID


def test_load_assigned_rows_map_uses_nested_elem_match_filter() -> None:
    """Mongo filter pins multi_data_sections → values → data $elemMatch chain on the subnet ref"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

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
                                    CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID,
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
#                                              _resolve_type_meta                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_type_meta_returns_empty_dict_for_empty_type_ids() -> None:
    """Empty input → empty result; the bulk-lookup endpoint is not invoked"""
    types_manager = MagicMock()

    result = _resolve_type_meta(types_manager, [])

    assert result == {}
    types_manager.get_types_lookup.assert_not_called()


def test_resolve_type_meta_deduplicates_input_ids_before_lookup() -> None:
    """Duplicates are collapsed via set() so the bulk-lookup endpoint gets each id once"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}

    _resolve_type_meta(types_manager, [OWNER_TYPE_ID, OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID])

    [unique_ids] = types_manager.get_types_lookup.call_args.args
    assert set(unique_ids) == {OWNER_TYPE_ID, OTHER_OWNER_TYPE_ID}


def test_resolve_type_meta_projects_to_label_and_ci_explorer_color() -> None:
    """Each resolved CmdbType is projected to {LABEL, CI_EXPLORER_COLOR} from its attributes"""
    server_type = MagicMock(label='Server', ci_explorer_color='#FF0000')
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {OWNER_TYPE_ID: server_type}

    result = _resolve_type_meta(types_manager, [OWNER_TYPE_ID])

    assert result == {
        OWNER_TYPE_ID: {
            IpamOverviewKey.LABEL: 'Server',
            IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
        },
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _build_ips_block                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_ips_block_uses_lazy_path_when_candidates_is_none() -> None:
    """candidates=None → ips.total equals assignable; rows come from the lazy IP slice"""
    network = IPv4Network('10.0.0.0/24')

    block = _build_ips_block(
        network, assignable=254, page=1, page_size=5,
        candidates=None, assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert block[IpamOverviewKey.TOTAL] == 254
    assert len(block[IpamOverviewKey.ROWS]) == 5
    assert block[IpamOverviewKey.ROWS][0][IpamOverviewKey.IP] == '10.0.0.1'


def test_build_ips_block_paginates_candidate_list_when_provided() -> None:
    """Non-None candidates list → ips.total equals len(candidates); rows are the page slice"""
    network = IPv4Network('10.0.0.0/24')
    candidates = ['10.0.0.5', '10.0.0.50', '10.0.0.51', '10.0.0.52']

    block = _build_ips_block(
        network, assignable=254, page=1, page_size=2,
        candidates=candidates, assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert block[IpamOverviewKey.TOTAL] == 4
    assert [r[IpamOverviewKey.IP] for r in block[IpamOverviewKey.ROWS]] == ['10.0.0.5', '10.0.0.50']


def test_build_ips_block_returns_empty_rows_when_candidates_list_is_empty() -> None:
    """An empty candidates list yields total=0 and an empty rows list"""
    network = IPv4Network('10.0.0.0/24')

    block = _build_ips_block(
        network, assignable=254, page=1, page_size=10,
        candidates=[], assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert block[IpamOverviewKey.TOTAL] == 0
    assert block[IpamOverviewKey.ROWS] == []


def test_build_ips_block_preserves_candidate_order_in_rows() -> None:
    """The rows on the page mirror the candidates list order verbatim (no re-sorting)"""
    network = IPv4Network('10.0.0.0/24')
    candidates = ['10.0.0.10', '10.0.0.1', '10.0.0.42']

    block = _build_ips_block(
        network, assignable=254, page=1, page_size=10,
        candidates=candidates, assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert [r[IpamOverviewKey.IP] for r in block[IpamOverviewKey.ROWS]] == candidates


def test_build_ips_block_shapes_assigned_rows_through_compose_ip_row() -> None:
    """An assigned IP on the page is shaped via _compose_ip_row (status='assigned', summary set)"""
    network = IPv4Network('10.0.0.0/24')
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    block = _build_ips_block(
        network, assignable=254, page=1, page_size=1,
        candidates=None, assigned=assigned, type_meta=type_meta, objects_manager=objects_manager,
    )

    [first_row] = block[IpamOverviewKey.ROWS]
    assert first_row[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED
    assert first_row[IpamOverviewKey.ASSIGNED_TO][IpamOverviewKey.SUMMARY_LINE] == 'Server: web01'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _parse_subnet_network                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_subnet_network_returns_ipv4network_for_valid_cidr() -> None:
    """A canonical CIDR string parses to the corresponding IPv4Network"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    result = _parse_subnet_network(doc)

    assert isinstance(result, IPv4Network)
    assert str(result) == SUBNET_RANGE


def test_parse_subnet_network_returns_none_when_field_missing() -> None:
    """A subnet doc without the network-range field yields None"""
    doc = _make_cmdb_object(SUBNET_OBJECT_ID, SUBNET_TYPE_ID, fields=[])

    assert _parse_subnet_network(doc) is None


def test_parse_subnet_network_returns_none_for_non_string_value() -> None:
    """A network-range field carrying a non-string value (e.g. None) yields None"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range=None)

    assert _parse_subnet_network(doc) is None


def test_parse_subnet_network_returns_none_for_unparsable_string() -> None:
    """A garbled CIDR string yields None rather than raising"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='not-a-cidr')

    assert _parse_subnet_network(doc) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _build_broken_state_payload                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_broken_state_payload_returns_full_envelope_key_set() -> None:
    """Degenerate payload still ships every top-level key the FE expects"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    payload = _build_broken_state_payload(doc, page=1, page_size=10)

    assert set(payload.keys()) == {
        IpamOverviewKey.SUBNET,
        IpamOverviewKey.IPS,
        IpamOverviewKey.TYPE_DISTRIBUTION,
        IpamOverviewKey.IP_DISTRIBUTION,
        IpamOverviewKey.VLANS,
        IpamOverviewKey.INVALID_COUNT,
    }
    assert payload[IpamOverviewKey.INVALID_COUNT] == 0


def test_build_broken_state_payload_zeroes_kpi_counters() -> None:
    """All counters are zeroed when the CIDR is broken"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    payload = _build_broken_state_payload(doc, page=1, page_size=10)

    subnet_block = payload[IpamOverviewKey.SUBNET]
    assert subnet_block[IpamOverviewKey.TOTAL_IPS] == 0
    assert subnet_block[IpamOverviewKey.ASSIGNABLE_IPS] == 0
    assert subnet_block[IpamOverviewKey.USED_IPS] == 0
    assert subnet_block[IpamOverviewKey.FREE_IPS] == 0


def test_build_broken_state_payload_echoes_raw_cidr_string_back() -> None:
    """The raw CIDR string is echoed under 'cidr' so the FE shows the broken input"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    payload = _build_broken_state_payload(doc, page=1, page_size=10)

    assert payload[IpamOverviewKey.SUBNET][IpamOverviewKey.CIDR] == 'not-a-cidr'


def test_build_broken_state_payload_emits_null_cidr_for_non_string_value() -> None:
    """A non-string field value becomes cidr=None on the wire"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, None)

    payload = _build_broken_state_payload(doc, page=1, page_size=10)

    assert payload[IpamOverviewKey.SUBNET][IpamOverviewKey.CIDR] is None


def test_build_broken_state_payload_emits_empty_ips_block_and_distributions() -> None:
    """Empty rows / total=0 / empty distributions so the FE can render unconditionally"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    payload = _build_broken_state_payload(doc, page=1, page_size=10)

    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 0
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.TYPE_DISTRIBUTION] == []
    assert payload[IpamOverviewKey.IP_DISTRIBUTION] == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_subnet_overview                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_overview_propagates_load_subnet_aborts() -> None:
    """An abort raised by _load_subnet_object propagates out of the orchestrator"""
    with patch(f'{PATH}._load_subnet_object', side_effect=NotFound('not found')), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_build_subnet_overview_returns_degenerate_payload_when_cidr_unparsable() -> None:
    """A subnet whose network range is unparsable yields zeroed counters and an empty page"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    subnet_block = payload[IpamOverviewKey.SUBNET]
    assert subnet_block[IpamOverviewKey.CIDR] == 'not-a-cidr'
    assert subnet_block[IpamOverviewKey.TOTAL_IPS] == 0
    assert subnet_block[IpamOverviewKey.ASSIGNABLE_IPS] == 0
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.TYPE_DISTRIBUTION] == []
    assert payload[IpamOverviewKey.IP_DISTRIBUTION] == {}
    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_omits_ip_range_from_subnet_block() -> None:
    """The subnet block no longer carries an ip_range key (removed; supernet keeps it)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert IpamOverviewKey.IP_RANGE not in payload[IpamOverviewKey.SUBNET]


def test_build_subnet_overview_emits_full_payload_envelope_on_happy_path() -> None:
    """Happy path payload carries subnet summary / ips / type_distribution / ip_distribution / vlans"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert set(payload.keys()) == {
        IpamOverviewKey.SUBNET,
        IpamOverviewKey.IPS,
        IpamOverviewKey.TYPE_DISTRIBUTION,
        IpamOverviewKey.IP_DISTRIBUTION,
        IpamOverviewKey.VLANS,
        IpamOverviewKey.INVALID_COUNT,
    }


def test_build_subnet_overview_composes_assigned_row_with_resolved_type_and_summary() -> None:
    """An IP with an assigned row produces a row carrying its resolved type_info / assigned_to"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:ff')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}

    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=1)

    [first_row] = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert first_row[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED
    assert first_row[IpamOverviewKey.ASSIGNED_TO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID,
        IpamOverviewKey.SUMMARY_LINE: 'Server: web01',
    }
    assert first_row[IpamOverviewKey.TYPE_INFO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: 'Server',
        IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
    }
    assert first_row[IpamOverviewKey.MAC_ADDRESS] == 'aa:bb:cc:dd:ee:ff'


def test_build_subnet_overview_total_equals_assignable_for_paginated_ip_table() -> None:
    """ips.total matches subnet.assignable_ips so the table paginates only assignable rows"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=5)

    assert (
        payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL]
        == payload[IpamOverviewKey.SUBNET][IpamOverviewKey.ASSIGNABLE_IPS]
    )


def test_build_subnet_overview_search_filters_ips_total_below_assignable() -> None:
    """Active search shrinks ips.total to the match count; assignable_ips stays the full count"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=50, search='10.0.0.5',
        )

    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] < payload[
        IpamOverviewKey.SUBNET
    ][IpamOverviewKey.ASSIGNABLE_IPS]
    assert all('10.0.0.5' in row[IpamOverviewKey.IP]
               for row in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS])


def test_build_subnet_overview_kpi_block_is_invariant_under_search() -> None:
    """KPI counters (total / assignable / used / free) are unaffected by an active search"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        no_search = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)
        with_search = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, search='10.0.0.5',
        )

    assert no_search[IpamOverviewKey.SUBNET] == with_search[IpamOverviewKey.SUBNET]


def test_build_subnet_overview_distributions_are_invariant_under_search() -> None:
    """type_distribution and ip_distribution are computed over the whole subnet, not the search match"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}

    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta):
        no_search = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        with_search = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, search='10.0.0.5',
        )

    assert no_search[IpamOverviewKey.TYPE_DISTRIBUTION] == with_search[IpamOverviewKey.TYPE_DISTRIBUTION]
    assert no_search[IpamOverviewKey.IP_DISTRIBUTION] == with_search[IpamOverviewKey.IP_DISTRIBUTION]


def test_build_subnet_overview_search_below_min_length_is_treated_as_no_search() -> None:
    """A 1-char query (below MIN_QUERY_LENGTH) restores the full assignable-range table"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=5, search='1',
        )

    assert (
        payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL]
        == payload[IpamOverviewKey.SUBNET][IpamOverviewKey.ASSIGNABLE_IPS]
    )


def test_build_subnet_overview_aborts_400_on_unknown_sort_column() -> None:
    """An invalid ?sort= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='foo')

    assert exc_info.value.code == 400


def test_build_subnet_overview_aborts_400_on_unknown_sort_direction() -> None:
    """An invalid ?order= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='ip', order='sideways')

    assert exc_info.value.code == 400


def test_build_subnet_overview_sorts_rows_by_ip_descending_when_order_desc() -> None:
    """sort=ip & order=desc reverses the natural ascending order on the page"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=3, sort='ip', order='-1',
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in rows] == ['10.0.0.254', '10.0.0.253', '10.0.0.252']


def test_build_subnet_overview_sort_default_ip_asc_uses_lazy_path() -> None:
    """sort=ip + no order keeps the lazy ascending IP path (ips.total == assignable)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=3, sort='ip',
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in rows] == ['10.0.0.1', '10.0.0.2', '10.0.0.3']
    assert (
        payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL]
        == payload[IpamOverviewKey.SUBNET][IpamOverviewKey.ASSIGNABLE_IPS]
    )


def test_build_subnet_overview_kpi_block_is_invariant_under_sort() -> None:
    """KPI counters are unaffected by sort direction"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        unsorted = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)
        sorted_desc = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='ip', order='-1',
        )

    assert unsorted[IpamOverviewKey.SUBNET] == sorted_desc[IpamOverviewKey.SUBNET]


def test_build_subnet_overview_distributions_are_invariant_under_sort() -> None:
    """type_distribution and ip_distribution cover the whole subnet, unaffected by sort"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta):
        no_sort = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        with_sort = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, sort='type', order='-1',
        )

    assert no_sort[IpamOverviewKey.TYPE_DISTRIBUTION] == with_sort[IpamOverviewKey.TYPE_DISTRIBUTION]
    assert no_sort[IpamOverviewKey.IP_DISTRIBUTION] == with_sort[IpamOverviewKey.IP_DISTRIBUTION]


def test_build_subnet_overview_sort_assigned_to_calls_summary_batch_when_any_assigned() -> None:
    """sort=assigned_to triggers the batch summary-line fetch on the ObjectsManager"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, sort='assigned_to',
        )

    objects_manager.get_summary_lines_lookup.assert_called_once()


def test_build_subnet_overview_sort_combines_with_search() -> None:
    """search + sort: matching IPs are filtered first, then ordered by the chosen column"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=50, search='10.0.0.5', sort='ip', order='-1',
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    ips = [r[IpamOverviewKey.IP] for r in rows]

    assert all('10.0.0.5' in ip for ip in ips)
    assert ips == sorted(ips, key=lambda ip: int(IPv4Address(ip)), reverse=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_subnet_overview - vlans                                             #
# -------------------------------------------------------------------------------------------------------------------- #
VLAN_OBJECT_ID_X: int = 501
VLAN_OBJECT_ID_Y: int = 502
VLAN_NAME_X: str = 'VLAN-X'
VLAN_NAME_Y: str = 'VLAN-Y'


def test_build_subnet_overview_vlans_carries_referenced_vlans_for_this_subnet() -> None:
    """The top-level 'vlans' list carries the bucket the lifted helper returns for this subnet"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    vlan_bucket = [
        {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X},
        {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y},
    ]

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={SUBNET_OBJECT_ID: vlan_bucket}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == vlan_bucket


def test_build_subnet_overview_vlans_is_empty_list_when_no_vlan_references_subnet() -> None:
    """No bucket for this subnet → empty list (not missing key, so FE can iterate unconditionally)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_invokes_vlan_helper_with_single_subnet_id_list() -> None:
    """The orchestrator queries the VLAN helper with exactly [public_id]"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}) as vlan_loader:
        build_subnet_overview(objects_manager, types_manager, SUBNET_OBJECT_ID)

    vlan_loader.assert_called_once_with(objects_manager, types_manager, [SUBNET_OBJECT_ID])


def test_build_subnet_overview_vlans_is_empty_list_on_degenerate_cidr_path() -> None:
    """Broken-state payload (unparsable CIDR) carries an empty vlans list, mirroring the happy-path envelope"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_vlans_is_invariant_under_search_and_sort() -> None:
    """The 'vlans' list covers the whole subnet, unaffected by search / sort query params"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    vlan_bucket = [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}]

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={SUBNET_OBJECT_ID: vlan_bucket}):
        unsorted = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)
        searched = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, search='10.0.0.5',
        )
        sorted_desc = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='ip', order='-1',
        )

    assert unsorted[IpamOverviewKey.VLANS] == vlan_bucket
    assert searched[IpamOverviewKey.VLANS] == vlan_bucket
    assert sorted_desc[IpamOverviewKey.VLANS] == vlan_bucket


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_subnet_overview - filters                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_overview_status_assigned_narrows_rows_to_assigned_ips_only() -> None:
    """?status=assigned narrows ips.rows to assigned IPs and shrinks ips.total to match"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, status='assigned',
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in rows] == ['10.0.0.1']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 1


def test_build_subnet_overview_status_free_drops_assigned_rows() -> None:
    """?status=free narrows ips.rows to free IPs and excludes assigned ones"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=500, status='free',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert '10.0.0.1' not in ips
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 253


def test_build_subnet_overview_type_filter_narrows_to_matching_type_only() -> None:
    """?type=X narrows ips.rows to assigned rows of that owning type"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
    }
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, type_filter=str(OWNER_TYPE_ID),
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in rows] == ['10.0.0.1']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 1


def test_build_subnet_overview_status_free_combined_with_type_is_empty() -> None:
    """?status=free&type=X yields an empty page since free rows have no owner type"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID,
            status='free', type_filter=str(OWNER_TYPE_ID),
        )

    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 0


def test_build_subnet_overview_kpi_block_is_invariant_under_filter() -> None:
    """KPI counters cover the whole subnet, unaffected by status / type filters"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        no_filter = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        with_filter = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, status='assigned',
        )

    assert no_filter[IpamOverviewKey.SUBNET] == with_filter[IpamOverviewKey.SUBNET]


def test_build_subnet_overview_distributions_and_vlans_invariant_under_filter() -> None:
    """type_distribution / ip_distribution / vlans cover the whole subnet, unaffected by filter"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        no_filter = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        with_filter = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, status='free',
        )

    assert no_filter[IpamOverviewKey.TYPE_DISTRIBUTION] == with_filter[IpamOverviewKey.TYPE_DISTRIBUTION]
    assert no_filter[IpamOverviewKey.IP_DISTRIBUTION] == with_filter[IpamOverviewKey.IP_DISTRIBUTION]
    assert no_filter[IpamOverviewKey.VLANS] == with_filter[IpamOverviewKey.VLANS]


def test_build_subnet_overview_filter_combines_with_search() -> None:
    """search + filter: substring match is intersected with the status/type filter"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=50, search='10.0.0.5', status='assigned',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['10.0.0.5']


def test_build_subnet_overview_aborts_400_on_unknown_status_filter() -> None:
    """An invalid ?status= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, status='partial')

    assert exc_info.value.code == 400


def test_build_subnet_overview_aborts_400_on_non_integer_type_filter() -> None:
    """An invalid ?type= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, type_filter='Server')

    assert exc_info.value.code == 400


def test_build_subnet_overview_multi_value_type_filter_keeps_all_listed_types() -> None:
    """?type=A,B keeps assigned rows whose owner type is in the set (OR within type filter)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OTHER_OWNER_TYPE_ID, None),
        '10.0.0.3': _make_assigned_entry(OWNER_OBJECT_ID + 2, 9_999, None),
    }
    type_meta = {
        OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        OTHER_OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Printer', IpamOverviewKey.CI_EXPLORER_COLOR: None},
        9_999: {IpamOverviewKey.LABEL: 'Router', IpamOverviewKey.CI_EXPLORER_COLOR: None},
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'summary'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value=type_meta):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            type_filter=f'{OWNER_TYPE_ID},{OTHER_OWNER_TYPE_ID}',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['10.0.0.1', '10.0.0.2']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _sorted_invalid_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_sorted_invalid_ips_returns_empty_when_all_rows_are_valid() -> None:
    """An assigned map with no invalid rows yields an empty list (steady-state)"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None),
    }

    assert _sorted_invalid_ips(assigned) == []


def test_sorted_invalid_ips_returns_invalid_ips_in_ascending_ip_order() -> None:
    """Invalid rows are returned sorted by integer IP value (not lexicographic)"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.10': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
        '192.168.1.2':  _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None, is_valid=False),
    }

    assert _sorted_invalid_ips(assigned) == ['192.168.1.2', '192.168.1.10']


# -------------------------------------------------------------------------------------------------------------------- #
#                                _build_type_distribution - validity exclusion                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_type_distribution_excludes_invalid_rows_from_type_counts() -> None:
    """Invalid (out-of-CIDR) rows do not contribute to any type bucket - percentages stay bounded"""
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    distribution = _build_type_distribution(assigned, type_meta, total=254)

    server_bucket = next(b for b in distribution if b[CmdbObjectKey.PUBLIC_ID] == OWNER_TYPE_ID)
    free_bucket = next(b for b in distribution if b[IpamOverviewKey.LABEL] == IpamBucketLabel.FREE)
    assert server_bucket[IpamOverviewKey.COUNT] == 1
    assert free_bucket[IpamOverviewKey.COUNT] == 253


# -------------------------------------------------------------------------------------------------------------------- #
#                                       build_subnet_overview - invalid handling                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_overview_used_ips_counts_valid_plus_invalid() -> None:
    """KPI used_ips includes both in-range and out-of-range rows referencing this subnet"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    subnet_block = payload[IpamOverviewKey.SUBNET]
    assert subnet_block[IpamOverviewKey.USED_IPS] == 2
    assert subnet_block[IpamOverviewKey.FREE_IPS] == 253


def test_build_subnet_overview_carries_invalid_count_top_level() -> None:
    """The top-level invalid_count equals the number of out-of-CIDR rows"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
        '192.168.1.6': _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.INVALID_COUNT] == 2


def test_build_subnet_overview_appends_invalid_rows_after_assignable_in_default_order() -> None:
    """Default (no sort) order shows assignable IPs first, then invalid IPs trailing"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=500,
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    # 254 assignable IPs + 1 invalid trailing
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 255
    assert rows[0][IpamOverviewKey.IP] == '10.0.0.1'
    assert rows[-1][IpamOverviewKey.IP] == '192.168.1.5'
    assert rows[-1][IpamOverviewKey.IS_VALID] is False


def test_build_subnet_overview_assigned_rows_carry_is_valid_true_when_in_cidr() -> None:
    """In-range assigned rows carry is_valid=True so the FE can distinguish them from conflicts"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=1,
        )

    [first_row] = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert first_row[IpamOverviewKey.IS_VALID] is True


def test_build_subnet_overview_search_matches_invalid_ips_too() -> None:
    """An active search filters both assignable and invalid IPs by substring"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=50, search='192.168',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['192.168.1.5']


# -------------------------------------------------------------------------------------------------------------------- #
#                                       build_invalid_subnet_overview                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_invalid_subnet_overview_emits_same_envelope_keys() -> None:
    """Same top-level key set as the main overview"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_invalid_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert set(payload.keys()) == {
        IpamOverviewKey.SUBNET,
        IpamOverviewKey.IPS,
        IpamOverviewKey.TYPE_DISTRIBUTION,
        IpamOverviewKey.IP_DISTRIBUTION,
        IpamOverviewKey.VLANS,
        IpamOverviewKey.INVALID_COUNT,
    }


def test_build_invalid_subnet_overview_returns_only_invalid_rows() -> None:
    """ips.rows contains only out-of-CIDR rows; in-range assigned rows are excluded"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1':   _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
        '172.16.0.9':  _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_invalid_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    ips = [r[IpamOverviewKey.IP] for r in rows]
    assert ips == ['172.16.0.9', '192.168.1.5']
    assert all(r[IpamOverviewKey.IS_VALID] is False for r in rows)
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 2


def test_build_invalid_subnet_overview_kpi_block_matches_main_view() -> None:
    """KPI block covers the whole subnet, same shape as the main overview"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1':   _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        main_payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        invalid_payload = build_invalid_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert main_payload[IpamOverviewKey.SUBNET] == invalid_payload[IpamOverviewKey.SUBNET]
    assert main_payload[IpamOverviewKey.INVALID_COUNT] == invalid_payload[IpamOverviewKey.INVALID_COUNT]


def test_build_invalid_subnet_overview_search_filters_invalid_rows() -> None:
    """search narrows ips.rows / ips.total but leaves invalid_count covering the whole subnet"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
        '172.16.0.9':  _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'x'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_invalid_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, search='192.168',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['192.168.1.5']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 1
    assert payload[IpamOverviewKey.INVALID_COUNT] == 2


def test_build_invalid_subnet_overview_returns_degenerate_payload_when_cidr_unparsable() -> None:
    """Broken CIDR yields the degenerate envelope (mirrors build_subnet_overview)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc):
        payload = build_invalid_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.INVALID_COUNT] == 0
