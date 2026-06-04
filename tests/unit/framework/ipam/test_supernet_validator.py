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
Unit tests for cmdb.framework.ipam.supernet_validator

Pure tests: supernet validation is stateless (no DB / Flask), so each behavior is exercised
directly. Covers the individual checks (_check_canonical_cidr, _check_type_matches_family) and
the validate_supernet orchestrator across IPv4 / IPv6 and the family-vs-type consistency rule
"""
from cmdb.utils import ValidationErrorKey
from cmdb.models.special_type_model.ipam_constants import IpAddressFamily, IpamValidationDetailKey
from cmdb.framework.ipam.cidr import parse_cidr
from cmdb.framework.ipam.supernet_validator import (
    SupernetErrorCode,
    _check_canonical_cidr,
    _check_type_matches_family,
    validate_supernet,
)
# -------------------------------------------------------------------------------------------------------------------- #

VALID_RANGE_V4: str = '10.0.0.0/16'
VALID_RANGE_V6: str = '2001:db8::/32'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _check_canonical_cidr                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_canonical_cidr_returns_network_and_no_errors_for_canonical_ipv4() -> None:
    """A canonical IPv4 CIDR yields the parsed network and an empty error list"""
    network, errors = _check_canonical_cidr(VALID_RANGE_V4)

    assert network is not None
    assert str(network) == VALID_RANGE_V4
    assert not errors


def test_check_canonical_cidr_returns_network_and_no_errors_for_canonical_ipv6() -> None:
    """A canonical IPv6 CIDR yields the parsed network and an empty error list"""
    network, errors = _check_canonical_cidr(VALID_RANGE_V6)

    assert network is not None
    assert str(network) == VALID_RANGE_V6
    assert not errors


def test_check_canonical_cidr_reports_cidr_invalid_for_garbage_input() -> None:
    """A non-CIDR string yields None and a CIDR_INVALID error carrying the raw value"""
    network, errors = _check_canonical_cidr('not-a-cidr')

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.CIDR_INVALID
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.NETWORK_RANGE] == 'not-a-cidr'


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _check_type_matches_family                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_type_matches_family_reports_type_missing_when_supernet_type_is_none() -> None:
    """A None selector emits TYPE_MISSING - the selector is required on every supernet"""
    errors = _check_type_matches_family(parse_cidr(VALID_RANGE_V4), None)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.TYPE_MISSING
    assert errors[0][ValidationErrorKey.DETAILS][IpamValidationDetailKey.CANDIDATE] == VALID_RANGE_V4


def test_check_type_matches_family_returns_empty_when_ipv4_selector_matches_ipv4_cidr() -> None:
    """An 'ipv4' selector on an IPv4 CIDR is consistent -> no errors"""
    assert not _check_type_matches_family(parse_cidr(VALID_RANGE_V4), IpAddressFamily.IPV4)


def test_check_type_matches_family_returns_empty_when_ipv6_selector_matches_ipv6_cidr() -> None:
    """An 'ipv6' selector on an IPv6 CIDR is consistent -> no errors"""
    assert not _check_type_matches_family(parse_cidr(VALID_RANGE_V6), IpAddressFamily.IPV6)


def test_check_type_matches_family_reports_mismatch_for_ipv6_selector_on_ipv4_cidr() -> None:
    """An 'ipv6' selector on an IPv4 CIDR -> TYPE_FAMILY_MISMATCH carrying both families"""
    errors = _check_type_matches_family(parse_cidr(VALID_RANGE_V4), IpAddressFamily.IPV6)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.TYPE_FAMILY_MISMATCH
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.SUPERNET_TYPE] == IpAddressFamily.IPV6
    assert details[IpamValidationDetailKey.CIDR_FAMILY] == IpAddressFamily.IPV4


def test_check_type_matches_family_treats_unrecognised_selector_as_mismatch() -> None:
    """An unrecognised selector value never matches the candidate's family -> mismatch error"""
    errors = _check_type_matches_family(parse_cidr(VALID_RANGE_V4), 'something-else')

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.TYPE_FAMILY_MISMATCH


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_supernet                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_supernet_returns_only_cidr_error_for_invalid_cidr() -> None:
    """An invalid CIDR short-circuits; the family check never runs"""
    errors = validate_supernet('not-a-cidr', supernet_type=IpAddressFamily.IPV4)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.CIDR_INVALID


def test_validate_supernet_reports_type_missing_for_canonical_cidr_without_type() -> None:
    """A canonical CIDR with no selector is rejected: the selector is required"""
    for valid_range in (VALID_RANGE_V4, VALID_RANGE_V6):
        errors = validate_supernet(valid_range)

        assert len(errors) == 1
        assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.TYPE_MISSING


def test_validate_supernet_returns_empty_when_type_matches_family() -> None:
    """A selector that matches the CIDR family is valid, both families"""
    assert not validate_supernet(VALID_RANGE_V4, supernet_type=IpAddressFamily.IPV4)
    assert not validate_supernet(VALID_RANGE_V6, supernet_type=IpAddressFamily.IPV6)


def test_validate_supernet_reports_type_family_mismatch() -> None:
    """A selector that disagrees with the CIDR family yields TYPE_FAMILY_MISMATCH"""
    errors = validate_supernet(VALID_RANGE_V6, supernet_type=IpAddressFamily.IPV4)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SupernetErrorCode.TYPE_FAMILY_MISMATCH
