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
Unit tests for cmdb.framework.ipam.subnet_overview.orchestrators

Covers the degenerate broken-state payload and the two top-level builders: build_subnet_overview
(KPI block, paginated / search / sort / filter IP table, distributions, VLANs, invalid handling,
IPv6 adaptations) and build_invalid_ips_overview (the invalid-rows-only variant). The internal
loaders and the VLAN helper are patched at the orchestrators module's own bindings; each loader
has dedicated tests in test_assigned_rows
"""
from ipaddress import IPv4Address
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpAddressFamily,
    IpamOverviewKey,
    IpamRowStatus,
    IpamBucketLabel,
)
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
from cmdb.framework.ipam.subnet_overview.orchestrators import (
    _build_broken_state_payload,
    build_subnet_overview,
    build_invalid_ips_overview,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OWNER_OBJECT_ID: int = 700
OWNER_TYPE_ID: int = 50
OTHER_OWNER_TYPE_ID: int = 51

SUBNET_RANGE: str = '10.0.0.0/24'
SUBNET_RANGE_V6: str = '2001:db8::/64'
PATH: str = 'cmdb.framework.ipam.subnet_overview.orchestrators'

VLAN_OBJECT_ID_X: int = 501
VLAN_OBJECT_ID_Y: int = 502
VLAN_NAME_X: str = 'VLAN-X'
VLAN_NAME_Y: str = 'VLAN-Y'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_doc(public_id: int, network_range: Any, subnet_type: Any = None) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field and an optional type field."""
    fields: list[dict[str, Any]] = [{
        CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
        CmdbObjectFieldKey.VALUE: network_range,
    }]

    if subnet_type is not None:
        fields.append({
            CmdbObjectFieldKey.NAME: SubnetField.TYPE,
            CmdbObjectFieldKey.VALUE: subnet_type,
        })

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS: fields,
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
    """An abort raised by load_subnet_object propagates out of the orchestrator"""
    with patch(f'{PATH}.load_subnet_object', side_effect=NotFound('not found')), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_build_subnet_overview_returns_degenerate_payload_when_cidr_unparsable() -> None:
    """A subnet whose network range is unparsable yields zeroed counters and an empty page"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    subnet_block = payload[IpamOverviewKey.SUBNET]
    assert subnet_block[IpamOverviewKey.CIDR] == 'not-a-cidr'
    assert subnet_block[IpamOverviewKey.TOTAL_IPS] == 0
    assert subnet_block[IpamOverviewKey.ASSIGNABLE_IPS] == 0
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.TYPE_DISTRIBUTION] == []
    assert payload[IpamOverviewKey.IP_DISTRIBUTION] == {}
    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_broken_state_reports_family_from_selector() -> None:
    """With an unparsable CIDR the degenerate payload's subnet_type comes from the selector (ipv6), else ipv4"""
    ipv6_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr', subnet_type=IpAddressFamily.IPV6)
    legacy_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}.load_subnet_object', return_value=ipv6_doc):
        ipv6_payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    with patch(f'{PATH}.load_subnet_object', return_value=legacy_doc):
        legacy_payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert ipv6_payload[IpamOverviewKey.SUBNET][IpamOverviewKey.SUBNET_TYPE] == IpAddressFamily.IPV6
    assert legacy_payload[IpamOverviewKey.SUBNET][IpamOverviewKey.SUBNET_TYPE] == IpAddressFamily.IPV4


def test_build_subnet_overview_omits_ip_range_from_subnet_block() -> None:
    """The subnet block no longer carries an ip_range key (removed; supernet keeps it)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert IpamOverviewKey.IP_RANGE not in payload[IpamOverviewKey.SUBNET]


def test_build_subnet_overview_emits_full_payload_envelope_on_happy_path() -> None:
    """Happy path payload carries subnet summary / ips / type_distribution / ip_distribution / vlans"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, page=1, page_size=5)

    assert (
        payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL]
        == payload[IpamOverviewKey.SUBNET][IpamOverviewKey.ASSIGNABLE_IPS]
    )


