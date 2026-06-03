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
Unit tests for cmdb.framework.ipam.subnet_unassign

Covers the pure helpers (normalize_ip_list, clear_subnet_ref_in_rows, clear_subnet_ref_in_owner,
collect_present_ips), the three DB loaders (assert_subnet_exists, parse_subnet_network,
load_interface_owners), the per-owner write helper (clear_subnet_ref_in_owners) and the
unassign_ips_from_subnet orchestrator. The trivial diff_missing_ips helper is exercised
implicitly through the orchestrator's validate-all-or-nothing tests. Mongo filter shapes
are pinned via assert_called_once_with so a future refactor that loosens them fails loudly.
Flask aborts are exercised via pytest.raises(HTTPException). For orchestrator tests the
internal loaders are patched at the module path; each loader has its own dedicated tests
"""
from ipaddress import IPv4Network, IPv6Network
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
    IpamUnassignKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.subnet_unassign import (
    assert_subnet_exists,
    clear_subnet_ref_in_owner,
    clear_subnet_ref_in_owners,
    clear_subnet_ref_in_rows,
    collect_present_ips,
    load_interface_owners,
    normalize_ip_list,
    parse_subnet_network,
    unassign_ips_from_subnet,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 200
OTHER_SUBNET_OBJECT_ID: int = 201
OWNER_OBJECT_ID: int = 700
OTHER_OWNER_OBJECT_ID: int = 701
OWNER_TYPE_ID: int = 50

SUBNET_RANGE: str = '10.0.0.0/24'
SUBNET_NETWORK: IPv4Network = IPv4Network(SUBNET_RANGE)

SUBNET_RANGE_V6: str = '2001:db8::/64'
SUBNET_NETWORK_V6: IPv6Network = IPv6Network(SUBNET_RANGE_V6)

PATH: str = 'cmdb.framework.ipam.subnet_unassign'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_doc(public_id: int, network_range: Any, type_id: int = SUBNET_TYPE_ID) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with a network-range field entry."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: [{
            CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE,
            CmdbObjectFieldKey.VALUE: network_range,
        }],
    }


def _make_interface_row(
    subnet_ref: Any = None,
    ip: Any = None,
    mac: str | None = None,
) -> dict[str, Any]:
    """Builds one dg-ipam-interface MDS row with the requested field entries."""
    data: list[dict[str, Any]] = []

    if subnet_ref is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: subnet_ref})

    if ip is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: ip})

    if mac is not None:
        data.append({CmdbObjectFieldKey.NAME: InterfaceField.MAC, CmdbObjectFieldKey.VALUE: mac})

    return {CmdbObjectMdsRowKey.DATA: data}


def _make_owner(
    public_id: int,
    interface_rows: list[dict[str, Any]],
    extra_sections: list[dict[str, Any]] | None = None,
    type_id: int = OWNER_TYPE_ID,
) -> dict[str, Any]:
    """Builds a CmdbObject doc with one dg-ipam-interface MDS section carrying the given rows."""
    sections: list[dict[str, Any]] = [
        {
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
            CmdbObjectMdsKey.VALUES: interface_rows,
        },
    ]

    if extra_sections:
        sections.extend(extra_sections)

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.MULTI_DATA_SECTIONS: sections,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                normalize_ip_list                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_normalize_ip_list_rejects_non_list_raw() -> None:
    """A non-list payload aborts HTTP 400 with the IPS key in the message"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list('10.0.0.1', SUBNET_NETWORK)

    assert exc_info.value.code == 400


def test_normalize_ip_list_rejects_empty_list() -> None:
    """An empty list aborts HTTP 400 (the unassign route refuses no-op calls)"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list([], SUBNET_NETWORK)

    assert exc_info.value.code == 400


def test_normalize_ip_list_rejects_non_string_entry() -> None:
    """An int entry inside the list aborts HTTP 400 (no implicit coercion)"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list(['10.0.0.1', 12345], SUBNET_NETWORK)

    assert exc_info.value.code == 400


def test_normalize_ip_list_rejects_non_canonical_ipv4() -> None:
    """An integer-formatted string (parsed by IPv4Address but not canonical) is rejected"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list(['3232235521'], SUBNET_NETWORK)

    assert exc_info.value.code == 400


def test_normalize_ip_list_rejects_ip_outside_network() -> None:
    """A valid IPv4 string that falls outside the subnet network is rejected"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list(['192.168.1.1'], SUBNET_NETWORK)

    assert exc_info.value.code == 400


