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
from cmdb.models.special_type_model.ipam_constants import IpAddressFamily
from cmdb.framework.ipam.cidr import parse_cidr
from cmdb.framework.ipam.supernet_validator import (
    _check_canonical_cidr,
    _check_type_matches_family,
    validate_supernet,
)
# -------------------------------------------------------------------------------------------------------------------- #

VALID_RANGE_V4: str = '10.0.0.0/16'
VALID_RANGE_V6: str = '2001:db8::/32'

# Stable message fragments (errors carry only a 'message')
MSG_CIDR_INVALID: str = 'is not a canonical IPv4/IPv6 CIDR'
MSG_TYPE_REQUIRED: str = "Supernet type ('dg-supernet-type') is required"
MSG_FAMILY_MISMATCH: str = 'does not match the address family'


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
    """A non-CIDR string yields None and a CIDR-invalid error naming the raw value"""
    network, errors = _check_canonical_cidr('not-a-cidr')

    assert network is None
    assert len(errors) == 1
    assert MSG_CIDR_INVALID in errors[0][ValidationErrorKey.MESSAGE]
    assert 'not-a-cidr' in errors[0][ValidationErrorKey.MESSAGE]


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _check_type_matches_family                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_check_type_matches_family_reports_missing_selector_for_the_supernet_field() -> None:
    """The SUPERNET binding rejects a None selector, naming the dg-supernet-type field

    The full required-selector / mismatch matrix is covered once on the shared
    ``validate_family_selector`` core in test_cidr; here only the SUPERNET binding is pinned
    """
    errors = _check_type_matches_family(parse_cidr(VALID_RANGE_V4), None)

    assert len(errors) == 1
    assert MSG_TYPE_REQUIRED in errors[0][ValidationErrorKey.MESSAGE]


def test_check_type_matches_family_reports_mismatch() -> None:
    """The SUPERNET binding rejects a selector that disagrees with the CIDR family"""
    errors = _check_type_matches_family(parse_cidr(VALID_RANGE_V4), IpAddressFamily.IPV6)

    assert len(errors) == 1
    assert MSG_FAMILY_MISMATCH in errors[0][ValidationErrorKey.MESSAGE]


def test_check_type_matches_family_returns_empty_when_selector_matches() -> None:
    """A consistent selector passes the SUPERNET binding without errors"""
    assert not _check_type_matches_family(parse_cidr(VALID_RANGE_V6), IpAddressFamily.IPV6)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_supernet                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_supernet_returns_only_cidr_error_for_invalid_cidr() -> None:
    """An invalid CIDR short-circuits; the family check never runs"""
    errors = validate_supernet('not-a-cidr', supernet_type=IpAddressFamily.IPV4)

    assert len(errors) == 1
    assert MSG_CIDR_INVALID in errors[0][ValidationErrorKey.MESSAGE]


def test_validate_supernet_reports_type_missing_for_canonical_cidr_without_type() -> None:
    """A canonical CIDR with no selector is rejected: the selector is required"""
    for valid_range in (VALID_RANGE_V4, VALID_RANGE_V6):
        errors = validate_supernet(valid_range)

        assert len(errors) == 1
        assert MSG_TYPE_REQUIRED in errors[0][ValidationErrorKey.MESSAGE]


def test_validate_supernet_returns_empty_when_type_matches_family() -> None:
    """A selector that matches the CIDR family is valid, both families"""
    assert not validate_supernet(VALID_RANGE_V4, supernet_type=IpAddressFamily.IPV4)
    assert not validate_supernet(VALID_RANGE_V6, supernet_type=IpAddressFamily.IPV6)


def test_validate_supernet_reports_type_family_mismatch() -> None:
    """A selector that disagrees with the CIDR family is rejected with the mismatch message"""
    errors = validate_supernet(VALID_RANGE_V6, supernet_type=IpAddressFamily.IPV4)

    assert len(errors) == 1
    assert MSG_FAMILY_MISMATCH in errors[0][ValidationErrorKey.MESSAGE]
