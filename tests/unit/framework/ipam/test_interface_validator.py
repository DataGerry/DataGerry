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
Unit tests for cmdb.framework.ipam.interface_validator

Covers the pure helpers (membership, collision walking, row matching, batch completeness and
intra-submission duplicate checks), the DB-touching helpers (_load_subnet_object,
_check_ip_uniqueness - Mongo query filter shapes pinned via assert_called_once_with) and the
two orchestrators (validate_interface, validate_interface_rows). For the orchestrators the
internal helpers are patched at the module path so each test verifies orchestration in
isolation; every helper has its own dedicated tests in this file. Fixture documents reference
CmdbObjectKey / CmdbObjectMdsKey / CmdbObjectMdsRowKey / CmdbObjectFieldKey / InterfaceField /
IpamSection enums for structural keys, per the no-magic-values rule
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.utils import ValidationErrorKey, build_error
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
    IpAddressFamily,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.framework.ipam.cidr import parse_cidr, parse_ip
from cmdb.framework.ipam.interface_validator import (
    InterfaceErrorCode,
    _check_ip_format,
    _check_ip_membership,
    _check_ip_uniqueness,
    _check_row_type_against_ip,
    _check_row_type_against_subnet,
    _collect_collision_errors,
    _extract_subnet_network,
    _load_subnet_object,
    _load_subnets_by_ids,
    _row_matches,
    find_intra_submission_duplicates,
    find_missing_types,
    find_subnet_without_ip,
    find_type_family_mismatches,
    validate_interface,
    validate_interface_rows,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.ipam.interface_validator'
SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 201
OWNER_OBJECT_ID: int = 301


def _make_interface_row(subnet_id: int | None, ip: str | None) -> dict[str, Any]:
    """Builds one MDS row matching the interface section template's row shape."""
    data: list[dict[str, Any]] = []

    if subnet_id is not None:
        data.append(
            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: subnet_id},
        )

    if ip is not None:
        data.append(
            {CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: ip},
        )

    return {CmdbObjectMdsRowKey.DATA: data}


def _make_object(public_id: int, interface_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with one dg-ipam-interface MDS section."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: interface_rows,
            },
        ],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _check_ip_membership                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_ip_membership_passes_for_regular_host_in_subnet() -> None:
    """An assignable host inside /24 produces no errors"""
    errors = _check_ip_membership(IPv4Address('10.0.0.5'), IPv4Network('10.0.0.0/24'))

    assert not errors


def test_check_ip_membership_short_circuits_when_ip_outside_subnet() -> None:
    """When the IP is not in the subnet, only IP_NOT_IN_SUBNET is emitted (no IP_RESERVED follow-up)"""
    errors = _check_ip_membership(IPv4Address('192.168.1.1'), IPv4Network('10.0.0.0/24'))

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_NOT_IN_SUBNET
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.IP_ADDRESS] == '192.168.1.1'
    assert details[IpamValidationDetailKey.SUBNET_RANGE] == '10.0.0.0/24'


@pytest.mark.parametrize('reserved_ip', ['10.0.0.0', '10.0.0.255'])
def test_check_ip_membership_flags_network_and_broadcast_for_slash24(reserved_ip: str) -> None:
    """Network and broadcast addresses of /<=30 produce IP_RESERVED"""
    errors = _check_ip_membership(IPv4Address(reserved_ip), IPv4Network('10.0.0.0/24'))

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_RESERVED
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.IP_ADDRESS] == reserved_ip


@pytest.mark.parametrize('point_to_point_ip', ['10.0.0.0', '10.0.0.1'])
def test_check_ip_membership_allows_both_endpoints_of_slash31(point_to_point_ip: str) -> None:
    """/31 endpoints are assignable under the point-to-point policy (no IP_RESERVED)"""
    errors = _check_ip_membership(IPv4Address(point_to_point_ip), IPv4Network('10.0.0.0/31'))

    assert not errors


def test_check_ip_membership_allows_single_host_of_slash32() -> None:
    """/32 host route is assignable under the host-route policy (no IP_RESERVED)"""
    errors = _check_ip_membership(IPv4Address('10.0.0.5'), IPv4Network('10.0.0.5/32'))

    assert not errors


def test_check_ip_membership_passes_for_ipv6_host_in_ipv6_subnet() -> None:
    """An IPv6 host inside an IPv6 subnet produces no errors"""
    errors = _check_ip_membership(parse_ip('2001:db8::5'), parse_cidr('2001:db8::/64'))

    assert not errors


def test_check_ip_membership_allows_ipv6_network_address_no_reservation() -> None:
    """IPv6 reserves no network/broadcast address, so the all-zeros host is assignable"""
    errors = _check_ip_membership(parse_ip('2001:db8::'), parse_cidr('2001:db8::/64'))

    assert not errors


