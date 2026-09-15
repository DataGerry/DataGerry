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
Unit tests for cmdb.framework.ipam.enforcement

Covers the pure helpers, the per-SpecialType enforcers, the delete guards and the two
orchestrators. Downstream validators (validate_subnet, validate_vlan, validate_interface_rows,
the reference finders) are patched at the enforcement module path so each enforcer test
verifies the dispatch/glue logic in isolation. The validators themselves have their own
dedicated unit-test files. _build_delete_guard_error is intentionally not tested directly:
it is a one-line wrapper around build_error, covered by its callers
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.utils import ValidationErrorKey
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
    VlanField,
    InterfaceField,
    IpAddressFamily,
    IpamSection,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.enforcement import (
    _canonical_cidr,
    _canonical_ip,
    _canonicalize_interface_ips,
    _coerce_int,
    _enforce_interface_rows,
    _enforce_subnet_object,
    _enforce_supernet_object,
    _enforce_vlan_object,
    _extract_interface_rows,
    _format_id_list,
    _guard_subnet_delete,
    _guard_supernet_delete,
    _normalize_ipam_object,
    _resolve_object_special_type,
    enforce_delete_guards,
    enforce_object_invariants,
    format_errors_for_abort,
    object_write_requires_ipam_license,
    object_delete_requires_ipam_license,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
OTHER_TYPE_ID: int = 99
CANDIDATE_OBJECT_ID: int = 500
PARENT_SUPERNET_ID: int = 600
SIBLING_SUBNET_ID: int = 700

PREV_RANGE: str = '10.0.0.0/24'
NEW_RANGE: str = '10.0.0.0/16'
INVALID_CIDR: str = 'not-a-cidr'

# Stable message fragments (IPAM errors carry only a 'message')
MSG_CIDR_INVALID: str = 'is not a canonical IPv4/IPv6 CIDR'
MSG_SUPERNET_TYPE_REQUIRED: str = "Supernet type ('dg-supernet-type') is required"
MSG_FAMILY_MISMATCH: str = 'does not match the address family'
MSG_SUPERNET_REFERENCED: str = 'Supernet is referenced by subnets'
MSG_SUBNET_REF_VLANS: str = 'Subnet is referenced by vlans'
MSG_SUBNET_REF_INTERFACES: str = 'Subnet is referenced by interface rows'

ENF_PATH: str = 'cmdb.framework.ipam.enforcement'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_object_doc(
    public_id: int | None,
    type_id: int | None,
    fields: list[dict[str, Any]] | None = None,
    mds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with optional fields and MDS sections."""
    doc: dict[str, Any] = {}

    if public_id is not None:
        doc[CmdbObjectKey.PUBLIC_ID] = public_id

    if type_id is not None:
        doc[CmdbObjectKey.TYPE_ID] = type_id

    if fields is not None:
        doc[CmdbObjectKey.FIELDS] = fields

    if mds is not None:
        doc[CmdbObjectKey.MULTI_DATA_SECTIONS] = mds

    return doc


def _make_field(name: Any, value: Any) -> dict[str, Any]:
    """Builds one entry for an object 'fields' list."""
    return {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}


def _make_interface_row(
    subnet_id: int | None,
    ip: str | None,
    interface_type: str | None = None,
    multi_data_id: int | None = None,
) -> dict[str, Any]:
    """
    Builds one MDS interface row with an optional dg-interface-type entry

    ``multi_data_id`` defaults to None so existing callers build LEGACY rows, which
    ``interface_row_keys`` keys by position. Pass an id to build a row the way the application
    actually creates one.
    """
    data: list[dict[str, Any]] = []

    if subnet_id is not None:
        data.append(_make_field(InterfaceField.SUBNET, subnet_id))

    if ip is not None:
        data.append(_make_field(InterfaceField.IP, ip))

    if interface_type is not None:
        data.append(_make_field(InterfaceField.TYPE, interface_type))

    row: dict[str, Any] = {CmdbObjectMdsRowKey.DATA: data}

    if multi_data_id is not None:
        row[CmdbObjectMdsRowKey.MULTI_DATA_ID] = multi_data_id

    return row


def _make_interface_section(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds an MDS section entry of the dg-ipam-interface template kind."""
    return {
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: rows,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              format_errors_for_abort                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_errors_for_abort_returns_prefix_only_for_empty_list() -> None:
    """No errors → only the 'IPAM validation failed: ' prefix is emitted"""
    assert format_errors_for_abort([]) == 'IPAM validation failed: '


def test_format_errors_for_abort_uses_message_when_present() -> None:
    """A single error with a message yields the message after the prefix"""
    errors = [{ValidationErrorKey.MESSAGE: 'IP not in subnet'}]

    assert format_errors_for_abort(errors) == 'IPAM validation failed: IP not in subnet'


def test_format_errors_for_abort_falls_back_to_unknown_when_message_missing() -> None:
    """An error dict without a message shows up as 'unknown error'"""
    assert format_errors_for_abort([{}]) == 'IPAM validation failed: unknown error'
    assert format_errors_for_abort(
        [{ValidationErrorKey.DETAILS: {'row_index': 1}}],
    ) == 'IPAM validation failed: unknown error'


def test_format_errors_for_abort_joins_multiple_errors_with_pipe_separator() -> None:
    """Two or more errors are joined with ' | ' between their messages"""
    errors = [
        {ValidationErrorKey.MESSAGE: 'first'},
        {ValidationErrorKey.MESSAGE: 'second'},
    ]

    assert format_errors_for_abort(errors) == 'IPAM validation failed: first | second'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _resolve_object_special_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_object_special_type_returns_none_when_get_type_returns_none() -> None:
    """No matching CmdbType for the id → None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = None

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_when_get_type_returns_empty_dict() -> None:
    """An empty type doc is treated as 'no type'"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_when_type_has_no_special_type_field() -> None:
    """A type doc that doesn't carry a special_type yields None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: None}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


def test_resolve_object_special_type_returns_none_for_unrecognized_special_type_value() -> None:
    """A special_type string that doesn't match any SpecialType member is treated as None"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: 'NOT_A_SPECIAL_TYPE'}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) is None


@pytest.mark.parametrize('raw_value, expected', [
    ('SUBNET', SpecialType.SUBNET),
    ('SUPERNET', SpecialType.SUPERNET),
    ('VLAN', SpecialType.VLAN),
])
def test_resolve_object_special_type_returns_enum_for_valid_value(raw_value: str, expected: SpecialType) -> None:
    """A recognized SpecialType value is returned as the corresponding enum member"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: raw_value}

    assert _resolve_object_special_type(types_manager, SUBNET_TYPE_ID) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   _coerce_int                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value', [None, '', 0])
def test_coerce_int_returns_none_for_empty_or_zero_sentinel(value: Any) -> None:
    """None, empty string and literal 0 are treated as 'absent' and yield None"""
    assert _coerce_int(value) is None


@pytest.mark.parametrize('value, expected', [
    (42, 42),
    ('42', 42),
    (-5, -5),
])
def test_coerce_int_converts_valid_int_or_int_string(value: Any, expected: int) -> None:
    """Numeric ints and int-formatted strings are coerced to int"""
    assert _coerce_int(value) == expected


@pytest.mark.parametrize('value', ['abc', '12.5', [], {}, object()])
def test_coerce_int_returns_none_for_unconvertible_input(value: Any) -> None:
    """A value that int() cannot parse yields None instead of raising"""
    assert _coerce_int(value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _extract_interface_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_interface_rows_returns_empty_when_no_mds_sections() -> None:
    """An object with no multi_data_sections list yields no rows"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    assert not _extract_interface_rows(obj)


def test_extract_interface_rows_skips_non_interface_sections() -> None:
    """Sections whose section_id is not the interface template are ignored"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        {
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
            CmdbObjectMdsKey.VALUES: [_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')],
        },
    ])

    assert not _extract_interface_rows(obj)


def test_extract_interface_rows_returns_subnet_and_ip_for_complete_row() -> None:
    """A complete row yields a (index, subnet_ref, ip) tuple"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, '10.0.0.5', None)]


def test_extract_interface_rows_yields_none_pair_for_empty_row() -> None:
    """A row with empty data still emits a tuple — with both slots None — preserving its index"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([{CmdbObjectMdsRowKey.DATA: []}]),
    ])

    assert _extract_interface_rows(obj) == [(0, None, None, None)]


def test_extract_interface_rows_treats_empty_string_ip_as_none() -> None:
    """An IP value that is an empty string is normalized to None (interface IP is optional)"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '')]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, None, None)]


def test_extract_interface_rows_passes_interface_type_token_through() -> None:
    """A non-empty dg-interface-type value lands in the tuple's fourth slot verbatim"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5', interface_type=IpAddressFamily.IPV4),
        ]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, '10.0.0.5', IpAddressFamily.IPV4)]


def test_extract_interface_rows_treats_empty_string_type_as_none() -> None:
    """An empty dg-interface-type value is normalized to None so the family check is skipped"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5', interface_type='')]),
    ])

    assert _extract_interface_rows(obj) == [(0, SIBLING_SUBNET_ID, '10.0.0.5', None)]


def test_extract_interface_rows_preserves_row_indices_in_order() -> None:
    """Row indices reflect the position inside the section's values list"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.1'),
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.2'),
            _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.3'),
        ]),
    ])

    indices = [row[0] for row in _extract_interface_rows(obj)]
    assert indices == [0, 1, 2]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _format_id_list                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_format_id_list_returns_empty_string_for_no_refs() -> None:
    """No references → empty string"""
    assert _format_id_list([]) == ''


def test_format_id_list_returns_single_id_without_separator() -> None:
    """One reference → just its id, no comma"""
    assert _format_id_list([{CmdbObjectKey.PUBLIC_ID: 7}]) == '7'


def test_format_id_list_joins_multiple_ids_with_comma_separator() -> None:
    """Multiple references → comma-separated id string in the input order"""
    refs = [
        {CmdbObjectKey.PUBLIC_ID: 7},
        {CmdbObjectKey.PUBLIC_ID: 9},
        {CmdbObjectKey.PUBLIC_ID: 11},
    ]

    assert _format_id_list(refs) == '7, 9, 11'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _enforce_subnet_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_candidate(
    public_id: int | None,
    network_range: str,
    parent_id: int | None = None,
    subnet_type: Any = None,
) -> dict[str, Any]:
    """Builds a SUBNET candidate CmdbObject doc, with an optional address-family selector."""
    fields = [_make_field(SubnetField.NETWORK_RANGE, network_range)]

    if parent_id is not None:
        fields.append(_make_field(SubnetField.PARENT_SUPERNET, parent_id))

    if subnet_type is not None:
        fields.append(_make_field(SubnetField.TYPE, subnet_type))

    return _make_object_doc(public_id=public_id, type_id=SUBNET_TYPE_ID, fields=fields)


def test_enforce_subnet_object_on_insert_runs_validate_subnet() -> None:
    """No previous_object → validate_subnet drives the result and exclude_subnet_id is None"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        errors = _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert not errors
    validate_mock.assert_called_once()
    assert validate_mock.call_args.kwargs['exclude_subnet_id'] is None


def test_enforce_subnet_object_on_update_passes_candidate_id_as_exclude() -> None:
    """previous_object set → exclude_subnet_id is forwarded so candidate doesn't collide with itself"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)
    previous = _make_subnet_candidate(CANDIDATE_OBJECT_ID, PREV_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert validate_mock.call_args.kwargs['exclude_subnet_id'] == CANDIDATE_OBJECT_ID


def test_enforce_subnet_object_allows_range_change_even_when_interface_ips_would_orphan() -> None:
    """
    Range change to a smaller / disjoint CIDR is permitted: validate_subnet decides on its own,
    no separate guard blocks the save. Interface IPs that no longer fit surface as
    is_valid=False in the subnet IP-Übersicht instead
    """
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, parent_id=PARENT_SUPERNET_ID)
    previous = _make_subnet_candidate(CANDIDATE_OBJECT_ID, PREV_RANGE, parent_id=PARENT_SUPERNET_ID)

    with patch(f'{ENF_PATH}.validate_subnet', return_value=[]) as validate_mock:
        errors = _enforce_subnet_object(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert not errors
    validate_mock.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _enforce_supernet_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_supernet_candidate(
    public_id: int | None,
    network_range: Any,
    supernet_type: Any = None,
) -> dict[str, Any]:
    """Builds a SUPERNET candidate CmdbObject doc, with an optional address-family selector."""
    fields: list[dict[str, Any]] = [_make_field(SupernetField.NETWORK_RANGE, network_range)]

    if supernet_type is not None:
        fields.append(_make_field(SupernetField.TYPE, supernet_type))

    return _make_object_doc(public_id=public_id, type_id=SUPERNET_TYPE_ID, fields=fields)


def test_enforce_supernet_object_emits_cidr_invalid_for_unparseable_range() -> None:
    """An invalid CIDR string on the candidate yields a canonical-CIDR error"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, INVALID_CIDR)

    errors = _enforce_supernet_object(candidate)

    assert len(errors) == 1
    assert MSG_CIDR_INVALID in errors[0][ValidationErrorKey.MESSAGE]


def test_enforce_supernet_object_reports_type_missing_for_canonical_cidr_without_type() -> None:
    """A canonical CIDR with no type selector is rejected: the selector is required"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE)

    errors = _enforce_supernet_object(candidate)

    assert len(errors) == 1
    assert MSG_SUPERNET_TYPE_REQUIRED in errors[0][ValidationErrorKey.MESSAGE]


def test_enforce_supernet_object_returns_empty_when_type_matches_cidr_family() -> None:
    """An ipv4 selector on an IPv4 CIDR (and ipv6 on IPv6) passes"""
    ipv4 = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, supernet_type=IpAddressFamily.IPV4)
    ipv6 = _make_supernet_candidate(CANDIDATE_OBJECT_ID, '2001:db8::/32', supernet_type=IpAddressFamily.IPV6)

    assert not _enforce_supernet_object(ipv4)
    assert not _enforce_supernet_object(ipv6)


def test_enforce_supernet_object_emits_type_family_mismatch_when_selector_disagrees() -> None:
    """An ipv6 selector on an IPv4 CIDR is rejected with TYPE_FAMILY_MISMATCH"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, supernet_type=IpAddressFamily.IPV6)

    errors = _enforce_supernet_object(candidate)

    assert len(errors) == 1
    assert MSG_FAMILY_MISMATCH in errors[0][ValidationErrorKey.MESSAGE]


def test_enforce_supernet_object_allows_range_change_even_when_child_subnets_would_orphan() -> None:
    """
    Range change is permitted regardless of whether existing child subnets would now fall
    outside the new range: those children surface as is_valid=False in the supernet overview
    so the user can repair or detach them after the fact, instead of the save being blocked
    """
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, NEW_RANGE, supernet_type=IpAddressFamily.IPV4)

    assert not _enforce_supernet_object(candidate)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _enforce_vlan_object                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_vlan_object_returns_empty_when_no_subnet_ref_present() -> None:
    """A VLAN candidate without a subnet reference does not invoke validate_vlan"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID, fields=[])

    with patch(f'{ENF_PATH}.validate_vlan') as validate_mock:
        errors = _enforce_vlan_object(MagicMock(), MagicMock(), candidate)

    assert not errors
    validate_mock.assert_not_called()


def test_enforce_vlan_object_delegates_to_validate_vlan_with_subnet_id() -> None:
    """A VLAN candidate with a subnet_ref invokes validate_vlan with the coerced id"""
    candidate = _make_object_doc(
        CANDIDATE_OBJECT_ID, VLAN_TYPE_ID,
        fields=[_make_field(VlanField.SUBNET_REF, '700')],
    )
    expected_error = {ValidationErrorKey.MESSAGE: 'subnet not found'}

    with patch(f'{ENF_PATH}.validate_vlan', return_value=[expected_error]) as validate_mock:
        errors = _enforce_vlan_object(MagicMock(), MagicMock(), candidate)

    assert errors == [expected_error]
    validate_mock.assert_called_once()
    assert validate_mock.call_args.args[2] == 700


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _enforce_interface_rows                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_interface_rows_returns_empty_when_no_rows_present() -> None:
    """An object with no interface rows does not invoke validate_interface_rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}.validate_interface_rows') as validate_mock:
        errors = _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert not errors
    validate_mock.assert_not_called()