def test_normalize_ip_list_dedups_preserving_input_order() -> None:
    """Duplicates collapse silently with the first occurrence's position preserved"""
    result = normalize_ip_list(['10.0.0.5', '10.0.0.1', '10.0.0.5'], SUBNET_NETWORK)

    assert result == ['10.0.0.5', '10.0.0.1']


def test_normalize_ip_list_returns_canonical_ips_for_valid_input() -> None:
    """Happy path: every entry is parseable, canonical and within the subnet"""
    result = normalize_ip_list(['10.0.0.1', '10.0.0.254'], SUBNET_NETWORK)

    assert result == ['10.0.0.1', '10.0.0.254']


def test_normalize_ip_list_accepts_ipv6_within_network() -> None:
    """IPv6 host strings inside an IPv6 subnet are accepted and returned canonical"""
    result = normalize_ip_list(['2001:db8::5', '2001:db8::ffff'], SUBNET_NETWORK_V6)

    assert result == ['2001:db8::5', '2001:db8::ffff']


def test_normalize_ip_list_canonicalizes_and_dedups_ipv6_forms() -> None:
    """Uppercase / leading-zero IPv6 forms canonicalize, so equivalent forms dedup to one entry"""
    result = normalize_ip_list(['2001:DB8::0005', '2001:db8::5'], SUBNET_NETWORK_V6)

    assert result == ['2001:db8::5']


def test_normalize_ip_list_rejects_ipv4_ip_against_ipv6_network() -> None:
    """A cross-family entry (IPv4 string, IPv6 subnet) is treated as outside the network -> 400"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list(['10.0.0.5'], SUBNET_NETWORK_V6)

    assert exc_info.value.code == 400


def test_normalize_ip_list_rejects_ipv6_outside_network() -> None:
    """A valid IPv6 string outside the subnet network is rejected"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_ip_list(['2001:dead::1'], SUBNET_NETWORK_V6)

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                            clear_subnet_ref_in_rows                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_clear_subnet_ref_in_rows_returns_inputs_when_target_set_is_empty() -> None:
    """No target IPs → every row passes through unchanged and nothing is reported as cleared"""
    rows = [
        _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1'),
        _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2'),
    ]

    new_rows, cleared = clear_subnet_ref_in_rows(rows, SUBNET_OBJECT_ID, set())

    assert new_rows == rows
    assert cleared == set()


def test_clear_subnet_ref_in_rows_only_clears_matching_subnet_and_ip() -> None:
    """A row's subnet ref is set to None only when both subnet_ref and ip match a target"""
    matching = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1', mac='aa:bb:cc:dd:ee:ff')
    same_subnet_other_ip = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2')
    other_subnet_same_ip = _make_interface_row(subnet_ref=OTHER_SUBNET_OBJECT_ID, ip='10.0.0.1')

    new_rows, cleared = clear_subnet_ref_in_rows(
        [matching, same_subnet_other_ip, other_subnet_same_ip],
        SUBNET_OBJECT_ID,
        {'10.0.0.1'},
    )

    assert cleared == {'10.0.0.1'}
    assert len(new_rows) == 3
    assert new_rows[1] is same_subnet_other_ip
    assert new_rows[2] is other_subnet_same_ip


def test_clear_subnet_ref_in_rows_preserves_ip_and_mac_on_cleared_row() -> None:
    """A cleared row keeps its dg-interface-ip-address and dg-interface-mac-address entries"""
    row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1', mac='aa:bb:cc:dd:ee:ff')

    [new_row], _ = clear_subnet_ref_in_rows([row], SUBNET_OBJECT_ID, {'10.0.0.1'})

    by_name = {entry[CmdbObjectFieldKey.NAME]: entry[CmdbObjectFieldKey.VALUE]
               for entry in new_row[CmdbObjectMdsRowKey.DATA]}
    assert by_name[InterfaceField.SUBNET] is None
    assert by_name[InterfaceField.IP] == '10.0.0.1'
    assert by_name[InterfaceField.MAC] == 'aa:bb:cc:dd:ee:ff'


def test_clear_subnet_ref_in_rows_keeps_rows_missing_subnet_or_ip_field() -> None:
    """A row with neither field passes through (no target match possible)"""
    incomplete = _make_interface_row(mac='aa:bb:cc:dd:ee:ff')

    new_rows, cleared = clear_subnet_ref_in_rows([incomplete], SUBNET_OBJECT_ID, {'10.0.0.1'})

    assert new_rows == [incomplete]
    assert cleared == set()