def test_check_ip_membership_rejects_ipv4_ip_in_ipv6_subnet() -> None:
    """A cross-family pairing (IPv4 IP, IPv6 subnet) is reported as not-in-subnet, never raises"""
    errors = _check_ip_membership(parse_ip('10.0.0.5'), parse_cidr('2001:db8::/64'))

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_NOT_IN_SUBNET


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 _row_matches                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_row_matches_returns_true_when_both_subnet_and_ip_present() -> None:
    """A row with both the candidate subnet ref AND IP matches"""
    row = _make_interface_row(subnet_id=42, ip='10.0.0.5')

    assert _row_matches(row, subnet_object_id=42, ip_address='10.0.0.5') is True


def test_row_matches_returns_false_when_only_subnet_present() -> None:
    """A row with the matching subnet ref but a different IP does not match"""
    row = _make_interface_row(subnet_id=42, ip='10.0.0.99')

    assert _row_matches(row, subnet_object_id=42, ip_address='10.0.0.5') is False


def test_row_matches_returns_false_when_only_ip_present() -> None:
    """A row with the matching IP but a different subnet ref does not match"""
    row = _make_interface_row(subnet_id=99, ip='10.0.0.5')

    assert _row_matches(row, subnet_object_id=42, ip_address='10.0.0.5') is False


def test_row_matches_returns_false_when_row_is_empty() -> None:
    """A row with no data entries does not match"""
    empty_row = {CmdbObjectMdsRowKey.DATA: []}

    assert _row_matches(empty_row, subnet_object_id=42, ip_address='10.0.0.5') is False


def test_row_matches_returns_false_when_data_key_missing() -> None:
    """A row missing the 'data' key is treated as empty rather than raising"""
    assert _row_matches({}, subnet_object_id=42, ip_address='10.0.0.5') is False


def test_row_matches_ignores_irrelevant_fields_in_data() -> None:
    """Extra entries (e.g. MAC) don't affect the subnet+IP match"""
    row = {
        CmdbObjectMdsRowKey.DATA: [
            {CmdbObjectFieldKey.NAME: InterfaceField.MAC, CmdbObjectFieldKey.VALUE: 'aa:bb:cc:dd:ee:ff'},
            {CmdbObjectFieldKey.NAME: InterfaceField.SUBNET, CmdbObjectFieldKey.VALUE: 42},
            {CmdbObjectFieldKey.NAME: InterfaceField.IP, CmdbObjectFieldKey.VALUE: '10.0.0.5'},
        ],
    }

    assert _row_matches(row, subnet_object_id=42, ip_address='10.0.0.5') is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _collect_collision_errors                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_collision_errors_reports_single_collision() -> None:
    """One candidate object whose row matches the (subnet, IP) pair surfaces a single error"""
    candidates = [_make_object(
        public_id=7,
        interface_rows=[_make_interface_row(subnet_id=42, ip='10.0.0.5')],
    )]

    errors = _collect_collision_errors(
        candidates,
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=None,
        exclude_row_index=None,
    )

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_DUPLICATE
    assert details[IpamValidationDetailKey.OBJECT_ID] == 7
    assert details[IpamValidationDetailKey.ROW_INDEX] == 0


def test_collect_collision_errors_skips_excluded_self_row() -> None:
    """The candidate's own pre-edit row (exclude pair) is not flagged as a collision"""
    candidates = [_make_object(
        public_id=7,
        interface_rows=[_make_interface_row(subnet_id=42, ip='10.0.0.5')],
    )]

    errors = _collect_collision_errors(
        candidates,
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=7,
        exclude_row_index=0,
    )

    assert not errors


def test_collect_collision_errors_reports_other_row_on_same_object() -> None:
    """Exclusion pair is per-row: a different row on the same object still collides"""
    candidates = [_make_object(
        public_id=7,
        interface_rows=[
            _make_interface_row(subnet_id=42, ip='10.0.0.99'),
            _make_interface_row(subnet_id=42, ip='10.0.0.5'),
        ],
    )]

    errors = _collect_collision_errors(
        candidates,
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=7,
        exclude_row_index=0,
    )

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 1


def test_collect_collision_errors_ignores_non_interface_sections() -> None:
    """Sections whose section_id is not the interface template are skipped"""
    candidates = [{
        CmdbObjectKey.PUBLIC_ID: 7,
        CmdbObjectKey.MULTI_DATA_SECTIONS: [
            {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
                CmdbObjectMdsKey.VALUES: [_make_interface_row(subnet_id=42, ip='10.0.0.5')],
            },
        ],
    }]

    errors = _collect_collision_errors(
        candidates,
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=None,
        exclude_row_index=None,
    )

    assert not errors