def test_enforce_interface_rows_on_insert_passes_none_as_exclude_object_id() -> None:
    """On insert (no previous_object) the exclude_object_id is None"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])

    with patch(f'{ENF_PATH}.validate_interface_rows', return_value=[]) as validate_mock:
        _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=None)

    assert validate_mock.call_args.args[3] is None


def test_enforce_interface_rows_on_update_passes_candidate_id_as_exclude_object_id() -> None:
    """On update the candidate's own public_id is passed as exclude_object_id"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[
        _make_interface_section([_make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5')]),
    ])
    previous = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}.validate_interface_rows', return_value=[]) as validate_mock:
        _enforce_interface_rows(MagicMock(), MagicMock(), candidate, previous_object=previous)

    assert validate_mock.call_args.args[3] == CANDIDATE_OBJECT_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                     CANONICALISATION (ON STORE)                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_canonical_cidr_normalizes_ipv6_leaves_ipv4_and_unparsable() -> None:
    """_canonical_cidr lower-cases / compresses IPv6, leaves canonical IPv4 and bad input untouched"""
    assert _canonical_cidr('2001:DB8:0:0::/32') == '2001:db8::/32'
    assert _canonical_cidr('10.0.0.0/24') == '10.0.0.0/24'
    assert _canonical_cidr('not-a-cidr') == 'not-a-cidr'
    assert _canonical_cidr(None) is None