def test_clear_subnet_ref_in_rows_only_reports_ips_actually_cleared() -> None:
    """A target IP not present in any row is not in the cleared set"""
    present_row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')

    _, cleared = clear_subnet_ref_in_rows([present_row], SUBNET_OBJECT_ID, {'10.0.0.1', '10.0.0.99'})

    assert cleared == {'10.0.0.1'}


def test_clear_subnet_ref_in_rows_does_not_mutate_input_row() -> None:
    """The cleared row is a fresh copy; the original row's subnet entry is unchanged"""
    row = _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')

    clear_subnet_ref_in_rows([row], SUBNET_OBJECT_ID, {'10.0.0.1'})

    original_by_name = {entry[CmdbObjectFieldKey.NAME]: entry[CmdbObjectFieldKey.VALUE]
                        for entry in row[CmdbObjectMdsRowKey.DATA]}
    assert original_by_name[InterfaceField.SUBNET] == SUBNET_OBJECT_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                            clear_subnet_ref_in_owner                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_clear_subnet_ref_in_owner_returns_owner_unchanged_when_no_interface_section() -> None:
    """An owner without a dg-ipam-interface section is returned with no rows cleared"""
    owner = {
        CmdbObjectKey.PUBLIC_ID: OWNER_OBJECT_ID,
        CmdbObjectKey.TYPE_ID: OWNER_TYPE_ID,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {CmdbObjectMdsKey.SECTION_ID: 'other-section', CmdbObjectMdsKey.VALUES: []},
        ],
    }

    new_doc, cleared = clear_subnet_ref_in_owner(owner, SUBNET_OBJECT_ID, {'10.0.0.1'})

    assert cleared == set()
    assert new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS] == owner[CmdbObjectKey.MULTI_DATA_SECTIONS]


def test_clear_subnet_ref_in_owner_preserves_row_count_after_clearing() -> None:
    """All matching rows have their subnet ref cleared but the row count is unchanged"""
    rows = [
        _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1'),
        _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2'),
    ]
    owner = _make_owner(OWNER_OBJECT_ID, rows)

    new_doc, cleared = clear_subnet_ref_in_owner(owner, SUBNET_OBJECT_ID, {'10.0.0.1', '10.0.0.2'})

    [section] = new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS]
    assert section[CmdbObjectMdsKey.SECTION_ID] == IpamSection.INTERFACE
    assert len(section[CmdbObjectMdsKey.VALUES]) == 2
    assert cleared == {'10.0.0.1', '10.0.0.2'}

    for new_row in section[CmdbObjectMdsKey.VALUES]:
        by_name = {entry[CmdbObjectFieldKey.NAME]: entry[CmdbObjectFieldKey.VALUE]
                   for entry in new_row[CmdbObjectMdsRowKey.DATA]}
        assert by_name[InterfaceField.SUBNET] is None


def test_clear_subnet_ref_in_owner_does_not_mutate_original_doc() -> None:
    """The returned doc is a fresh shell; the original section / rows reference is untouched"""
    rows = [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')]
    owner = _make_owner(OWNER_OBJECT_ID, rows)
    original_sections = owner[CmdbObjectKey.MULTI_DATA_SECTIONS]
    original_values = original_sections[0][CmdbObjectMdsKey.VALUES]

    new_doc, _ = clear_subnet_ref_in_owner(owner, SUBNET_OBJECT_ID, {'10.0.0.1'})
    new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS][0][CmdbObjectMdsKey.VALUES].append({'sentinel': True})

    assert original_values == rows
    assert original_sections is owner[CmdbObjectKey.MULTI_DATA_SECTIONS]


def test_clear_subnet_ref_in_owner_passes_other_sections_through_unchanged() -> None:
    """Sections that aren't dg-ipam-interface are not inspected and are forwarded as-is"""
    other_section = {CmdbObjectMdsKey.SECTION_ID: 'dg-other', CmdbObjectMdsKey.VALUES: [{'x': 1}]}
    interface_rows = [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')]
    owner = _make_owner(OWNER_OBJECT_ID, interface_rows, extra_sections=[other_section])

    new_doc, _ = clear_subnet_ref_in_owner(owner, SUBNET_OBJECT_ID, {'10.0.0.1'})

    assert other_section in new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS]


# -------------------------------------------------------------------------------------------------------------------- #
#                                               collect_present_ips                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_present_ips_returns_empty_set_for_empty_owner_list() -> None:
    """No owners → empty present-ip set"""
    assert collect_present_ips([], SUBNET_OBJECT_ID) == set()