def test_collect_collision_errors_returns_empty_for_no_candidates() -> None:
    """No candidate objects means no collisions"""
    errors = _collect_collision_errors(
        candidates=[],
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=None,
        exclude_row_index=None,
    )

    assert not errors


def test_collect_collision_errors_reports_one_error_per_matching_row_across_objects() -> None:
    """Two distinct objects with matching rows produce two errors"""
    candidates = [
        _make_object(public_id=7, interface_rows=[_make_interface_row(subnet_id=42, ip='10.0.0.5')]),
        _make_object(public_id=9, interface_rows=[_make_interface_row(subnet_id=42, ip='10.0.0.5')]),
    ]

    errors = _collect_collision_errors(
        candidates,
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=None,
        exclude_row_index=None,
    )

    assert len(errors) == 2
    reported_ids = {e[ValidationErrorKey.DETAILS][IpamValidationDetailKey.OBJECT_ID] for e in errors}
    assert reported_ids == {7, 9}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       find_intra_submission_duplicates                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_intra_submission_duplicates_returns_empty_for_unique_rows() -> None:
    """Rows with distinct (subnet, IP) pairs produce no errors"""
    rows = [
        (0, 1, '10.0.0.1', None),
        (1, 1, '10.0.0.2', None),
        (2, 2, '10.0.0.1', None),
    ]

    assert not find_intra_submission_duplicates(rows)


def test_find_intra_submission_duplicates_flags_second_occurrence() -> None:
    """The first occurrence wins; the second occurrence is reported with both row indices"""
    rows = [
        (0, 1, '10.0.0.1', None),
        (1, 1, '10.0.0.1', None),
    ]

    errors = find_intra_submission_duplicates(rows)

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_DUPLICATE
    assert details[IpamValidationDetailKey.FIRST_ROW_INDEX] == 0
    assert details[IpamValidationDetailKey.DUPLICATE_ROW_INDEX] == 1


def test_find_intra_submission_duplicates_flags_each_subsequent_occurrence() -> None:
    """Three identical rows produce two errors (second and third both against the first)"""
    rows = [
        (0, 1, '10.0.0.1', None),
        (1, 1, '10.0.0.1', None),
        (2, 1, '10.0.0.1', None),
    ]

    errors = find_intra_submission_duplicates(rows)

    assert len(errors) == 2

    for err in errors:
        assert err[ValidationErrorKey.DETAILS][IpamValidationDetailKey.FIRST_ROW_INDEX] == 0


def test_find_intra_submission_duplicates_skips_incomplete_rows() -> None:
    """Rows missing subnet_ref or ip are not considered for duplicate detection"""
    rows = [
        (0, 1, '10.0.0.1', None),
        (1, None, '10.0.0.1', None),
        (2, 1, None, None),
        (3, 1, '10.0.0.1', None),
    ]

    errors = find_intra_submission_duplicates(rows)

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.FIRST_ROW_INDEX] == 0
    assert details[IpamValidationDetailKey.DUPLICATE_ROW_INDEX] == 3


def test_find_intra_submission_duplicates_treats_different_subnets_as_distinct() -> None:
    """Same IP under different subnets is allowed (only the (subnet, IP) pair is unique)"""
    rows = [
        (0, 1, '10.0.0.1', None),
        (1, 2, '10.0.0.1', None),
    ]

    assert not find_intra_submission_duplicates(rows)


def test_find_intra_submission_duplicates_returns_empty_for_empty_input() -> None:
    """No rows submitted means no errors"""
    assert not find_intra_submission_duplicates([])


# -------------------------------------------------------------------------------------------------------------------- #
#                                           find_subnet_without_ip                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_subnet_without_ip_returns_empty_for_empty_input() -> None:
    """No rows submitted means no errors"""
    assert not find_subnet_without_ip([])


def test_find_subnet_without_ip_accepts_complete_row() -> None:
    """A row with both subnet_ref and ip set produces no error"""
    rows = [(0, 1, '10.0.0.1', None)]

    assert not find_subnet_without_ip(rows)


def test_find_subnet_without_ip_accepts_empty_placeholder_row() -> None:
    """A row with neither subnet_ref nor ip set is treated as an empty placeholder and accepted"""
    rows = [(0, None, None, None)]

    assert not find_subnet_without_ip(rows)


def test_find_subnet_without_ip_accepts_ip_only_row_per_literal_scope() -> None:
    """A row with ip set but no subnet is allowed (inverse case is not in scope)"""
    rows = [(0, None, '10.0.0.1', None)]

    assert not find_subnet_without_ip(rows)


def test_find_subnet_without_ip_flags_row_with_subnet_but_no_ip() -> None:
    """A row with subnet_ref set and ip None produces one SUBNET_WITHOUT_IP error"""
    rows = [(3, 42, None, None)]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_WITHOUT_IP
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.ROW_INDEX] == 3
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == 42