def test_canonical_ip_normalizes_ipv6_leaves_ipv4_and_unparsable() -> None:
    """_canonical_ip lower-cases / compresses IPv6, leaves canonical IPv4 and bad input untouched"""
    assert _canonical_ip('2001:DB8::0001') == '2001:db8::1'
    assert _canonical_ip('10.0.0.5') == '10.0.0.5'
    assert _canonical_ip('nonsense') == 'nonsense'


def test_canonicalize_interface_ips_rewrites_rows_in_place() -> None:
    """Every dg-ipam-interface row's IP value is rewritten to canonical form"""
    candidate = _make_object_doc(
        CANDIDATE_OBJECT_ID, OTHER_TYPE_ID,
        mds=[_make_interface_section([_make_interface_row(700, '2001:DB8::0001')])],
    )

    _canonicalize_interface_ips(candidate)

    ip_entry = candidate[CmdbObjectKey.MULTI_DATA_SECTIONS][0][CmdbObjectMdsKey.VALUES][0][CmdbObjectMdsRowKey.DATA][1]
    assert ip_entry[CmdbObjectFieldKey.VALUE] == '2001:db8::1'


def test_normalize_ipam_object_canonicalizes_subnet_range_in_place() -> None:
    """A SUBNET candidate's dg-network-range is canonicalised in place"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, '2001:DB8:0:0::/48', subnet_type=IpAddressFamily.IPV6)

    _normalize_ipam_object(candidate, SpecialType.SUBNET)

    assert extract_field_value(candidate, SubnetField.NETWORK_RANGE) == '2001:db8::/48'


def test_normalize_ipam_object_canonicalizes_supernet_range_in_place() -> None:
    """A SUPERNET candidate's dg-network-range is canonicalised in place"""
    candidate = _make_supernet_candidate(CANDIDATE_OBJECT_ID, '2001:DB8::/32', supernet_type=IpAddressFamily.IPV6)

    _normalize_ipam_object(candidate, SpecialType.SUPERNET)

    assert extract_field_value(candidate, SupernetField.NETWORK_RANGE) == '2001:db8::/32'