def test_build_subnet_overview_search_filters_ips_total_below_assignable() -> None:
    """Active search shrinks ips.total to the match count; assignable_ips stays the full count"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
        no_search = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        with_search = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, search='10.0.0.5',
        )

    assert no_search[IpamOverviewKey.TYPE_DISTRIBUTION] == with_search[IpamOverviewKey.TYPE_DISTRIBUTION]
    assert no_search[IpamOverviewKey.IP_DISTRIBUTION] == with_search[IpamOverviewKey.IP_DISTRIBUTION]


def test_build_subnet_overview_search_below_min_length_is_treated_as_no_search() -> None:
    """A 1-char query (below MIN_QUERY_LENGTH) restores the full assignable-range table"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='foo')

    assert exc_info.value.code == 400


def test_build_subnet_overview_aborts_400_on_unknown_sort_direction() -> None:
    """An invalid ?order= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, sort='ip', order='sideways')

    assert exc_info.value.code == 400


def test_build_subnet_overview_sorts_rows_by_ip_descending_when_order_desc() -> None:
    """sort=ip & order=desc reverses the natural ascending order on the page"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            MagicMock(), MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=3, sort='ip', order='-1',
        )

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in rows] == ['10.0.0.254', '10.0.0.253', '10.0.0.252']


def test_build_subnet_overview_sort_default_ip_asc_uses_lazy_path() -> None:
    """sort=ip + no order keeps the lazy ascending IP path (ips.total == assignable)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, sort='assigned_to',
        )

    objects_manager.get_summary_lines_lookup.assert_called()


def test_build_subnet_overview_sort_combines_with_search() -> None:
    """search + sort: matching IPs are filtered first, then ordered by the chosen column"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
def test_build_subnet_overview_vlans_carries_referenced_vlans_for_this_subnet() -> None:
    """The top-level 'vlans' list carries the bucket the lifted helper returns for this subnet"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    vlan_bucket = [
        {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X},
        {CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_Y, IpamOverviewKey.NAME: VLAN_NAME_Y},
    ]

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={SUBNET_OBJECT_ID: vlan_bucket}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == vlan_bucket


def test_build_subnet_overview_vlans_is_empty_list_when_no_vlan_references_subnet() -> None:
    """No bucket for this subnet → empty list (not missing key, so FE can iterate unconditionally)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_invokes_vlan_helper_with_single_subnet_id_list() -> None:
    """The orchestrator queries the VLAN helper with exactly [public_id]"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}) as vlan_loader:
        build_subnet_overview(objects_manager, types_manager, SUBNET_OBJECT_ID)

    vlan_loader.assert_called_once_with(objects_manager, types_manager, [SUBNET_OBJECT_ID])


def test_build_subnet_overview_vlans_is_empty_list_on_degenerate_cidr_path() -> None:
    """Broken-state payload (unparsable CIDR) carries an empty vlans list, mirroring the happy-path envelope"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc):
        payload = build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.VLANS] == []


def test_build_subnet_overview_vlans_is_invariant_under_search_and_sort() -> None:
    """The 'vlans' list covers the whole subnet, unaffected by search / sort query params"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    vlan_bucket = [{CmdbObjectKey.PUBLIC_ID: VLAN_OBJECT_ID_X, IpamOverviewKey.NAME: VLAN_NAME_X}]

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
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

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta), \
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=50, search='10.0.0.5', status='assigned',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['10.0.0.5']


def test_build_subnet_overview_aborts_400_on_unknown_status_filter() -> None:
    """An invalid ?status= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         pytest.raises(HTTPException) as exc_info:
        build_subnet_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, status='partial')

    assert exc_info.value.code == 400


def test_build_subnet_overview_aborts_400_on_non_integer_type_filter() -> None:
    """An invalid ?type= value propagates as HTTP 400 out of the orchestrator"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
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
    objects_manager.get_summary_lines_lookup.return_value = {}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            type_filter=f'{OWNER_TYPE_ID},{OTHER_OWNER_TYPE_ID}',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['10.0.0.1', '10.0.0.2']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 2


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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.INVALID_COUNT] == 2


def test_build_subnet_overview_appends_invalid_rows_after_assignable_in_default_order() -> None:
    """Default (no sort) order shows assignable IPs first, then invalid IPs trailing"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
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
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_subnet_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            page=1, page_size=50, search='192.168',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['192.168.1.5']