def test_find_subnet_without_ip_flags_multiple_offending_rows_in_order() -> None:
    """Each offending row produces its own error; emission order matches input order"""
    rows = [
        (0, 1, None, None),
        (1, 1, '10.0.0.1', None),
        (2, 2, None, None),
    ]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 2
    reported_rows = [err[ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] for err in errors]
    assert reported_rows == [0, 2]


def test_find_subnet_without_ip_flags_only_offending_rows_in_mixed_batch() -> None:
    """A mixed batch produces errors only for the subnet-without-ip rows, leaving valid + empty rows alone"""
    rows = [
        (0, 1, '10.0.0.1', None),  # valid
        (1, None, None, None),     # empty placeholder
        (2, 2, None, None),        # offending
        (3, None, '10.0.0.2', None),  # ip-only, literal-scope passes
    ]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 2


def test_find_subnet_without_ip_error_envelope_carries_code_message_and_details() -> None:
    """The structured error envelope exposes code + a non-empty message + the documented detail keys"""
    rows = [(7, 99, None, None)]

    error = find_subnet_without_ip(rows)[0]

    assert error[ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_WITHOUT_IP
    assert isinstance(error[ValidationErrorKey.MESSAGE], str)
    assert error[ValidationErrorKey.MESSAGE]  # non-empty
    assert set(error[ValidationErrorKey.DETAILS].keys()) == {
        IpamValidationDetailKey.ROW_INDEX,
        IpamValidationDetailKey.SUBNET_OBJECT_ID,
    }


def _make_subnet_doc(public_id: int, network_range: Any = None) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with an optional network-range field."""
    fields: list[dict[str, Any]] = []

    if network_range is not None:
        fields.append(
            {CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE, CmdbObjectFieldKey.VALUE: network_range},
        )

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS: fields,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _load_subnet_object                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_subnet_object_errors_when_subnet_type_undefined() -> None:
    """Without a SUBNET CmdbType the loader emits SUBNET_TYPE_MISSING and skips the object query"""
    objects_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=None):
        subnet_obj, errors = _load_subnet_object(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert subnet_obj is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_TYPE_MISSING
    objects_manager.find_objects.assert_not_called()


def test_load_subnet_object_pins_the_id_and_type_criteria() -> None:
    """The loader queries exactly {public_id, type_id} with as_dict=True"""
    objects_manager = MagicMock()
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')
    objects_manager.find_objects.return_value = [doc]
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID) as mock_resolve:
        subnet_obj, errors = _load_subnet_object(objects_manager, types_manager, SUBNET_OBJECT_ID)

    mock_resolve.assert_called_once_with(types_manager, SpecialType.SUBNET)
    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
        as_dict=True,
    )
    assert subnet_obj is doc
    assert not errors


def test_load_subnet_object_errors_when_no_match() -> None:
    """An id that matches no SUBNET emits SUBNET_NOT_FOUND with the id in the details"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        subnet_obj, errors = _load_subnet_object(objects_manager, MagicMock(), SUBNET_OBJECT_ID)

    assert subnet_obj is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_NOT_FOUND
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.SUBNET_OBJECT_ID] == SUBNET_OBJECT_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _extract_subnet_network                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_extract_subnet_network_parses_a_valid_range() -> None:
    """A canonical CIDR parses into the network with no errors"""
    network, errors = _extract_subnet_network(_make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24'))

    assert network == IPv4Network('10.0.0.0/24')
    assert not errors


@pytest.mark.parametrize('bad_range', [None, 12345, 'not-a-cidr', '10.0.0.5/24'])
def test_extract_subnet_network_errors_on_missing_or_unparsable_range(bad_range: Any) -> None:
    """A missing, non-string or non-canonical range emits SUBNET_BROKEN_STATE with the stored value"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range=bad_range)

    network, errors = _extract_subnet_network(doc)

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_BROKEN_STATE
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == SUBNET_OBJECT_ID
    assert details[IpamValidationDetailKey.STORED_VALUE] == bad_range


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 _check_ip_format                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('valid_ip', ['10.0.0.5', '2001:db8::5'])
def test_check_ip_format_parses_both_families(valid_ip: str) -> None:
    """A valid IPv4 / IPv6 address parses with no errors"""
    parsed, errors = _check_ip_format(valid_ip)

    assert parsed == parse_ip(valid_ip)
    assert not errors


def test_check_ip_format_errors_on_invalid_address() -> None:
    """An unparsable address emits IP_INVALID carrying the candidate string"""
    parsed, errors = _check_ip_format('not-an-ip')

    assert parsed is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_INVALID
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.IP_ADDRESS] == 'not-an-ip'


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _check_ip_uniqueness                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_ip_uniqueness_pins_the_collision_query() -> None:
    """The Mongo filter requires one interface row carrying both the subnet ref and the IP"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    errors = _check_ip_uniqueness(objects_manager, SUBNET_OBJECT_ID, '10.0.0.5', None, None)

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {
                    CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                    CmdbObjectMdsKey.VALUES: {
                        '$elemMatch': {
                            CmdbObjectMdsRowKey.DATA: {
                                '$all': [
                                    {'$elemMatch': {
                                        CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                        CmdbObjectFieldKey.VALUE: SUBNET_OBJECT_ID,
                                    }},
                                    {'$elemMatch': {
                                        CmdbObjectFieldKey.NAME: InterfaceField.IP,
                                        CmdbObjectFieldKey.VALUE: '10.0.0.5',
                                    }},
                                ],
                            },
                        },
                    },
                },
            },
        },
        as_dict=True,
    )
    assert not errors