def test_collect_present_ips_only_collects_rows_matching_subnet_id() -> None:
    """A row referencing a different subnet does not contribute its IP"""
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [
            _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1'),
            _make_interface_row(subnet_ref=OTHER_SUBNET_OBJECT_ID, ip='10.0.0.2'),
        ],
    )

    assert collect_present_ips([owner], SUBNET_OBJECT_ID) == {'10.0.0.1'}


def test_collect_present_ips_skips_non_interface_sections_and_unionizes_across_owners() -> None:
    """Other MDS sections are ignored; IPs across owners are unioned"""
    owner_a = _make_owner(
        OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')],
        extra_sections=[{CmdbObjectMdsKey.SECTION_ID: 'dg-other', CmdbObjectMdsKey.VALUES: [{'x': 1}]}],
    )
    owner_b = _make_owner(
        OTHER_OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2')],
    )

    assert collect_present_ips([owner_a, owner_b], SUBNET_OBJECT_ID) == {'10.0.0.1', '10.0.0.2'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              assert_subnet_exists                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_assert_subnet_exists_aborts_400_when_no_subnet_type_defined() -> None:
    """No SUBNET CmdbType configured → 400 with a structured message"""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        assert_subnet_exists(MagicMock(), types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_assert_subnet_exists_aborts_404_when_no_object_matches() -> None:
    """A SUBNET CmdbType exists but no object with this public_id → 404"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        assert_subnet_exists(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_assert_subnet_exists_aborts_400_when_object_is_not_a_subnet() -> None:
    """An object exists at this public_id but its type_id is not the SUBNET type → 400"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID, CmdbObjectKey.TYPE_ID: 999},
    ]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        assert_subnet_exists(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_assert_subnet_exists_returns_the_subnet_doc_on_success() -> None:
    """Happy path returns the loaded SUBNET CmdbObject document for the orchestrator to use"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [subnet_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    assert assert_subnet_exists(objects_manager, types_manager, SUBNET_OBJECT_ID) is subnet_doc
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                              parse_subnet_network                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_subnet_network_aborts_400_when_field_missing() -> None:
    """A subnet doc with no network-range field aborts HTTP 400"""
    with pytest.raises(HTTPException) as exc_info:
        parse_subnet_network({CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID, CmdbObjectKey.FIELDS: []})

    assert exc_info.value.code == 400


def test_parse_subnet_network_aborts_400_when_cidr_unparsable() -> None:
    """An unparseable network-range field value aborts HTTP 400 with the broken value"""
    with pytest.raises(HTTPException) as exc_info:
        parse_subnet_network(_make_subnet_doc(SUBNET_OBJECT_ID, 'not-a-cidr'))

    assert exc_info.value.code == 400


def test_parse_subnet_network_returns_parsed_network_on_success() -> None:
    """Happy path returns the IPv4Network the orchestrator uses to validate target IPs"""
    result = parse_subnet_network(_make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE))

    assert result == SUBNET_NETWORK


def test_parse_subnet_network_returns_ipv6_network_for_ipv6_subnet() -> None:
    """An IPv6 subnet range parses to the corresponding IPv6Network"""
    result = parse_subnet_network(_make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE_V6))

    assert result == SUBNET_NETWORK_V6


# -------------------------------------------------------------------------------------------------------------------- #
#                                              load_interface_owners                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_interface_owners_returns_objects_manager_result() -> None:
    """The helper passes the find_objects result through verbatim"""
    owners = [
        _make_owner(OWNER_OBJECT_ID, [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')]),
    ]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = owners

    assert load_interface_owners(objects_manager, SUBNET_OBJECT_ID) is owners


def test_load_interface_owners_queries_with_nested_mds_elem_match_filter() -> None:
    """Mongo filter nests $elemMatch through multi_data_sections → values → data"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    load_interface_owners(objects_manager, SUBNET_OBJECT_ID)

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
#                                           clear_subnet_ref_in_owners                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_clear_subnet_ref_in_owners_skips_owners_with_no_matching_rows() -> None:
    """An owner whose rows never match a target IP is not updated and contributes 0 to the count"""
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.99')],
    )
    objects_manager = MagicMock()

    count = clear_subnet_ref_in_owners(
        objects_manager, [owner], SUBNET_OBJECT_ID, {'10.0.0.1'}, MagicMock(),
    )

    assert count == 0
    objects_manager.update_object.assert_not_called()


def test_clear_subnet_ref_in_owners_writes_each_touched_owner_with_acl_permission() -> None:
    """Touched owners are updated via update_object with the UPDATE ACL permission"""
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')],
    )
    objects_manager = MagicMock()
    request_user = MagicMock()

    clear_subnet_ref_in_owners(
        objects_manager, [owner], SUBNET_OBJECT_ID, {'10.0.0.1'}, request_user,
    )

    objects_manager.update_object.assert_called_once()
    call_args = objects_manager.update_object.call_args
    assert call_args.args[0] == OWNER_OBJECT_ID
    assert call_args.args[2] is request_user
    assert call_args.args[3] == AccessControlPermission.UPDATE