def test_enforce_object_invariants_canonicalizes_ipv6_range_before_save() -> None:
    """enforce_object_invariants normalises the candidate in place so the saved value is canonical"""
    candidate = _make_subnet_candidate(CANDIDATE_OBJECT_ID, '2001:DB8::/32', subnet_type=IpAddressFamily.IPV6)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET):
        errors = enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    assert not errors
    assert extract_field_value(candidate, SubnetField.NETWORK_RANGE) == '2001:db8::/32'


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _guard_supernet_delete                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_guard_supernet_delete_returns_empty_when_no_subnets_reference_it() -> None:
    """No referencing subnets → empty guard error list"""
    with patch(f'{ENF_PATH}.find_subnets_referencing_supernet', return_value=[]):
        errors = _guard_supernet_delete(MagicMock(), MagicMock(), PARENT_SUPERNET_ID)

    assert not errors


def test_guard_supernet_delete_returns_guard_error_when_subnets_reference_it() -> None:
    """Referencing subnets → single guard error naming the referencing subnet ids in the message"""
    refs = [{CmdbObjectKey.PUBLIC_ID: 7, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_subnets_referencing_supernet', return_value=refs):
        errors = _guard_supernet_delete(MagicMock(), MagicMock(), PARENT_SUPERNET_ID)

    assert len(errors) == 1
    message = errors[0][ValidationErrorKey.MESSAGE]
    assert MSG_SUPERNET_REFERENCED in message
    assert '7' in message


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _guard_subnet_delete                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_guard_subnet_delete_returns_empty_when_no_references_exist() -> None:
    """No vlans and no interface rows reference the subnet → empty"""
    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=[]):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert not errors


def test_guard_subnet_delete_returns_only_vlan_error_when_only_vlans_reference_it() -> None:
    """Vlans referencing the subnet produce a single VLAN guard error"""
    vlan_refs = [{CmdbObjectKey.PUBLIC_ID: 8, CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=vlan_refs), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=[]):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert len(errors) == 1
    assert MSG_SUBNET_REF_VLANS in errors[0][ValidationErrorKey.MESSAGE]


def test_guard_subnet_delete_returns_only_interface_error_when_only_interfaces_reference_it() -> None:
    """Interface rows referencing the subnet produce a single INTERFACES guard error"""
    interface_refs = [{CmdbObjectKey.PUBLIC_ID: 9, CmdbObjectKey.TYPE_ID: OTHER_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=interface_refs):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    assert len(errors) == 1
    assert MSG_SUBNET_REF_INTERFACES in errors[0][ValidationErrorKey.MESSAGE]


def test_guard_subnet_delete_returns_both_errors_when_both_kinds_of_reference_exist() -> None:
    """Both kinds of references produce two guard errors (one per kind)"""
    vlan_refs = [{CmdbObjectKey.PUBLIC_ID: 8, CmdbObjectKey.TYPE_ID: VLAN_TYPE_ID}]
    interface_refs = [{CmdbObjectKey.PUBLIC_ID: 9, CmdbObjectKey.TYPE_ID: OTHER_TYPE_ID}]

    with patch(f'{ENF_PATH}.find_vlans_referencing_subnet', return_value=vlan_refs), \
         patch(f'{ENF_PATH}.find_interfaces_referencing_subnet', return_value=interface_refs):
        errors = _guard_subnet_delete(MagicMock(), MagicMock(), SIBLING_SUBNET_ID)

    messages = ' '.join(e[ValidationErrorKey.MESSAGE] for e in errors)
    assert len(errors) == 2
    assert MSG_SUBNET_REF_VLANS in messages
    assert MSG_SUBNET_REF_INTERFACES in messages


# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_object_invariants                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_object_invariants_returns_empty_when_type_id_is_not_int() -> None:
    """A candidate without an int type_id short-circuits with no errors"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, type_id=None)

    errors = enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    assert not errors


def test_enforce_object_invariants_dispatches_to_supernet_enforcer() -> None:
    """A SUPERNET-typed candidate routes to _enforce_supernet_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUPERNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUPERNET), \
         patch(f'{ENF_PATH}._enforce_supernet_object', return_value=[]) as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]) as interface_mock:
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    supernet_mock.assert_called_once()
    interface_mock.assert_called_once()
    subnet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_dispatches_to_subnet_enforcer() -> None:
    """A SUBNET-typed candidate routes to _enforce_subnet_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object', return_value=[]) as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]):
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    subnet_mock.assert_called_once()
    supernet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_dispatches_to_vlan_enforcer() -> None:
    """A VLAN-typed candidate routes to _enforce_vlan_object plus interface rows"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.VLAN), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object', return_value=[]) as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]):
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    vlan_mock.assert_called_once()
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()