def test_check_ip_uniqueness_reports_collisions_from_the_candidates() -> None:
    """A candidate row matching the (subnet, IP) pair yields one IP_DUPLICATE error"""
    objects_manager = MagicMock()
    carrier = _make_object(OWNER_OBJECT_ID, [_make_interface_row(SUBNET_OBJECT_ID, '10.0.0.5')])
    objects_manager.find_objects.return_value = [carrier]

    errors = _check_ip_uniqueness(objects_manager, SUBNET_OBJECT_ID, '10.0.0.5', None, None)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.IP_DUPLICATE
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.OBJECT_ID] == OWNER_OBJECT_ID


def test_check_ip_uniqueness_honours_the_self_exclusion_pair() -> None:
    """The candidate's own pre-edit row (object id + row index) is not flagged against itself"""
    objects_manager = MagicMock()
    carrier = _make_object(OWNER_OBJECT_ID, [_make_interface_row(SUBNET_OBJECT_ID, '10.0.0.5')])
    objects_manager.find_objects.return_value = [carrier]

    errors = _check_ip_uniqueness(
        objects_manager, SUBNET_OBJECT_ID, '10.0.0.5',
        exclude_object_id=OWNER_OBJECT_ID, exclude_row_index=0,
    )

    assert not errors


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_interface                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_interface_short_circuits_when_subnet_load_fails() -> None:
    """A failed subnet load returns the load errors without running any further check"""
    load_error = build_error(InterfaceErrorCode.SUBNET_NOT_FOUND, 'gone')

    with patch(f'{PATH}._load_subnet_object', return_value=(None, [load_error])), \
         patch(f'{PATH}._extract_subnet_network') as mock_extract, \
         patch(f'{PATH}._check_ip_format') as mock_format, \
         patch(f'{PATH}._check_ip_uniqueness') as mock_unique:
        errors = validate_interface(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, '10.0.0.5')

    assert errors == [load_error]
    mock_extract.assert_not_called()
    mock_format.assert_not_called()
    mock_unique.assert_not_called()


def test_validate_interface_returns_empty_for_a_valid_row() -> None:
    """With every check clean the orchestrator returns no errors and forwards the exclude pair"""
    objects_manager = MagicMock()
    subnet_doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')
    network = parse_cidr('10.0.0.0/24')
    ip = parse_ip('10.0.0.5')

    with patch(f'{PATH}._load_subnet_object', return_value=(subnet_doc, [])), \
         patch(f'{PATH}._extract_subnet_network', return_value=(network, [])), \
         patch(f'{PATH}._check_ip_format', return_value=(ip, [])), \
         patch(f'{PATH}._check_ip_membership', return_value=[]) as mock_membership, \
         patch(f'{PATH}._check_ip_uniqueness', return_value=[]) as mock_unique:
        errors = validate_interface(
            objects_manager, MagicMock(), SUBNET_OBJECT_ID, '10.0.0.5',
            exclude_object_id=OWNER_OBJECT_ID, exclude_row_index=2,
        )

    assert not errors
    mock_membership.assert_called_once_with(ip, network)
    mock_unique.assert_called_once_with(
        objects_manager, SUBNET_OBJECT_ID, '10.0.0.5', OWNER_OBJECT_ID, 2,
    )


def test_validate_interface_skips_membership_when_range_broken_but_still_checks_uniqueness() -> None:
    """A broken subnet range plus a valid IP: membership is skipped, uniqueness still runs"""
    range_error = build_error(InterfaceErrorCode.SUBNET_BROKEN_STATE, 'broken')
    ip = parse_ip('10.0.0.5')

    with patch(f'{PATH}._load_subnet_object', return_value=(_make_subnet_doc(SUBNET_OBJECT_ID), [])), \
         patch(f'{PATH}._extract_subnet_network', return_value=(None, [range_error])), \
         patch(f'{PATH}._check_ip_format', return_value=(ip, [])), \
         patch(f'{PATH}._check_ip_membership') as mock_membership, \
         patch(f'{PATH}._check_ip_uniqueness', return_value=[]) as mock_unique:
        errors = validate_interface(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, '10.0.0.5')

    assert errors == [range_error]
    mock_membership.assert_not_called()
    mock_unique.assert_called_once()