def test_clear_subnet_ref_in_owners_returns_total_rows_cleared_across_owners() -> None:
    """The returned count is the sum of cleared rows across every touched owner"""
    owner_a = _make_owner(
        OWNER_OBJECT_ID,
        [
            _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1'),
            _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2'),
        ],
    )
    owner_b = _make_owner(
        OTHER_OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.3')],
    )

    count = clear_subnet_ref_in_owners(
        MagicMock(), [owner_a, owner_b], SUBNET_OBJECT_ID,
        {'10.0.0.1', '10.0.0.2', '10.0.0.3'}, MagicMock(),
    )

    assert count == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                            unassign_ips_from_subnet                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_ips_from_subnet_propagates_subnet_existence_aborts() -> None:
    """A 404 from assert_subnet_exists propagates out of the orchestrator"""
    with patch(f'{PATH}.assert_subnet_exists', side_effect=HTTPException(description='not found')) as guard:
        guard.side_effect.code = 404

        with pytest.raises(HTTPException):
            unassign_ips_from_subnet(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, ['10.0.0.1'], MagicMock())


def test_unassign_ips_from_subnet_aborts_400_when_any_requested_ip_is_not_assigned() -> None:
    """Validate-all-or-nothing: any unknown IP triggers HTTP 400 and no write happens"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')],
    )
    objects_manager = MagicMock()

    with patch(f'{PATH}.assert_subnet_exists', return_value=subnet_doc), \
         patch(f'{PATH}.load_interface_owners', return_value=[owner]), \
         pytest.raises(HTTPException) as exc_info:
        unassign_ips_from_subnet(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            ['10.0.0.1', '10.0.0.2'], MagicMock(),
        )

    assert exc_info.value.code == 400
    objects_manager.update_object.assert_not_called()


def test_unassign_ips_from_subnet_returns_response_envelope_on_happy_path() -> None:
    """Happy path returns the {ips, unassigned_count} envelope with deduped input order"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [
            _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1'),
            _make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.2'),
        ],
    )
    objects_manager = MagicMock()

    with patch(f'{PATH}.assert_subnet_exists', return_value=subnet_doc), \
         patch(f'{PATH}.load_interface_owners', return_value=[owner]):
        result = unassign_ips_from_subnet(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID,
            ['10.0.0.2', '10.0.0.1', '10.0.0.2'], MagicMock(),
        )

    assert result == {
        IpamUnassignKey.IPS: ['10.0.0.2', '10.0.0.1'],
        IpamUnassignKey.UNASSIGNED_COUNT: 2,
    }


def test_unassign_ips_from_subnet_forwards_request_user_to_per_owner_writes() -> None:
    """The request_user is threaded through to update_object so ACL is enforced per owner"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    owner = _make_owner(
        OWNER_OBJECT_ID,
        [_make_interface_row(subnet_ref=SUBNET_OBJECT_ID, ip='10.0.0.1')],
    )
    objects_manager = MagicMock()
    request_user = MagicMock()

    with patch(f'{PATH}.assert_subnet_exists', return_value=subnet_doc), \
         patch(f'{PATH}.load_interface_owners', return_value=[owner]):
        unassign_ips_from_subnet(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, ['10.0.0.1'], request_user,
        )

    objects_manager.update_object.assert_called_once()
    assert objects_manager.update_object.call_args.args[2] is request_user
    assert objects_manager.update_object.call_args.args[3] == AccessControlPermission.UPDATE


def test_unassign_ips_from_subnet_does_not_write_when_no_owner_matches() -> None:
    """When the requested IP is present but its owner is filtered out (drift), the call fails 400"""
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, SUBNET_RANGE)
    objects_manager = MagicMock()

    with patch(f'{PATH}.assert_subnet_exists', return_value=subnet_doc), \
         patch(f'{PATH}.load_interface_owners', return_value=[]), \
         pytest.raises(HTTPException) as exc_info:
        unassign_ips_from_subnet(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, ['10.0.0.1'], MagicMock(),
        )

    assert exc_info.value.code == 400
    objects_manager.update_object.assert_not_called()
