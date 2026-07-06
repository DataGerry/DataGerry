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
Unit tests for cmdb.framework.ipam.subnet_overview.sectors

Covers the single-sector drill-down: the grid-presence guard (_require_sector_grid), the
sector-bounds validator (_resolve_sector_bounds) and the build_subnet_sector_ips orchestrator
(IPv4 assignable window, IPv6 assigned-only window, the abort paths). The orchestrator's DB
collaborators are patched at the sectors module's own bindings
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpamOverviewKey,
    IpamRowStatus,
)
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.sectors import (
    _require_sector_grid,
    _resolve_sector_bounds,
    build_subnet_sector_ips,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50

SUBNET_RANGE: str = '10.0.0.0/24'
SUBNET_RANGE_V6: str = '2001:db8::/64'
PATH: str = 'cmdb.framework.ipam.subnet_overview.sectors'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_doc(public_id: int, network_range: Any) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS: [{
            CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    }


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
#                                            _require_sector_grid                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_require_sector_grid_returns_sector_size_for_slash_24() -> None:
    """A /24 fills the full 4x16 grid; the sector size is 256 / 64 = 4 addresses"""
    assert _require_sector_grid(SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24')) == 4


def test_require_sector_grid_aborts_when_subnet_too_small() -> None:
    """A /27 cannot fill the full grid, so there are no clickable sectors -> 400"""
    with pytest.raises(HTTPException) as exc_info:
        _require_sector_grid(SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/27'))

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _resolve_sector_bounds                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_sector_bounds_returns_inclusive_window_for_aligned_start() -> None:
    """An aligned start yields the [lo, hi] integer window of that sector"""
    network = IPv4Network('10.0.0.0/24')
    lo, hi = _resolve_sector_bounds(network, '10.0.0.4', sector_size=4)

    assert (lo, hi) == (int(IPv4Address('10.0.0.4')), int(IPv4Address('10.0.0.7')))


def test_resolve_sector_bounds_aborts_for_unaligned_start() -> None:
    """A start that is not on a sector boundary aborts 400"""
    with pytest.raises(HTTPException) as exc_info:
        _resolve_sector_bounds(IPv4Network('10.0.0.0/24'), '10.0.0.5', sector_size=4)

    assert exc_info.value.code == 400


def test_resolve_sector_bounds_aborts_for_wrong_family_or_out_of_range() -> None:
    """A cross-family start, an out-of-subnet start, or an unparsable string all abort 400"""
    network = IPv4Network('10.0.0.0/24')

    for bad_start in ('2001:db8::', '192.168.1.0', 'nonsense'):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_sector_bounds(network, bad_start, sector_size=4)
        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_subnet_sector_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_sector_ips_ipv4_lists_assignable_window_free_and_assigned() -> None:
    """An IPv4 mid sector lists its assignable addresses (free + assigned), echoing the window"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)  # 10.0.0.0/24 -> sector_size 4
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server'}}):
        payload = build_subnet_sector_ips(objects_manager, MagicMock(), SUBNET_OBJECT_ID, '10.0.0.4')

    assert payload[IpamOverviewKey.SECTOR] == {
        IpamOverviewKey.IP_START: '10.0.0.4', IpamOverviewKey.IP_END: '10.0.0.7',
    }
    ips = payload[IpamOverviewKey.IPS]
    assert ips[IpamOverviewKey.TOTAL] == 4
    assert [r[IpamOverviewKey.IP] for r in ips[IpamOverviewKey.ROWS]] == \
        ['10.0.0.4', '10.0.0.5', '10.0.0.6', '10.0.0.7']
    statuses = {r[IpamOverviewKey.IP]: r[IpamOverviewKey.STATUS] for r in ips[IpamOverviewKey.ROWS]}
    assert statuses['10.0.0.5'] == IpamRowStatus.ASSIGNED
    assert statuses['10.0.0.4'] == IpamRowStatus.FREE


def test_build_subnet_sector_ips_ipv4_first_sector_excludes_network_address() -> None:
    """The first sector clamps to the assignable range, dropping the network address"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_sector_ips(objects_manager, MagicMock(), SUBNET_OBJECT_ID, '10.0.0.0')

    ips = payload[IpamOverviewKey.IPS]
    assert ips[IpamOverviewKey.TOTAL] == 3  # .0 (network) excluded, .1 .2 .3 remain
    assert [r[IpamOverviewKey.IP] for r in ips[IpamOverviewKey.ROWS]] == ['10.0.0.1', '10.0.0.2', '10.0.0.3']


def test_build_subnet_sector_ips_ipv6_is_assigned_only_within_the_sector() -> None:
    """An IPv6 sector lists only the assigned addresses inside its window (no free enumeration)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE_V6)  # sector_size 2**58
    # '2001:db8::5' is in sector 0; the all-ffff host is in the last sector
    in_sector_0 = _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)
    in_last_sector = _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)
    assigned = {'2001:db8::5': in_sector_0, '2001:db8::ffff:ffff:ffff:ffff': in_last_sector}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server'}}):
        payload = build_subnet_sector_ips(objects_manager, MagicMock(), SUBNET_OBJECT_ID, '2001:db8::')

    ips = payload[IpamOverviewKey.IPS]
    assert ips[IpamOverviewKey.TOTAL] == 1
    assert [r[IpamOverviewKey.IP] for r in ips[IpamOverviewKey.ROWS]] == ['2001:db8::5']


def test_build_subnet_sector_ips_aborts_for_subnet_without_grid() -> None:
    """A subnet too small to expose a grid aborts 400 (no sectors to drill into)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, '10.0.0.0/27')

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_sector_ips(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, '10.0.0.0')

    assert exc_info.value.code == 400


def test_build_subnet_sector_ips_aborts_for_misaligned_sector_start() -> None:
    """A sector_start that is not a sector boundary aborts 400"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_sector_ips(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, '10.0.0.5')

    assert exc_info.value.code == 400
