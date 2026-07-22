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
Unit tests for cmdb.framework.ipam.subnet_overview.rows

Covers the wire-format row composers (_compose_assigned_row, _compose_free_row, compose_ip_row)
and the paginated 'ips' block assembly (build_ips_block). compose_ip_row now reads summary
lines from a pre-batched dict rather than calling the manager per row; build_ips_block resolves
the page's summary lines via a single get_summary_lines_lookup batch
"""
from ipaddress import IPv4Network
from typing import Any
from unittest.mock import MagicMock

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamRowStatus
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.rows import (
    _compose_assigned_row,
    _compose_free_row,
    compose_ip_row,
    build_ips_block,
)
# -------------------------------------------------------------------------------------------------------------------- #


OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50


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
#                                              compose_ip_row                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_ip_row_returns_free_row_when_ip_not_in_assigned_map() -> None:
    """An IP absent from the assigned map yields the free-row shape regardless of summary_lines"""
    row = compose_ip_row('10.0.0.1', assigned={}, type_meta={}, summary_lines={})

    assert row[IpamOverviewKey.STATUS] == IpamRowStatus.FREE
    assert row[IpamOverviewKey.ASSIGNED_TO] is None


def test_compose_ip_row_returns_assigned_row_with_resolved_type_info_and_summary() -> None:
    """An IP present in the assigned map reads its summary line from summary_lines and resolves type metadata"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb:cc:dd:ee:ff')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    summary_lines = {'10.0.0.1': 'Server: web01'}

    row = compose_ip_row('10.0.0.1', assigned=assigned, type_meta=type_meta, summary_lines=summary_lines)

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


def test_compose_ip_row_falls_back_to_empty_summary_when_owner_absent_from_batch() -> None:
    """An assigned IP whose owner did not resolve (absent from summary_lines) gets an empty summary line"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    row = compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, summary_lines={})

    assert row[IpamOverviewKey.ASSIGNED_TO][IpamOverviewKey.SUMMARY_LINE] == ''


def test_compose_ip_row_sets_type_info_to_none_when_type_id_is_none() -> None:
    """An assigned entry whose type_id is None yields type_info=None on the row"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, None, None)}

    row = compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, summary_lines={'10.0.0.1': 'Server: web01'})

    assert row[IpamOverviewKey.TYPE_INFO] is None


def test_compose_ip_row_sets_type_info_with_none_label_and_color_when_type_meta_missing() -> None:
    """An assigned entry whose type_id has no entry in type_meta still emits the type_info envelope"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    row = compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, summary_lines={'10.0.0.1': 'Server: web01'})

    assert row[IpamOverviewKey.TYPE_INFO] == {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: None,
        IpamOverviewKey.CI_EXPLORER_COLOR: None,
    }


def test_compose_ip_row_carries_none_mac_when_assigned_entry_lacks_mac() -> None:
    """A MAC value of None in the assigned entry surfaces as mac_address=None on the row"""
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None)}

    row = compose_ip_row('10.0.0.1', assigned=assigned, type_meta={}, summary_lines={'10.0.0.1': 'Server: web01'})

    assert row[IpamOverviewKey.MAC_ADDRESS] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_ips_block                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_ips_block_uses_lazy_path_when_candidates_is_none() -> None:
    """candidates=None → ips.total equals assignable; rows come from the lazy IP slice"""
    network = IPv4Network('10.0.0.0/24')

    block = build_ips_block(
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

    block = build_ips_block(
        network, assignable=254, page=1, page_size=2,
        candidates=candidates, assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert block[IpamOverviewKey.TOTAL] == 4
    assert [r[IpamOverviewKey.IP] for r in block[IpamOverviewKey.ROWS]] == ['10.0.0.5', '10.0.0.50']


def test_build_ips_block_returns_empty_rows_when_candidates_list_is_empty() -> None:
    """An empty candidates list yields total=0 and an empty rows list"""
    network = IPv4Network('10.0.0.0/24')

    block = build_ips_block(
        network, assignable=254, page=1, page_size=10,
        candidates=[], assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert block[IpamOverviewKey.TOTAL] == 0
    assert block[IpamOverviewKey.ROWS] == []


def test_build_ips_block_preserves_candidate_order_in_rows() -> None:
    """The rows on the page mirror the candidates list order verbatim (no re-sorting)"""
    network = IPv4Network('10.0.0.0/24')
    candidates = ['10.0.0.10', '10.0.0.1', '10.0.0.42']

    block = build_ips_block(
        network, assignable=254, page=1, page_size=10,
        candidates=candidates, assigned={}, type_meta={}, objects_manager=MagicMock(),
    )

    assert [r[IpamOverviewKey.IP] for r in block[IpamOverviewKey.ROWS]] == candidates


def test_build_ips_block_shapes_assigned_rows_through_compose_ip_row() -> None:
    """An assigned IP on the page is shaped via compose_ip_row (status='assigned', summary set)"""
    network = IPv4Network('10.0.0.0/24')
    assigned = {'10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, 'aa:bb')}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000'}}
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    block = build_ips_block(
        network, assignable=254, page=1, page_size=1,
        candidates=None, assigned=assigned, type_meta=type_meta, objects_manager=objects_manager,
    )

    [first_row] = block[IpamOverviewKey.ROWS]
    assert first_row[IpamOverviewKey.STATUS] == IpamRowStatus.ASSIGNED
    assert first_row[IpamOverviewKey.ASSIGNED_TO][IpamOverviewKey.SUMMARY_LINE] == 'Server: web01'


def test_build_ips_block_resolves_summary_lines_once_per_page() -> None:
    """The page's summary lines are batch-resolved in a single get_summary_lines_lookup call"""
    network = IPv4Network('10.0.0.0/24')
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None),
        '10.0.0.2': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None),
        '10.0.0.3': _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {
        OWNER_OBJECT_ID: 'Server: web01',
        OWNER_OBJECT_ID + 1: 'Server: web02',
        OWNER_OBJECT_ID + 2: 'Server: web03',
    }

    build_ips_block(
        network, assignable=254, page=1, page_size=10,
        candidates=['10.0.0.1', '10.0.0.2', '10.0.0.3'],
        assigned=assigned, type_meta={}, objects_manager=objects_manager,
    )

    objects_manager.get_summary_lines_lookup.assert_called_once()
