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
Unit tests for cmdb.framework.ipam.subnet_export

Covers the IP-range cell formatting, the per-row mapping to export cells, and the full CSV build:
the rows are stubbed (load_subnet_usage_rows / build_subnet_ip_export_rows are patched) and the
produced CSV bytes are read back with the csv module to assert the header row and data rows. CSV is
text, so numeric cells round-trip as their string form (and large IPv6 counts keep full precision).

The supernet export's reads are pinned too: the supernet is read once and its family taken from that
document, the read scope reaches both reads, no VLAN query runs (the real row loader is exercised with
its DB helpers patched), and there is no row limit - more rows than the subnet IP export allows are
all written.
"""
import csv
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamExport,
    IpamSubnetIpsExport,
    IpamRowStatus,
    IpAddressFamily,
    SubnetField,
)
from cmdb.models.object_model import CmdbObjectKey
from cmdb.framework.ipam.subnet_export import (
    _format_ip_range,
    _subnet_export_row,
    _subnet_ip_export_row,
    build_supernet_subnets_csv,
    build_subnet_ips_csv,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.framework.ipam.subnet_export'
OVERVIEW_MODULE: str = 'cmdb.framework.ipam.supernet_overview'

SUPERNET_PUBLIC_ID: int = 42
SUBNET_TYPE_ID: int = 11
SUBNET_PUBLIC_ID_A: int = 201
SUBNET_PUBLIC_ID_B: int = 202
SUBNET_RANGE_A: str = '10.0.0.0/24'
SUBNET_RANGE_B: str = '10.0.1.0/24'
USED_IPS_A: int = 3
USED_IPS_B: int = 9
DENIED_TYPE_IDS: list[int] = [7]
SUPERNET_DOC: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID: SUPERNET_PUBLIC_ID}

ROW_A: dict[str, Any] = {
    IpamOverviewKey.CIDR: '10.0.0.0/24',
    IpamOverviewKey.IP_RANGE: {IpamOverviewKey.FIRST: '10.0.0.0', IpamOverviewKey.LAST: '10.0.0.255'},
    IpamOverviewKey.USED_IPS: 3,
    IpamOverviewKey.FREE_IPS: 253,
    IpamOverviewKey.USAGE_PERCENT: 1.17,
}
ROW_DEGENERATE: dict[str, Any] = {
    IpamOverviewKey.CIDR: 'not-a-cidr',
    IpamOverviewKey.IP_RANGE: None,
    IpamOverviewKey.USED_IPS: 0,
    IpamOverviewKey.FREE_IPS: 0,
    IpamOverviewKey.USAGE_PERCENT: 0.0,
}


def _read_csv(content: bytes) -> list[list[str]]:
    """Decodes CSV export bytes and returns the parsed rows (each a list of string cells)."""
    return list(csv.reader(StringIO(content.decode('utf-8'))))


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _format_ip_range                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_format_ip_range_joins_first_and_last() -> None:
    """A populated range renders as 'first - last'"""
    rendered: str = _format_ip_range({IpamOverviewKey.FIRST: '10.0.0.0', IpamOverviewKey.LAST: '10.0.0.255'})

    assert rendered == '10.0.0.0 - 10.0.0.255'


def test_format_ip_range_returns_empty_for_missing_range() -> None:
    """A None / empty range renders as an empty string"""
    assert _format_ip_range(None) == ''
    assert _format_ip_range({}) == ''

# -------------------------------------------------------------------------------------------------------------------- #
#                                             _subnet_export_row                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_subnet_export_row_includes_usage_for_ipv4() -> None:
    """With include_usage=True the row carries the trailing usage-percent cell (IPv4 export)"""
    assert _subnet_export_row(ROW_A, include_usage=True) == ['10.0.0.0/24', '10.0.0.0 - 10.0.0.255', 3, 253, 1.17]


def test_subnet_export_row_omits_usage_for_ipv6() -> None:
    """With include_usage=False the row stops at free_ips (IPv6 export drops the usage column)"""
    assert _subnet_export_row(ROW_A, include_usage=False) == ['10.0.0.0/24', '10.0.0.0 - 10.0.0.255', 3, 253]

# -------------------------------------------------------------------------------------------------------------------- #
#                                        build_supernet_subnets_csv                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_supernet_subnets_csv_ipv4_includes_usage_column() -> None:
    """An IPv4 supernet's CSV carries the trailing 'Usage (%)' header and per-row usage cell"""
    with patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[ROW_A, ROW_DEGENERATE]):
        content: bytes = build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    rows: list[list[str]] = _read_csv(content)
    assert rows[0] == IpamExport.HEADERS + [IpamExport.USAGE_HEADER]
    assert rows[1] == ['10.0.0.0/24', '10.0.0.0 - 10.0.0.255', '3', '253', '1.17']
    # the degenerate row's None range is written as an empty field
    assert rows[2] == ['not-a-cidr', '', '0', '0', '0.0']