def test_validate_interface_skips_membership_and_uniqueness_when_ip_invalid() -> None:
    """An unparsable IP collects the format error and skips both IP-dependent checks"""
    ip_error = build_error(InterfaceErrorCode.IP_INVALID, 'bad ip')
    network = parse_cidr('10.0.0.0/24')

    with patch(f'{PATH}._load_subnet_object', return_value=(_make_subnet_doc(SUBNET_OBJECT_ID), [])), \
         patch(f'{PATH}._extract_subnet_network', return_value=(network, [])), \
         patch(f'{PATH}._check_ip_format', return_value=(None, [ip_error])), \
         patch(f'{PATH}._check_ip_membership') as mock_membership, \
         patch(f'{PATH}._check_ip_uniqueness') as mock_unique:
        errors = validate_interface(MagicMock(), MagicMock(), SUBNET_OBJECT_ID, 'not-an-ip')

    assert errors == [ip_error]
    mock_membership.assert_not_called()
    mock_unique.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_interface_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_interface_rows_returns_empty_for_an_empty_batch() -> None:
    """An empty row list short-circuits without invoking any check"""
    with patch(f'{PATH}.find_subnet_without_ip') as mock_completeness, \
         patch(f'{PATH}.find_intra_submission_duplicates') as mock_duplicates, \
         patch(f'{PATH}.find_type_family_mismatches') as mock_type_check, \
         patch(f'{PATH}.validate_interface') as mock_validate:
        errors = validate_interface_rows(MagicMock(), MagicMock(), [])

    assert not errors
    mock_completeness.assert_not_called()
    mock_duplicates.assert_not_called()
    mock_type_check.assert_not_called()
    mock_validate.assert_not_called()


def test_validate_interface_rows_concatenates_batch_and_per_row_errors_in_order() -> None:
    """Order: completeness, duplicates, missing types, type mismatches, then per-row results"""
    completeness_error = build_error(InterfaceErrorCode.SUBNET_WITHOUT_IP, 'no ip')
    duplicate_error = build_error(InterfaceErrorCode.IP_DUPLICATE, 'twice')
    missing_type_error = build_error(InterfaceErrorCode.TYPE_MISSING, 'no type')
    type_error = build_error(InterfaceErrorCode.TYPE_FAMILY_MISMATCH, 'wrong family')
    row_error = build_error(InterfaceErrorCode.IP_NOT_IN_SUBNET, 'outside')
    rows: list[tuple[int, int | None, str | None, str | None]] = [(0, SUBNET_OBJECT_ID, '10.0.0.5', None)]

    with patch(f'{PATH}.find_subnet_without_ip', return_value=[completeness_error]), \
         patch(f'{PATH}.find_intra_submission_duplicates', return_value=[duplicate_error]), \
         patch(f'{PATH}.find_missing_types', return_value=[missing_type_error]) as mock_missing_types, \
         patch(f'{PATH}.find_type_family_mismatches', return_value=[type_error]) as mock_type_check, \
         patch(f'{PATH}.validate_interface', return_value=[row_error]):
        errors = validate_interface_rows(MagicMock(), MagicMock(), rows)

    assert errors == [completeness_error, duplicate_error, missing_type_error, type_error, row_error]
    assert mock_missing_types.call_args.args[0] is rows
    assert mock_type_check.call_args.args[2] is rows


