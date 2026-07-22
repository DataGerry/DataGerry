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
Unit tests for cmdb.models.special_type_model.schemas.cidr_regex

Confirms CIDR_REGEX accepts a valid IPv4 or IPv6 CIDR (and rejects bare addresses / out-of-range
prefixes / garbage) and that IP_ADDRESS_REGEX accepts a valid IPv4 or IPv6 host address (and rejects
CIDR notation / garbage). These are coarse field guards; canonical validation lives in ipaddress.
"""
import re

import pytest

from cmdb.models.special_type_model.schemas.cidr_regex import CIDR_REGEX, IP_ADDRESS_REGEX
# -------------------------------------------------------------------------------------------------------------------- #

VALID_CIDRS: list[str] = [
    '10.0.0.0/8', '192.168.1.0/24', '0.0.0.0/0', '255.255.255.255/32',
    '2001:db8::/32', '::/0', 'fe80::/10', '::1/128', '2001:0db8::1/64', '::ffff:192.0.2.1/96',
]
INVALID_CIDRS: list[str] = [
    '10.0.0.0', '10.0.0.0/33', '300.0.0.0/8', '2001:db8::/129', 'gggg::/32', '2001:db8::1', 'hello', '',
]
VALID_ADDRESSES: list[str] = [
    '192.168.0.1', '0.0.0.0', '255.255.255.255',
    '::1', '2001:db8::1', 'fe80::1', '::', '2001:0db8:0000:0000:0000:0000:0000:0001', '::ffff:192.0.2.1',
]
INVALID_ADDRESSES: list[str] = [
    '256.0.0.1', '1.2.3', '2001:db8:::1', 'gg::1', '12345::', '192.168.0.1/24', 'hello', '',
]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CIDR_REGEX                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', VALID_CIDRS)
def test_cidr_regex_accepts_valid(value: str) -> None:
    """A valid IPv4 or IPv6 CIDR matches CIDR_REGEX"""
    assert re.fullmatch(CIDR_REGEX, value) is not None


@pytest.mark.parametrize('value', INVALID_CIDRS)
def test_cidr_regex_rejects_invalid(value: str) -> None:
    """A bare address, out-of-range prefix or garbage does not match CIDR_REGEX"""
    assert re.fullmatch(CIDR_REGEX, value) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                               IP_ADDRESS_REGEX                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', VALID_ADDRESSES)
def test_ip_address_regex_accepts_valid(value: str) -> None:
    """A valid IPv4 or IPv6 host address matches IP_ADDRESS_REGEX"""
    assert re.fullmatch(IP_ADDRESS_REGEX, value) is not None


@pytest.mark.parametrize('value', INVALID_ADDRESSES)
def test_ip_address_regex_rejects_invalid(value: str) -> None:
    """CIDR notation or garbage does not match IP_ADDRESS_REGEX"""
    assert re.fullmatch(IP_ADDRESS_REGEX, value) is None