def test_build_supernet_subnets_csv_ipv6_omits_usage_column() -> None:
    """An IPv6 supernet's CSV has the base headers only and no per-row usage cell"""
    row_v6: dict[str, Any] = {
        IpamOverviewKey.CIDR: '2001:db8:1::/64',
        IpamOverviewKey.IP_RANGE: {IpamOverviewKey.FIRST: '2001:db8:1::', IpamOverviewKey.LAST: '2001:db8:1::ffff'},
        IpamOverviewKey.USED_IPS: 1,
        IpamOverviewKey.FREE_IPS: 18446744073709551615,
        IpamOverviewKey.USAGE_PERCENT: None,
    }

    with patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV6), \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[row_v6]):
        content: bytes = build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    rows: list[list[str]] = _read_csv(content)
    # No 'Usage (%)' column for IPv6: header + data row are both 4 cells. Unlike the old xlsx export,
    # CSV keeps the huge free_ips count exact (text, not Excel's float64)
    assert rows[0] == IpamExport.HEADERS
    assert rows[1] == ['2001:db8:1::/64', '2001:db8:1:: - 2001:db8:1::ffff', '1', '18446744073709551615']


def test_build_supernet_subnets_csv_emits_header_only_when_no_subnets() -> None:
    """With no assigned subnets the CSV still carries just the (family-appropriate) header row"""
    with patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[]):
        content: bytes = build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    assert _read_csv(content) == [IpamExport.HEADERS + [IpamExport.USAGE_HEADER]]


def test_build_supernet_subnets_csv_reads_the_supernet_once_and_takes_its_family_from_it() -> None:
    """One supernet read, scoped to the caller; the family is derived from that same document"""
    objects_manager, types_manager, request_user = MagicMock(), MagicMock(), MagicMock()

    with patch(f'{MODULE}.resolve_read_scope', return_value=DENIED_TYPE_IDS) as scope_mock, \
         patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC) as supernet_mock, \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4) as family_mock, \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[]):
        build_supernet_subnets_csv(objects_manager, types_manager, SUPERNET_PUBLIC_ID, request_user)

    scope_mock.assert_called_once_with(request_user)
    supernet_mock.assert_called_once_with(objects_manager, types_manager, SUPERNET_PUBLIC_ID, DENIED_TYPE_IDS)
    family_mock.assert_called_once_with(SUPERNET_DOC)


def test_build_supernet_subnets_csv_scopes_the_rows_to_the_caller() -> None:
    """The subnet rows are loaded for the same supernet, with the caller's denied type ids"""
    objects_manager, types_manager = MagicMock(), MagicMock()

    with patch(f'{MODULE}.resolve_read_scope', return_value=DENIED_TYPE_IDS), \
         patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[]) as rows_mock:
        build_supernet_subnets_csv(objects_manager, types_manager, SUPERNET_PUBLIC_ID, MagicMock())

    rows_mock.assert_called_once_with(objects_manager, types_manager, SUPERNET_PUBLIC_ID, DENIED_TYPE_IDS)


def test_build_supernet_subnets_csv_stops_on_a_supernet_abort() -> None:
    """A supernet that cannot be read aborts before any subnet row is loaded"""
    with patch(f'{MODULE}.load_supernet_object', side_effect=NotFound('missing')), \
         patch(f'{MODULE}.load_subnet_usage_rows') as rows_mock, \
         pytest.raises(HTTPException):
        build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    rows_mock.assert_not_called()


def _subnet_doc(public_id: int, cidr: str) -> dict[str, Any]:
    """Builds a SUBNET object document carrying only its network range."""
    return make_object_doc(public_id, SUBNET_TYPE_ID, [make_field(SubnetField.NETWORK_RANGE, cidr)])


