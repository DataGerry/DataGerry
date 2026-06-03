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

Covers the pure helpers only — DB-orchestrating functions (_load_subnet_object,
_check_ip_uniqueness, validate_interface, validate_interface_rows) are deferred to the
integration tier. Fixture documents reference CmdbObjectKey / CmdbObjectMdsKey /
CmdbObjectMdsRowKey / CmdbObjectFieldKey / InterfaceField / IpamSection enums for structural
keys, per the no-magic-values rule
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import pytest

from cmdb.utils import ValidationErrorKey
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.framework.ipam.cidr import parse_cidr, parse_ip
from cmdb.framework.ipam.interface_validator import (
    InterfaceErrorCode,
    _check_ip_membership,
    _collect_collision_errors,
    _row_matches,
    find_intra_submission_duplicates,
    find_subnet_without_ip,
)
# -------------------------------------------------------------------------------------------------------------------- #


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

    assert errors == []


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

    assert errors == []


def test_check_ip_membership_allows_single_host_of_slash32() -> None:
    """/32 host route is assignable under the host-route policy (no IP_RESERVED)"""
    errors = _check_ip_membership(IPv4Address('10.0.0.5'), IPv4Network('10.0.0.5/32'))

    assert errors == []


def test_check_ip_membership_passes_for_ipv6_host_in_ipv6_subnet() -> None:
    """An IPv6 host inside an IPv6 subnet produces no errors"""
    errors = _check_ip_membership(parse_ip('2001:db8::5'), parse_cidr('2001:db8::/64'))

    assert errors == []


def test_check_ip_membership_allows_ipv6_network_address_no_reservation() -> None:
    """IPv6 reserves no network/broadcast address, so the all-zeros host is assignable"""
    errors = _check_ip_membership(parse_ip('2001:db8::'), parse_cidr('2001:db8::/64'))

    assert errors == []


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

    assert errors == []


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

    assert errors == []


def test_collect_collision_errors_returns_empty_for_no_candidates() -> None:
    """No candidate objects means no collisions"""
    errors = _collect_collision_errors(
        candidates=[],
        subnet_object_id=42,
        ip_address='10.0.0.5',
        exclude_object_id=None,
        exclude_row_index=None,
    )

    assert errors == []


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
        (0, 1, '10.0.0.1'),
        (1, 1, '10.0.0.2'),
        (2, 2, '10.0.0.1'),
    ]

    assert find_intra_submission_duplicates(rows) == []


def test_find_intra_submission_duplicates_flags_second_occurrence() -> None:
    """The first occurrence wins; the second occurrence is reported with both row indices"""
    rows = [
        (0, 1, '10.0.0.1'),
        (1, 1, '10.0.0.1'),
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
        (0, 1, '10.0.0.1'),
        (1, 1, '10.0.0.1'),
        (2, 1, '10.0.0.1'),
    ]

    errors = find_intra_submission_duplicates(rows)

    assert len(errors) == 2

    for err in errors:
        assert err[ValidationErrorKey.DETAILS][IpamValidationDetailKey.FIRST_ROW_INDEX] == 0


def test_find_intra_submission_duplicates_skips_incomplete_rows() -> None:
    """Rows missing subnet_ref or ip are not considered for duplicate detection"""
    rows = [
        (0, 1, '10.0.0.1'),
        (1, None, '10.0.0.1'),
        (2, 1, None),
        (3, 1, '10.0.0.1'),
    ]

    errors = find_intra_submission_duplicates(rows)

    assert len(errors) == 1
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.FIRST_ROW_INDEX] == 0
    assert details[IpamValidationDetailKey.DUPLICATE_ROW_INDEX] == 3


def test_find_intra_submission_duplicates_treats_different_subnets_as_distinct() -> None:
    """Same IP under different subnets is allowed (only the (subnet, IP) pair is unique)"""
    rows = [
        (0, 1, '10.0.0.1'),
        (1, 2, '10.0.0.1'),
    ]

    assert find_intra_submission_duplicates(rows) == []


def test_find_intra_submission_duplicates_returns_empty_for_empty_input() -> None:
    """No rows submitted means no errors"""
    assert find_intra_submission_duplicates([]) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                           find_subnet_without_ip                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_subnet_without_ip_returns_empty_for_empty_input() -> None:
    """No rows submitted means no errors"""
    assert find_subnet_without_ip([]) == []


def test_find_subnet_without_ip_accepts_complete_row() -> None:
    """A row with both subnet_ref and ip set produces no error"""
    rows = [(0, 1, '10.0.0.1')]

    assert find_subnet_without_ip(rows) == []


def test_find_subnet_without_ip_accepts_empty_placeholder_row() -> None:
    """A row with neither subnet_ref nor ip set is treated as an empty placeholder and accepted"""
    rows = [(0, None, None)]

    assert find_subnet_without_ip(rows) == []


def test_find_subnet_without_ip_accepts_ip_only_row_per_literal_scope() -> None:
    """A row with ip set but no subnet is allowed (inverse case is not in scope)"""
    rows = [(0, None, '10.0.0.1')]

    assert find_subnet_without_ip(rows) == []


def test_find_subnet_without_ip_flags_row_with_subnet_but_no_ip() -> None:
    """A row with subnet_ref set and ip None produces one SUBNET_WITHOUT_IP error"""
    rows = [(3, 42, None)]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_WITHOUT_IP
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.ROW_INDEX] == 3
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == 42


def test_find_subnet_without_ip_flags_multiple_offending_rows_in_order() -> None:
    """Each offending row produces its own error; emission order matches input order"""
    rows = [
        (0, 1, None),
        (1, 1, '10.0.0.1'),
        (2, 2, None),
    ]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 2
    reported_rows = [err[ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] for err in errors]
    assert reported_rows == [0, 2]


def test_find_subnet_without_ip_flags_only_offending_rows_in_mixed_batch() -> None:
    """A mixed batch produces errors only for the subnet-without-ip rows, leaving valid + empty rows alone"""
    rows = [
        (0, 1, '10.0.0.1'),  # valid
        (1, None, None),     # empty placeholder
        (2, 2, None),        # offending
        (3, None, '10.0.0.2'),  # ip-only, literal-scope passes
    ]

    errors = find_subnet_without_ip(rows)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.ROW_INDEX] == 2


def test_find_subnet_without_ip_error_envelope_carries_code_message_and_details() -> None:
    """The structured error envelope exposes code + a non-empty message + the documented detail keys"""
    rows = [(7, 99, None)]

    error = find_subnet_without_ip(rows)[0]

    assert error[ValidationErrorKey.CODE] == InterfaceErrorCode.SUBNET_WITHOUT_IP
    assert isinstance(error[ValidationErrorKey.MESSAGE], str)
    assert error[ValidationErrorKey.MESSAGE]  # non-empty
    assert set(error[ValidationErrorKey.DETAILS].keys()) == {
        IpamValidationDetailKey.ROW_INDEX,
        IpamValidationDetailKey.SUBNET_OBJECT_ID,
    }