def test_enforce_object_invariants_runs_interface_rows_for_non_special_type() -> None:
    """A non-IPAM-SpecialType object still runs the interface-row check (rows are global)"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=None), \
         patch(f'{ENF_PATH}._enforce_supernet_object') as supernet_mock, \
         patch(f'{ENF_PATH}._enforce_subnet_object') as subnet_mock, \
         patch(f'{ENF_PATH}._enforce_vlan_object') as vlan_mock, \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[]) as interface_mock:
        enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    interface_mock.assert_called_once()
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()
    vlan_mock.assert_not_called()


def test_enforce_object_invariants_accumulates_errors_from_both_layers() -> None:
    """Errors from the per-SpecialType enforcer and the interface-row enforcer are combined"""
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)
    subnet_err = {ValidationErrorKey.MESSAGE: 'subnet_err'}
    interface_err = {ValidationErrorKey.MESSAGE: 'interface_err'}

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._enforce_subnet_object', return_value=[subnet_err]), \
         patch(f'{ENF_PATH}._enforce_interface_rows', return_value=[interface_err]):
        errors = enforce_object_invariants(MagicMock(), MagicMock(), candidate)

    messages = {e[ValidationErrorKey.MESSAGE] for e in errors}
    assert messages == {'subnet_err', 'interface_err'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                           enforce_delete_guards                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_enforce_delete_guards_returns_empty_for_invalid_type_id() -> None:
    """A target object without an int type_id short-circuits with no errors"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, type_id=None)

    errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert not errors