def test_validate_interface_rows_skips_incomplete_rows_in_the_per_row_pass() -> None:
    """Rows missing the subnet ref or the IP never reach validate_interface"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, None, '10.0.0.5', None),
        (1, SUBNET_OBJECT_ID, None, None),
        (2, None, None, None),
        (3, SUBNET_OBJECT_ID, '10.0.0.7', None),
    ]

    with patch(f'{PATH}.find_subnet_without_ip', return_value=[]), \
         patch(f'{PATH}.find_intra_submission_duplicates', return_value=[]), \
         patch(f'{PATH}.validate_interface', return_value=[]) as mock_validate:
        validate_interface_rows(MagicMock(), MagicMock(), rows)

    assert mock_validate.call_count == 1
    assert mock_validate.call_args.kwargs['subnet_object_id'] == SUBNET_OBJECT_ID
    assert mock_validate.call_args.kwargs['ip_address'] == '10.0.0.7'


def test_validate_interface_rows_forwards_exclusion_and_injects_row_index() -> None:
    """Each per-row call gets (exclude_object_id, row_index) and its errors gain details.row_index"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    error_without_details = {
        ValidationErrorKey.CODE: InterfaceErrorCode.IP_DUPLICATE,
        ValidationErrorKey.MESSAGE: 'collision',
    }
    rows: list[tuple[int, int | None, str | None, str | None]] = [(5, SUBNET_OBJECT_ID, '10.0.0.5', None)]

    with patch(f'{PATH}.find_subnet_without_ip', return_value=[]), \
         patch(f'{PATH}.find_intra_submission_duplicates', return_value=[]), \
         patch(f'{PATH}.validate_interface', return_value=[error_without_details]) as mock_validate:
        errors = validate_interface_rows(
            objects_manager, types_manager, rows, exclude_object_id=OWNER_OBJECT_ID,
        )

    mock_validate.assert_called_once_with(
        objects_manager,
        types_manager,
        subnet_object_id=SUBNET_OBJECT_ID,
        ip_address='10.0.0.5',
        exclude_object_id=OWNER_OBJECT_ID,
        exclude_row_index=5,
    )
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 5


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _load_subnets_by_ids                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_subnets_by_ids_pins_the_batch_criteria_and_keys_by_public_id() -> None:
    """One $in query loads every referenced subnet; the result is keyed by public_id"""
    objects_manager = MagicMock()
    doc = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')
    objects_manager.find_objects.return_value = [doc]
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        result = _load_subnets_by_ids(objects_manager, types_manager, [SUBNET_OBJECT_ID])

    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: {'$in': [SUBNET_OBJECT_ID]}, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
        as_dict=True,
    )
    assert result == {SUBNET_OBJECT_ID: doc}


def test_load_subnets_by_ids_returns_empty_without_ids_or_subnet_type() -> None:
    """An empty id list and a missing SUBNET CmdbType both yield {} without querying"""
    objects_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        assert _load_subnets_by_ids(objects_manager, MagicMock(), []) == {}

    with patch(f'{PATH}.resolve_special_type_id', return_value=None):
        assert _load_subnets_by_ids(objects_manager, MagicMock(), [SUBNET_OBJECT_ID]) == {}

    objects_manager.find_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _check_row_type_against_ip                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_row_type_against_ip_passes_on_matching_family() -> None:
    """A matching token / IP family pair produces no errors (both families)"""
    assert not _check_row_type_against_ip(0, IpAddressFamily.IPV4, '10.0.0.5')
    assert not _check_row_type_against_ip(0, IpAddressFamily.IPV6, '2001:db8::5')


def test_check_row_type_against_ip_flags_contradicting_family() -> None:
    """An ipv4 token on an IPv6 address emits TYPE_FAMILY_MISMATCH with full details"""
    errors = _check_row_type_against_ip(3, IpAddressFamily.IPV4, '2001:db8::5')

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_FAMILY_MISMATCH
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.ROW_INDEX] == 3
    assert details[IpamValidationDetailKey.INTERFACE_TYPE] == IpAddressFamily.IPV4
    assert details[IpamValidationDetailKey.IP_ADDRESS] == '2001:db8::5'
    assert details[IpamValidationDetailKey.IP_FAMILY] == IpAddressFamily.IPV6


def test_check_row_type_against_ip_treats_unrecognised_token_as_mismatch() -> None:
    """A token outside IpAddressFamily can never match the parsed family"""
    errors = _check_row_type_against_ip(0, 'ipv5', '10.0.0.5')

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_FAMILY_MISMATCH


def test_check_row_type_against_ip_skips_unparsable_ip() -> None:
    """An unparsable IP is reported as IP_INVALID elsewhere, not as a family mismatch"""
    assert not _check_row_type_against_ip(0, IpAddressFamily.IPV4, 'not-an-ip')


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _check_row_type_against_subnet                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_row_type_against_subnet_passes_on_matching_family() -> None:
    """A matching token / subnet-CIDR family pair produces no errors"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')

    assert not _check_row_type_against_subnet(0, IpAddressFamily.IPV4, subnet)


def test_check_row_type_against_subnet_flags_contradicting_family() -> None:
    """An ipv4 token on an IPv6 subnet emits TYPE_FAMILY_MISMATCH with full details"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='2001:db8::/64')

    errors = _check_row_type_against_subnet(2, IpAddressFamily.IPV4, subnet)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_FAMILY_MISMATCH
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.ROW_INDEX] == 2
    assert details[IpamValidationDetailKey.INTERFACE_TYPE] == IpAddressFamily.IPV4
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == SUBNET_OBJECT_ID
    assert details[IpamValidationDetailKey.SUBNET_RANGE] == '2001:db8::/64'
    assert details[IpamValidationDetailKey.SUBNET_FAMILY] == IpAddressFamily.IPV6


