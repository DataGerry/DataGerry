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
Unit tests for cmdb.framework.ipam.subnet_overview.export_rows

Covers the export-size guard (_abort_if_export_too_big) and the build_subnet_ip_export_rows
row provider (IPv4 free + assigned, IPv6 assigned-only, the abort paths and the cheap size
check that never enumerates an oversized space). DB collaborators are patched at the
export_rows module's own bindings
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpamOverviewKey,
    IpamRowStatus,
    IpamSubnetIpsExport,
)
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.export_rows import (
    _abort_if_export_too_big,
    build_subnet_ip_export_rows,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50

SUBNET_RANGE: str = '10.0.0.0/24'
PATH: str = 'cmdb.framework.ipam.subnet_overview.export_rows'


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
#                                          _abort_if_export_too_big                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_abort_if_export_too_big_raises_400_over_the_limit() -> None:
    """One row over IpamSubnetIpsExport.MAX_EXPORT_ROWS aborts 400"""
    with pytest.raises(HTTPException) as exc_info:
        _abort_if_export_too_big(SUBNET_OBJECT_ID, IpamSubnetIpsExport.MAX_EXPORT_ROWS + 1)

    assert exc_info.value.code == 400


def test_abort_if_export_too_big_allows_the_limit_exactly() -> None:
    """Exactly MAX_EXPORT_ROWS rows is allowed (the guard returns without raising)"""
    assert _abort_if_export_too_big(SUBNET_OBJECT_ID, IpamSubnetIpsExport.MAX_EXPORT_ROWS) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                        build_subnet_ip_export_rows                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_ip_export_rows_ipv4_emits_free_and_assigned() -> None:
    """An IPv4 subnet exports every assignable address (free + assigned) in ascending IP order"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:ff')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
        rows = build_subnet_ip_export_rows(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    # /24 has 254 assignable addresses (network + broadcast excluded)
    assert len(rows) == 254
    assert rows[0][IpamOverviewKey.IP] == '10.0.0.1'
    assigned_rows = [r for r in rows if r[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED]
    assert [r[IpamOverviewKey.IP] for r in assigned_rows] == ['10.0.0.5']
    assert assigned_rows[0][IpamOverviewKey.TYPE_INFO][IpamOverviewKey.LABEL] == 'Server'


def test_build_subnet_ip_export_rows_resolves_summary_lines_once() -> None:
    """The export's summary lines are batch-resolved in a single get_summary_lines_lookup call"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {'10.0.0.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        build_subnet_ip_export_rows(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    objects_manager.get_summary_lines_lookup.assert_called_once()


def test_build_subnet_ip_export_rows_ipv6_emits_assigned_only() -> None:
    """An IPv6 subnet exports only its in-CIDR assigned addresses (no free rows, no out-of-CIDR rows)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, '2001:db8::/64')
    assigned = {
        '2001:db8::20': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:01'),
        '2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:02'),
        '2002:db8::9': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'x', is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        rows = build_subnet_ip_export_rows(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    # only the two in-CIDR assigned IPs, ascending; the out-of-CIDR (invalid) row is excluded
    assert [r[IpamOverviewKey.IP] for r in rows] == ['2001:db8::5', '2001:db8::20']
    assert all(r[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED for r in rows)


def test_build_subnet_ip_export_rows_aborts_400_when_ipv4_too_big_without_enumerating() -> None:
    """A large IPv4 subnet aborts 400 on the cheap assignable count, never enumerating the space"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, '10.0.0.0/20')  # 4094 assignable > 2500

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.list_all_assignable_ips') as mock_enumerate, \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_ip_export_rows(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400
    mock_enumerate.assert_not_called()


def test_build_subnet_ip_export_rows_aborts_400_when_range_unparsable() -> None:
    """A subnet whose network range is missing / unparsable aborts 400"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_ip_export_rows(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_build_subnet_ip_export_rows_propagates_load_subnet_aborts() -> None:
    """An abort raised by load_subnet_object (missing / non-subnet object) propagates out"""
    with patch(f'{PATH}.load_subnet_object', side_effect=NotFound('not found')), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_ip_export_rows(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404