# -------------------------------------------------------------------------------------------------------------------- #
#                                              IPv6 ADAPTATION                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_overview_ipv6_is_assigned_only_with_family_and_assigned_share_percentages() -> None:
    """IPv6 overview: subnet_type=ipv6, ips list only assigned rows, type_distribution has no Free, % of assigned"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE_V6)
    assigned = {'2001:db8::5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True)}
    type_meta = {OWNER_TYPE_ID: {IpamOverviewKey.LABEL: 'Server', IpamOverviewKey.CI_EXPLORER_COLOR: None}}

    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Server: web01'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value=type_meta), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.SUBNET][IpamOverviewKey.SUBNET_TYPE] == IpAddressFamily.IPV6
    # IP table shows only the assigned address - no enumerated free rows
    ip_rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    assert [r[IpamOverviewKey.IP] for r in ip_rows] == ['2001:db8::5']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 1
    # type_distribution: one type bucket, no Free, percentage = share of the assigned addresses
    distribution = payload[IpamOverviewKey.TYPE_DISTRIBUTION]
    labels = [b[IpamOverviewKey.LABEL] for b in distribution]
    assert IpamBucketLabel.FREE not in labels
    assert distribution[0][IpamOverviewKey.PERCENTAGE] == 100.0  # the one assigned address is 100% of assigned


# -------------------------------------------------------------------------------------------------------------------- #
#                                       build_invalid_ips_overview                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_invalid_ips_overview_emits_same_envelope_keys() -> None:
    """Same top-level key set as the main overview"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value={}), \
         patch(f'{PATH}.resolve_type_meta', return_value={}), \
         patch(f'{PATH}.load_vlans_by_subnets', return_value={}):
        payload = build_invalid_ips_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert set(payload.keys()) == {
        IpamOverviewKey.SUBNET,
        IpamOverviewKey.IPS,
        IpamOverviewKey.TYPE_DISTRIBUTION,
        IpamOverviewKey.IP_DISTRIBUTION,
        IpamOverviewKey.VLANS,
        IpamOverviewKey.INVALID_COUNT,
    }


def test_build_invalid_ips_overview_returns_only_invalid_rows() -> None:
    """ips.rows contains only out-of-CIDR rows; in-range assigned rows are excluded"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
        '172.16.0.9': _make_assigned_entry(OWNER_OBJECT_ID + 2, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_invalid_ips_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    rows = payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]
    ips = [r[IpamOverviewKey.IP] for r in rows]
    assert ips == ['172.16.0.9', '192.168.1.5']
    assert all(r[IpamOverviewKey.IS_VALID] is False for r in rows)
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 2


def test_build_invalid_ips_overview_kpi_block_matches_main_view() -> None:
    """KPI block covers the whole subnet, same shape as the main overview"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '10.0.0.1': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=True),
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        main_payload = build_subnet_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)
        invalid_payload = build_invalid_ips_overview(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert main_payload[IpamOverviewKey.SUBNET] == invalid_payload[IpamOverviewKey.SUBNET]
    assert main_payload[IpamOverviewKey.INVALID_COUNT] == invalid_payload[IpamOverviewKey.INVALID_COUNT]


def test_build_invalid_ips_overview_search_filters_invalid_rows() -> None:
    """search narrows ips.rows / ips.total but leaves invalid_count covering the whole subnet"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    assigned = {
        '192.168.1.5': _make_assigned_entry(OWNER_OBJECT_ID, OWNER_TYPE_ID, None, is_valid=False),
        '172.16.0.9': _make_assigned_entry(OWNER_OBJECT_ID + 1, OWNER_TYPE_ID, None, is_valid=False),
    }
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'x'}

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc), \
         patch(f'{PATH}.load_assigned_rows_map', return_value=assigned), \
         patch(f'{PATH}.resolve_type_meta', return_value={}):
        payload = build_invalid_ips_overview(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, search='192.168',
        )

    ips = [r[IpamOverviewKey.IP] for r in payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS]]
    assert ips == ['192.168.1.5']
    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.TOTAL] == 1
    assert payload[IpamOverviewKey.INVALID_COUNT] == 2


def test_build_invalid_ips_overview_returns_degenerate_payload_when_cidr_unparsable() -> None:
    """Broken CIDR yields the degenerate envelope (mirrors build_subnet_overview)"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr')

    with patch(f'{PATH}.load_subnet_object', return_value=subnet_doc):
        payload = build_invalid_ips_overview(MagicMock(), MagicMock(), SUBNET_OBJECT_ID)

    assert payload[IpamOverviewKey.IPS][IpamOverviewKey.ROWS] == []
    assert payload[IpamOverviewKey.INVALID_COUNT] == 0