def test_enforce_delete_guards_returns_empty_for_invalid_object_id() -> None:
    """A target object without an int public_id short-circuits with no errors"""
    target = _make_object_doc(public_id=None, type_id=SUPERNET_TYPE_ID)

    errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert not errors


def test_enforce_delete_guards_dispatches_to_supernet_guard_for_supernet_target() -> None:
    """A SUPERNET target routes to _guard_supernet_delete"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, SUPERNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUPERNET), \
         patch(f'{ENF_PATH}._guard_supernet_delete', return_value=[]) as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        enforce_delete_guards(MagicMock(), MagicMock(), target)

    supernet_mock.assert_called_once()
    subnet_mock.assert_not_called()


def test_enforce_delete_guards_dispatches_to_subnet_guard_for_subnet_target() -> None:
    """A SUBNET target routes to _guard_subnet_delete"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.SUBNET), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete', return_value=[]) as subnet_mock:
        enforce_delete_guards(MagicMock(), MagicMock(), target)

    subnet_mock.assert_called_once()
    supernet_mock.assert_not_called()


def test_enforce_delete_guards_returns_empty_for_vlan_target() -> None:
    """VLAN objects have no IPAM references pointing at them, so delete is unconditionally allowed"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, VLAN_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=SpecialType.VLAN), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert not errors
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()


def test_enforce_delete_guards_returns_empty_for_non_special_type_target() -> None:
    """A non-IPAM SpecialType object passes through unaffected"""
    target = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID)

    with patch(f'{ENF_PATH}._resolve_object_special_type', return_value=None), \
         patch(f'{ENF_PATH}._guard_supernet_delete') as supernet_mock, \
         patch(f'{ENF_PATH}._guard_subnet_delete') as subnet_mock:
        errors = enforce_delete_guards(MagicMock(), MagicMock(), target)

    assert not errors
    supernet_mock.assert_not_called()
    subnet_mock.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          LICENSE GATING (IPAM feature)                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def _license_types_manager(special_type_by_id: dict[int, str]) -> MagicMock:
    """Builds a types_manager mock whose get_type marks the given ids as the given SpecialType"""
    manager = MagicMock()

    def _get_type(type_id: int) -> dict[str, Any]:
        special_type = special_type_by_id.get(type_id)

        return {TypeSchemaKey.SPECIAL_TYPE: special_type} if special_type else {}

    manager.get_type.side_effect = _get_type

    return manager


def _interface_object(public_id: int | None, type_id: int, subnet_ids: list[int | None]) -> dict[str, Any]:
    """Builds a regular object with one dg-ipam-interface row per entry in subnet_ids"""
    rows = [_make_interface_row(subnet_id, '10.0.0.5') for subnet_id in subnet_ids]

    return _make_object_doc(public_id, type_id, mds=[_make_interface_section(rows)])


def test_write_requires_license_for_special_type_object() -> None:
    """Any write to an IPAM special-type object requires the IPAM license (flat block)"""
    types_manager = _license_types_manager({SUBNET_TYPE_ID: SpecialType.SUBNET.value})
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID, fields=[_make_field('dg-name', 'x')])

    assert object_write_requires_ipam_license(types_manager, candidate) is True


def test_write_requires_license_when_insert_adds_interface_subnet() -> None:
    """Creating a regular object with an interface row carrying a subnet requires the license"""
    types_manager = _license_types_manager({})
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is True


def test_write_allows_insert_interface_without_subnet() -> None:
    """Creating a regular object whose interface row selects no subnet is not gated"""
    types_manager = _license_types_manager({})
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [None])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is False


def test_write_allows_regular_object_without_interface() -> None:
    """A plain regular object write touches no IPAM surface"""
    types_manager = _license_types_manager({})
    candidate = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, fields=[_make_field('dg-name', 'x')])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=None) is False


def test_write_allows_resaving_unchanged_interface_subnet() -> None:
    """Re-saving a regular object with the same interface subnet is allowed (no link added/changed)"""
    types_manager = _license_types_manager({})
    previous = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=previous) is False


def test_write_requires_license_when_interface_subnet_changes() -> None:
    """Switching an interface row to a different subnet requires the license"""
    types_manager = _license_types_manager({})
    previous = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [PARENT_SUPERNET_ID])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=previous) is True


def test_write_allows_clearing_interface_subnet() -> None:
    """Removing the subnet from an interface row (keeping the interface) is allowed"""
    types_manager = _license_types_manager({})
    previous = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [None])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=previous) is False


def test_write_requires_license_when_adding_a_second_subnet_row() -> None:
    """Adding a new interface row that carries a subnet requires the license"""
    types_manager = _license_types_manager({})
    previous = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])
    candidate = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID, PARENT_SUPERNET_ID])

    assert object_write_requires_ipam_license(types_manager, candidate, previous_object=previous) is True


def test_delete_requires_license_for_special_type_object() -> None:
    """Deleting an IPAM special-type object requires the IPAM license"""
    types_manager = _license_types_manager({SUBNET_TYPE_ID: SpecialType.SUBNET.value})
    target = _make_object_doc(CANDIDATE_OBJECT_ID, SUBNET_TYPE_ID, fields=[_make_field('dg-name', 'x')])

    assert object_delete_requires_ipam_license(types_manager, target) is True


def test_delete_allows_regular_object_even_with_interface_subnet() -> None:
    """Deleting a regular object is never gated, even if it links a subnet on an interface"""
    types_manager = _license_types_manager({})
    target = _interface_object(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, [SIBLING_SUBNET_ID])

    assert object_delete_requires_ipam_license(types_manager, target) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                     _extract_interface_rows - the row key is the row ID                                             #
# -------------------------------------------------------------------------------------------------------------------- #
#
# The first element of each tuple doubles as the self-exclusion key against the stored object, so it
# has to be the row's multi_data_id. Emitting the POSITION here (with the stored side also keyed by
# position) is what made an edited interface row collide with its own stored row once the positions
# had shifted.

FIRST_ROW_ID: int = 1


def test_extract_interface_rows_keys_rows_by_their_row_id() -> None:
    """A modern row's key is its multi_data_id, not its index in the section"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[_make_interface_section([
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5', multi_data_id=FIRST_ROW_ID),
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.6', multi_data_id=7),
    ])])

    assert [row_key for row_key, _, _, _ in _extract_interface_rows(obj)] == [FIRST_ROW_ID, 7]


def test_extract_interface_rows_key_of_a_single_modern_row_is_not_zero() -> None:
    """The off-by-one behind the bug, pinned on the candidate side too"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[_make_interface_section([
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5', multi_data_id=FIRST_ROW_ID),
    ])])

    assert [row_key for row_key, _, _, _ in _extract_interface_rows(obj)] == [FIRST_ROW_ID]


def test_extract_interface_rows_falls_back_to_positions_for_legacy_rows() -> None:
    """Rows with no multi_data_id keep the previous positional keys, so nothing regresses"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[_make_interface_section([
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5'),
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.6'),
    ])])

    assert [row_key for row_key, _, _, _ in _extract_interface_rows(obj)] == [0, 1]


def test_extract_interface_rows_still_reads_each_rows_values() -> None:
    """Keying by id must not disturb the subnet / ip / type each tuple carries"""
    obj = _make_object_doc(CANDIDATE_OBJECT_ID, OTHER_TYPE_ID, mds=[_make_interface_section([
        _make_interface_row(SIBLING_SUBNET_ID, '10.0.0.5', 'ipv4', multi_data_id=3),
    ])])

    assert _extract_interface_rows(obj) == [(3, SIBLING_SUBNET_ID, '10.0.0.5', 'ipv4')]