def test_build_supernet_subnets_csv_runs_no_vlan_query() -> None:
    """Through the real row loader: usage figures are written, and the VLAN query never runs"""
    subnet_docs = [_subnet_doc(SUBNET_PUBLIC_ID_B, SUBNET_RANGE_B), _subnet_doc(SUBNET_PUBLIC_ID_A, SUBNET_RANGE_A)]
    used = {SUBNET_PUBLIC_ID_A: USED_IPS_A, SUBNET_PUBLIC_ID_B: USED_IPS_B}

    with patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{OVERVIEW_MODULE}.load_subnets_for_supernet', return_value=subnet_docs), \
         patch(f'{OVERVIEW_MODULE}._count_used_ips_per_subnet', return_value=used), \
         patch(f'{OVERVIEW_MODULE}.load_vlans_by_subnets') as vlans_mock:
        content: bytes = build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    vlans_mock.assert_not_called()
    # ascending CIDR order, each row with its own used count
    assert [(row[0], row[2]) for row in _read_csv(content)[1:]] == [
        (SUBNET_RANGE_A, str(USED_IPS_A)), (SUBNET_RANGE_B, str(USED_IPS_B)),
    ]


def test_build_supernet_subnets_csv_has_no_row_limit() -> None:
    """More rows than the subnet IP export allows are all written - this export has no limit"""
    row_count: int = IpamSubnetIpsExport.MAX_EXPORT_ROWS + 1

    with patch(f'{MODULE}.load_supernet_object', return_value=SUPERNET_DOC), \
         patch(f'{MODULE}.supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{MODULE}.load_subnet_usage_rows', return_value=[ROW_A] * row_count):
        content: bytes = build_supernet_subnets_csv(MagicMock(), MagicMock(), SUPERNET_PUBLIC_ID)

    assert len(_read_csv(content)) == row_count + 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _subnet_ip_export_row                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

IP_ROW_ASSIGNED: dict[str, Any] = {
    IpamOverviewKey.IP: '10.0.0.5',
    IpamOverviewKey.STATUS: IpamRowStatus.ASSIGNED,
    IpamOverviewKey.TYPE_INFO: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#fff'},
    IpamOverviewKey.ASSIGNED_TO: {IpamOverviewKey.SUMMARY_LINE: 'Server: web01'},
    IpamOverviewKey.MAC_ADDRESS: 'aa:bb:cc:dd:ee:ff',
}
IP_ROW_FREE: dict[str, Any] = {
    IpamOverviewKey.IP: '10.0.0.6',
    IpamOverviewKey.STATUS: IpamRowStatus.FREE,
    IpamOverviewKey.TYPE_INFO: None,
    IpamOverviewKey.ASSIGNED_TO: None,
    IpamOverviewKey.MAC_ADDRESS: None,
}


def test_subnet_ip_export_row_maps_assigned_row_to_human_readable_cells() -> None:
    """An assigned row carries the type label, status value, owner summary line and MAC"""
    assert _subnet_ip_export_row(IP_ROW_ASSIGNED) == [
        '10.0.0.5', 'Server', IpamRowStatus.ASSIGNED.value, 'Server: web01', 'aa:bb:cc:dd:ee:ff',
    ]


def test_subnet_ip_export_row_blanks_type_owner_and_mac_for_free_row() -> None:
    """A free row leaves the type, assigned-to and MAC cells blank (not None)"""
    assert _subnet_ip_export_row(IP_ROW_FREE) == ['10.0.0.6', '', IpamRowStatus.FREE.value, '', '']


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_subnet_ips_csv                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_subnet_ips_csv_writes_headers_and_rows() -> None:
    """The CSV carries the header row and one data row per IP, with status as its plain value"""
    with patch(f'{MODULE}.build_subnet_ip_export_rows', return_value=[IP_ROW_ASSIGNED, IP_ROW_FREE]):
        content: bytes = build_subnet_ips_csv(MagicMock(), MagicMock(), 7)

    rows: list[list[str]] = _read_csv(content)
    assert rows[0] == IpamSubnetIpsExport.HEADERS
    assert rows[1] == ['10.0.0.5', 'Server', IpamRowStatus.ASSIGNED.value, 'Server: web01', 'aa:bb:cc:dd:ee:ff']
    assert rows[2] == ['10.0.0.6', '', IpamRowStatus.FREE.value, '', '']


def test_build_subnet_ips_csv_emits_header_only_when_no_rows() -> None:
    """With no exportable IPs the CSV still carries just the header row"""
    with patch(f'{MODULE}.build_subnet_ip_export_rows', return_value=[]):
        content: bytes = build_subnet_ips_csv(MagicMock(), MagicMock(), 7)

    assert _read_csv(content) == [IpamSubnetIpsExport.HEADERS]