def test_check_row_type_against_subnet_skips_unparsable_range() -> None:
    """A broken subnet range is reported as SUBNET_BROKEN_STATE elsewhere, not here"""
    subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='not-a-cidr')

    assert not _check_row_type_against_subnet(0, IpAddressFamily.IPV4, subnet)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            find_type_family_mismatches                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_type_family_mismatches_skips_rows_without_a_token_entirely() -> None:
    """Untyped rows never trigger the subnet batch load - legacy rows stay silent"""
    objects_manager = MagicMock()
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, '2001:db8::5', None),
    ]

    errors = find_type_family_mismatches(objects_manager, MagicMock(), rows)

    assert not errors
    objects_manager.find_objects.assert_not_called()


def test_find_type_family_mismatches_reports_ip_and_subnet_contradictions_per_row() -> None:
    """A typed row contradicting both its IP and its subnet yields two mismatch errors"""
    objects_manager = MagicMock()
    v6_subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='2001:db8::/64')
    objects_manager.find_objects.return_value = [v6_subnet]
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, '2001:db8::5', IpAddressFamily.IPV4),
    ]

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        errors = find_type_family_mismatches(objects_manager, MagicMock(), rows)

    assert len(errors) == 2
    assert all(e[ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_FAMILY_MISMATCH for e in errors)
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.IP_FAMILY] == IpAddressFamily.IPV6
    assert errors[1][ValidationErrorKey.DETAILS][IpamValidationDetailKey.SUBNET_FAMILY] == IpAddressFamily.IPV6


def test_find_type_family_mismatches_passes_consistent_typed_rows() -> None:
    """A typed row whose IP and subnet agree with the token produces no errors"""
    objects_manager = MagicMock()
    v4_subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')
    objects_manager.find_objects.return_value = [v4_subnet]
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, '10.0.0.5', IpAddressFamily.IPV4),
    ]

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        errors = find_type_family_mismatches(objects_manager, MagicMock(), rows)

    assert not errors


def test_find_type_family_mismatches_checks_partial_rows_against_present_data_only() -> None:
    """Type+IP without subnet and type+subnet without IP are each checked against what exists"""
    objects_manager = MagicMock()
    v4_subnet = _make_subnet_doc(SUBNET_OBJECT_ID, network_range='10.0.0.0/24')
    objects_manager.find_objects.return_value = [v4_subnet]
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, None, '10.0.0.5', IpAddressFamily.IPV6),
        (1, SUBNET_OBJECT_ID, None, IpAddressFamily.IPV6),
    ]

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        errors = find_type_family_mismatches(objects_manager, MagicMock(), rows)

    assert len(errors) == 2
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 0
    assert IpamValidationDetailKey.IP_ADDRESS in errors[0][ValidationErrorKey.DETAILS]
    assert errors[1][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 1
    assert IpamValidationDetailKey.SUBNET_OBJECT_ID in errors[1][ValidationErrorKey.DETAILS]


def test_find_type_family_mismatches_skips_unknown_subnet_refs() -> None:
    """A typed row referencing a subnet id that resolves to nothing is skipped silently"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, None, IpAddressFamily.IPV4),
    ]

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        errors = find_type_family_mismatches(objects_manager, MagicMock(), rows)

    assert not errors


def test_find_type_family_mismatches_loads_referenced_subnets_in_one_sorted_batch() -> None:
    """All typed rows' subnet refs land deduplicated and sorted in a single $in query"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID + 1, None, IpAddressFamily.IPV4),
        (1, SUBNET_OBJECT_ID, None, IpAddressFamily.IPV4),
        (2, SUBNET_OBJECT_ID, None, IpAddressFamily.IPV6),
    ]

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID):
        find_type_family_mismatches(objects_manager, MagicMock(), rows)

    criteria = objects_manager.find_objects.call_args.args[0]
    assert criteria[CmdbObjectKey.PUBLIC_ID] == {'$in': [SUBNET_OBJECT_ID, SUBNET_OBJECT_ID + 1]}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                find_missing_types                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_missing_types_flags_data_carrying_rows_without_a_token() -> None:
    """Rows with a subnet ref and/or an IP but no type token emit TYPE_MISSING with the row index"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, None, None),
        (1, None, '10.0.0.5', None),
        (2, SUBNET_OBJECT_ID, '10.0.0.7', None),
    ]

    errors = find_missing_types(rows)

    assert len(errors) == 3
    assert all(e[ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_MISSING for e in errors)
    assert [e[ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] for e in errors] == [0, 1, 2]


def test_find_missing_types_accepts_typed_rows_and_empty_placeholders() -> None:
    """A row with a token and a completely empty placeholder row both stay silent"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_OBJECT_ID, '10.0.0.5', IpAddressFamily.IPV4),
        (1, None, None, None),
    ]

    assert not find_missing_types(rows)
