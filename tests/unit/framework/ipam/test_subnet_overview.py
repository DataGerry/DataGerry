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
    InterfaceField,
    IpamSection,
    IpamOverviewKey,
    IpamRowStatus,
    IpamBucketLabel,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.subnet_overview import (
    _AssignedField,
    _bucket_used_counts,
    _build_ip_distribution,
    _build_type_distribution,
    _compose_assigned_row,
    _compose_free_row,
    _compose_sector,
    _compute_grid_dimensions,
    _extract_row_fields,
    _load_assigned_rows_map,
    _load_subnet_object,
    _page_slice_ips,
    _resolve_type_meta,
    build_subnet_overview,
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


def _make_assigned_entry(object_id: int, type_id: int | None, mac: str | None) -> dict[str, Any]:
    """Builds one value of the assigned map (the shape _load_assigned_rows_map produces)."""
    return {
        _AssignedField.OBJECT_ID: object_id,
        _AssignedField.TYPE_ID: type_id,
        _AssignedField.MAC: mac,
    }


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
#                                            _compose_assigned_row                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_assigned_row_pins_full_shape() -> None:
    """Output dict carries ip, status='assigned', type_info, assigned_to, mac_address keys"""
    type_info = {
        CmdbObjectKey.PUBLIC_ID: OWNER_TYPE_ID,
        IpamOverviewKey.LABEL: 'Server',
        IpamOverviewKey.CI_EXPLORER_COLOR: '#FF0000',
    }
    assigned_to = {CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID, IpamOverviewKey.SUMMARY_LINE: 'Server: web01'}

    row = _compose_assigned_row('10.0.0.5', type_info, assigned_to, 'aa:bb:cc:dd:ee:ff')

    assert row == {
        IpamOverviewKey.IP: '10.0.0.5',
        IpamOverviewKey.STATUS: IpamRowStatus.ASSIGNED,
        IpamOverviewKey.TYPE_INFO: type_info,
        IpamOverviewKey.ASSIGNED_TO: assigned_to,
        IpamOverviewKey.MAC_ADDRESS: 'aa:bb:cc:dd:ee:ff',
    }


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
    """Each in-range matching row contributes one entry keyed by its parsed IP"""
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


def test_load_assigned_rows_map_skips_rows_outside_the_subnet_range() -> None:
    """Rows with IPs outside the given network are filtered out defensively"""
    candidate = _make_interface_carrier(
        public_id=OWNER_OBJECT_ID,
        type_id=OWNER_TYPE_ID,
        rows=[_make_interface_row(SUBNET_OBJECT_ID, '192.168.1.5', None)],
    )
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [candidate]

    result = _load_assigned_rows_map(objects_manager, SUBNET_OBJECT_ID, IPv4Network('10.0.0.0/24'))

    assert result == {}


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
#                                            build_subnet_overview                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_overview_propagates_load_subnet_aborts() -> None:
    """An abort raised by _load_subnet_object propagates out of the orchestrator"""
    from werkzeug.exceptions import NotFound

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
    """Happy path payload carries subnet summary / ips / type_distribution / ip_distribution"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.get_summary_line.return_value = 'Server: web01'

    with patch(f'{PATH}._load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}._load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}._resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert set(payload.keys()) == {
        IpamOverviewKey.SUBNET,
        IpamOverviewKey.IPS,
        IpamOverviewKey.TYPE_DISTRIBUTION,
        IpamOverviewKey.IP_DISTRIBUTION,
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
