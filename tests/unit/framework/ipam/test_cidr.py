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
Unit tests for cmdb.framework.ipam.cidr

Pure tests: no Mongo, no Flask, no fixtures. Each behavior is exercised through a
pytest.mark.parametrize table so a new edge case is a single-line addition. Expected
values are written as concrete literals rather than re-derived from the same constants
the production code uses; tests act as specification-by-example so that an inadvertent
policy change (e.g. flipping the point-to-point threshold) breaks the suite loudly
"""
from typing import Any
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

import pytest

from cmdb.utils import ValidationErrorKey
from cmdb.models.special_type_model.ipam_constants import IpAddressFamily, IpamValidationDetailKey
from cmdb.framework.ipam.cidr import (
    address_family,
    parse_cidr,
    parse_ip,
    contains,
    overlaps,
    ip_in_network,
    is_strict_subnet,
    is_network_or_broadcast,
    total_address_count,
    assignable_address_count,
    first_assignable_int,
    validate_canonical_cidr_value,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    parse_cidr                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected_cidr', [
    ('10.0.0.0/24', '10.0.0.0/24'),
    ('192.168.1.0/24', '192.168.1.0/24'),
    ('0.0.0.0/0', '0.0.0.0/0'),
    ('10.0.0.0/32', '10.0.0.0/32'),
    ('10.0.0.0/31', '10.0.0.0/31'),
    ('172.16.0.0/12', '172.16.0.0/12'),
])
def test_parse_cidr_accepts_canonical(value: str, expected_cidr: str) -> None:
    """Canonical IPv4 CIDRs (host bits all zero) parse to the matching IPv4Network"""
    result: IPv4Network | None = parse_cidr(value)

    assert result is not None
    assert str(result) == expected_cidr


@pytest.mark.parametrize('value, expected_cidr', [
    ('2001:db8::/32', '2001:db8::/32'),
    ('2001:db8::/64', '2001:db8::/64'),
    ('fe80::/10', 'fe80::/10'),
    ('::/0', '::/0'),
    ('::1/128', '::1/128'),
    ('2001:DB8:ABCD::/48', '2001:db8:abcd::/48'),
])
def test_parse_cidr_accepts_canonical_ipv6(value: str, expected_cidr: str) -> None:
    """Canonical IPv6 CIDRs parse to the matching (lower-cased, compressed) IPv6Network"""
    result: IPv6Network | None = parse_cidr(value)

    assert result is not None
    assert str(result) == expected_cidr


@pytest.mark.parametrize('value', [
    '10.0.0.5/24',
    '192.168.1.7/16',
    '10.0.0.128/24',
    '2001:db8::1/32',
    '2001:db8:0:1::/16',
])
def test_parse_cidr_rejects_non_canonical(value: str) -> None:
    """Non-canonical CIDRs (host bits set) are rejected by strict mode, both families"""
    assert parse_cidr(value) is None


@pytest.mark.parametrize('value', [
    'garbage',
    '',
    '10.0.0.0/',
    '10.0.0.0/33',
    '10.0.0.0/-1',
    '10.0.0.0/abc',
    '2001:db8::/129',
    'fffff::/32',
    '10.0.0.0 ',
    ' 10.0.0.0/24',
])
def test_parse_cidr_rejects_invalid_strings(value: str) -> None:
    """Malformed CIDR strings return None instead of raising (over-long prefix, bad hextet)"""
    assert parse_cidr(value) is None


@pytest.mark.parametrize('value', [
    '10.0.0.0',
    '192.168.1.1',
    '0.0.0.0',
])
def test_parse_cidr_rejects_bare_address(value: str) -> None:
    """
    A bare IPv4 address (no slash) is rejected — Python's IPv4Network would treat it as /32
    but the canonical-CIDR contract requires an explicit prefix
    """
    assert parse_cidr(value) is None


@pytest.mark.parametrize('value', [
    '10.0.0.0/255.255.255.0',
    '192.168.1.0/255.255.255.128',
    '10.0.0.0/0.0.0.255',
    '10.0.0.0/255.0.0.0',
])
def test_parse_cidr_rejects_dotted_mask_form(value: str) -> None:
    """
    Netmask ('/A.B.C.D') and hostmask ('/W.W.W.W') prefix forms are rejected even though
    Python's IPv4Network accepts them; canonical CIDR uses '/N' integer form only
    """
    assert parse_cidr(value) is None


@pytest.mark.parametrize('value', [
    None,
    123,
    1.5,
    b'10.0.0.0/24',
    ['10.0.0.0/24'],
    {'cidr': '10.0.0.0/24'},
])
def test_parse_cidr_rejects_non_string(value: Any) -> None:
    """Non-string inputs are rejected by the isinstance guard, not by IPv4Network"""
    assert parse_cidr(value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     parse_ip                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected_address', [
    ('10.0.0.1', '10.0.0.1'),
    ('192.168.1.1', '192.168.1.1'),
    ('0.0.0.0', '0.0.0.0'),
    ('255.255.255.255', '255.255.255.255'),
    ('172.16.0.42', '172.16.0.42'),
])
def test_parse_ip_accepts_dotted_quad(value: str, expected_address: str) -> None:
    """Valid dotted-quad addresses parse to IPv4Address"""
    result: IPv4Address | None = parse_ip(value)

    assert result is not None
    assert str(result) == expected_address


@pytest.mark.parametrize('value, expected_address', [
    ('2001:db8::1', '2001:db8::1'),
    ('::1', '::1'),
    ('::', '::'),
    ('2001:DB8:0:0:0:0:0:1', '2001:db8::1'),
    ('fe80::a', 'fe80::a'),
])
def test_parse_ip_accepts_ipv6(value: str, expected_address: str) -> None:
    """Valid IPv6 host addresses parse to IPv6Address (compressed, lower-cased)"""
    result: IPv6Address | None = parse_ip(value)

    assert result is not None
    assert str(result) == expected_address


@pytest.mark.parametrize('value', [
    '3232235521',
    '192.168.1',
    '192.168.1.1.5',
    '',
    '10',
    '....',
])
def test_parse_ip_rejects_wrong_dot_count(value: str) -> None:
    """A colon-free string with other than exactly three dots is rejected before IPv4Address sees it"""
    assert parse_ip(value) is None


@pytest.mark.parametrize('value', [
    '0xc0.0xa8.0x1.0x1',
    '999.1.1.1',
    'a.b.c.d',
    '192.168.1.',
    '.192.168.1',
    '192.168..1',
    '2001:db8::g',
    '2001:::1',
    'fffff::1',
])
def test_parse_ip_rejects_invalid_octets_or_hextets(value: str) -> None:
    """Dotted-quad with invalid octets, or colon-form with invalid hextets, is rejected"""
    assert parse_ip(value) is None


@pytest.mark.parametrize('value', [
    None,
    123,
    1.5,
    b'192.168.1.1',
    ['192.168.1.1'],
    {'ip': '192.168.1.1'},
])
def test_parse_ip_rejects_non_string(value: Any) -> None:
    """Non-string inputs are rejected by the isinstance guard"""
    assert parse_ip(value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 is_strict_subnet                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('parent_cidr, child_cidr, expected', [
    ('10.0.0.0/8', '10.0.0.0/24', True),
    ('10.0.0.0/8', '10.255.0.0/16', True),
    ('0.0.0.0/0', '10.0.0.0/8', True),
    ('192.168.0.0/16', '192.168.1.0/24', True),

    ('10.0.0.0/8', '10.0.0.0/8', False),
    ('10.0.0.0/24', '10.0.0.0/24', False),
    ('0.0.0.0/0', '0.0.0.0/0', False),

    ('10.0.0.0/24', '192.168.1.0/24', False),
    ('10.0.0.0/24', '10.0.1.0/24', False),
    ('10.0.0.0/16', '192.168.0.0/16', False),

    ('10.0.0.0/24', '10.0.0.0/16', False),

    # IPv6 strict containment
    ('2001:db8::/32', '2001:db8:1::/48', True),
    ('::/0', '2001:db8::/32', True),
    ('2001:db8::/32', '2001:db8::/32', False),
    ('2001:db8::/48', '2001:db8:1::/48', False),

    # Cross-family pairs are disjoint, never raise
    ('10.0.0.0/8', '2001:db8::/32', False),
    ('::/0', '10.0.0.0/8', False),
])
def test_is_strict_subnet(parent_cidr: str, child_cidr: str, expected: bool) -> None:
    """Strict-subnet means contained AND not equal; cross-family pairs are False, not errors"""
    parent: IPv4Network | IPv6Network = parse_cidr(parent_cidr)
    child: IPv4Network | IPv6Network = parse_cidr(child_cidr)

    assert is_strict_subnet(parent, child) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          contains / overlaps / ip_in_network                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('parent_cidr, child_cidr, expected', [
    ('10.0.0.0/8', '10.0.0.0/24', True),
    ('10.0.0.0/8', '10.0.0.0/8', True),            # contains is inclusive of equality
    ('2001:db8::/32', '2001:db8:1::/48', True),
    ('2001:db8::/32', '2001:db8::/32', True),
    ('10.0.0.0/8', '2001:db8::/32', False),        # cross-family
    ('10.0.0.0/24', '10.0.1.0/24', False),
])
def test_contains(parent_cidr: str, child_cidr: str, expected: bool) -> None:
    """contains is inclusive (equal networks contain each other); cross-family is False"""
    assert contains(parse_cidr(parent_cidr), parse_cidr(child_cidr)) is expected


@pytest.mark.parametrize('a_cidr, b_cidr, expected', [
    ('10.0.0.0/24', '10.0.0.128/25', True),
    ('10.0.0.0/24', '10.0.1.0/24', False),
    ('2001:db8::/48', '2001:db8:0:1::/64', True),
    ('2001:db8::/48', '2001:db8:1::/48', False),
    ('10.0.0.0/8', '2001:db8::/32', False),        # cross-family never overlaps
])
def test_overlaps(a_cidr: str, b_cidr: str, expected: bool) -> None:
    """overlaps reports shared addresses; cross-family pairs never overlap"""
    assert overlaps(parse_cidr(a_cidr), parse_cidr(b_cidr)) is expected


@pytest.mark.parametrize('ip, cidr, expected', [
    ('10.0.0.5', '10.0.0.0/24', True),
    ('10.0.1.5', '10.0.0.0/24', False),
    ('2001:db8::5', '2001:db8::/64', True),
    ('2001:dead::5', '2001:db8::/64', False),
    ('10.0.0.5', '2001:db8::/64', False),          # IPv4 address in IPv6 network
    ('2001:db8::5', '10.0.0.0/24', False),          # IPv6 address in IPv4 network
])
def test_ip_in_network(ip: str, cidr: str, expected: bool) -> None:
    """Membership holds only within the same family; a cross-family pair is never a member"""
    assert ip_in_network(parse_ip(ip), parse_cidr(cidr)) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                              total_address_count                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('cidr, expected', [
    ('10.0.0.0/24', 256),
    ('10.0.0.0/16', 65536),
    ('10.0.0.5/32', 1),
    ('2001:db8::/64', 2 ** 64),
    ('2001:db8::/32', 2 ** 96),
    ('::1/128', 1),
])
def test_total_address_count(cidr: str, expected: int) -> None:
    """Total address count includes network + broadcast; IPv6 returns a Python big int"""
    assert total_address_count(parse_cidr(cidr)) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                              is_network_or_broadcast                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('address, cidr, expected', [
    ('10.0.0.0', '10.0.0.0/24', True),
    ('10.0.0.255', '10.0.0.0/24', True),
    ('10.0.0.1', '10.0.0.0/24', False),
    ('10.0.0.128', '10.0.0.0/24', False),
    ('10.0.0.254', '10.0.0.0/24', False),

    ('10.0.0.0', '10.0.0.0/16', True),
    ('10.0.255.255', '10.0.0.0/16', True),
    ('10.0.0.1', '10.0.0.0/16', False),
    ('10.0.128.0', '10.0.0.0/16', False),

    ('10.0.0.0', '10.0.0.0/30', True),
    ('10.0.0.3', '10.0.0.0/30', True),
    ('10.0.0.1', '10.0.0.0/30', False),
    ('10.0.0.2', '10.0.0.0/30', False),

    ('10.0.0.0', '10.0.0.0/31', False),
    ('10.0.0.1', '10.0.0.0/31', False),

    ('10.0.0.5', '10.0.0.5/32', False),
    ('192.168.10.42', '192.168.10.42/32', False),

    # IPv6 reserves neither a network nor a broadcast address: always False
    ('2001:db8::', '2001:db8::/64', False),
    ('2001:db8::ffff:ffff:ffff:ffff', '2001:db8::/64', False),
    ('2001:db8::1', '2001:db8::/64', False),
])
def test_is_network_or_broadcast(address: str, cidr: str, expected: bool) -> None:
    """IPv4 network/broadcast reservation applies to /<=30 only; /31, /32 and all IPv6 carve out"""
    assert is_network_or_broadcast(parse_ip(address), parse_cidr(cidr)) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                            assignable_address_count                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('cidr, expected', [
    ('10.0.0.5/32', 1),
    ('192.168.10.42/32', 1),

    ('10.0.0.0/31', 2),
    ('192.168.1.0/31', 2),

    ('10.0.0.0/30', 2),
    ('10.0.0.0/29', 6),
    ('10.0.0.0/28', 14),
    ('10.0.0.0/27', 30),
    ('10.0.0.0/26', 62),
    ('10.0.0.0/25', 126),
    ('10.0.0.0/24', 254),
    ('10.0.0.0/23', 510),
    ('10.0.0.0/16', 65534),
    ('10.0.0.0/8', 16777214),
    ('0.0.0.0/0', 4294967294),

    # IPv6 reserves nothing: every address is assignable (num_addresses)
    ('2001:db8::/64', 2 ** 64),
    ('2001:db8::/126', 4),
    ('::1/128', 1),
])
def test_assignable_address_count(cidr: str, expected: int) -> None:
    """IPv4: /32->1, /31->2, /<=30->num_addresses-2. IPv6: always num_addresses (no reservation)"""
    assert assignable_address_count(parse_cidr(cidr)) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                              first_assignable_int                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('cidr, expected_first_address', [
    ('10.0.0.0/24', '10.0.0.1'),
    ('10.0.0.0/30', '10.0.0.1'),
    ('192.168.5.0/26', '192.168.5.1'),
    ('172.16.0.0/16', '172.16.0.1'),
    ('0.0.0.0/0', '0.0.0.1'),

    ('10.0.0.0/31', '10.0.0.0'),
    ('192.168.1.0/31', '192.168.1.0'),

    ('10.0.0.5/32', '10.0.0.5'),
    ('192.168.10.42/32', '192.168.10.42'),

    # IPv6 reserves nothing: the first assignable address is the network address itself
    ('2001:db8::/64', '2001:db8::'),
    ('2001:db8:abcd::/48', '2001:db8:abcd::'),
    ('::1/128', '::1'),
])
def test_first_assignable_int(cidr: str, expected_first_address: str) -> None:
    """IPv4: skip network for /<=30, include it for /31, /32. IPv6: always the network address"""
    network: IPv4Network | IPv6Network = parse_cidr(cidr)
    expected_int: int = int(parse_ip(expected_first_address))

    assert first_assignable_int(network) == expected_int


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_canonical_cidr_value                                               #
# -------------------------------------------------------------------------------------------------------------------- #
SAMPLE_ERROR_CODE: str = 'sample_cidr_invalid'


def test_validate_canonical_cidr_value_returns_network_and_no_errors_for_canonical_input() -> None:
    """A canonical CIDR string yields the parsed network and an empty error list"""
    network, errors = validate_canonical_cidr_value('10.0.0.0/24', SAMPLE_ERROR_CODE)

    assert network == IPv4Network('10.0.0.0/24')
    assert not errors


@pytest.mark.parametrize('invalid_value', [
    'not-a-cidr',
    '10.0.0.5/24',       # host bits set, non-canonical
    '10.0.0.0',          # missing prefix
    '10.0.0.0/255.255.255.0',  # netmask form rejected by strict parser
])
def test_validate_canonical_cidr_value_emits_error_for_invalid_string(invalid_value: str) -> None:
    """Any non-canonical or non-CIDR string yields (None, [error]) with the caller's error code"""
    network, errors = validate_canonical_cidr_value(invalid_value, SAMPLE_ERROR_CODE)

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SAMPLE_ERROR_CODE


@pytest.mark.parametrize('non_string_value', [None, 42, 10.5, [], {}])
def test_validate_canonical_cidr_value_emits_error_for_non_string_input(non_string_value: Any) -> None:
    """Non-string inputs are rejected with the same error code (no TypeError raised)"""
    network, errors = validate_canonical_cidr_value(non_string_value, SAMPLE_ERROR_CODE)

    assert network is None
    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == SAMPLE_ERROR_CODE


def test_validate_canonical_cidr_value_captures_input_in_error_details() -> None:
    """The raw input value is preserved under IpamValidationDetailKey.NETWORK_RANGE in details"""
    network, errors = validate_canonical_cidr_value('garbage-value', SAMPLE_ERROR_CODE)

    assert network is None
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.NETWORK_RANGE] == 'garbage-value'


def test_validate_canonical_cidr_value_uses_caller_supplied_error_code() -> None:
    """The error code is parameterized; different callers see different codes for the same input"""
    _, first_errors = validate_canonical_cidr_value('bad', 'code_a')
    _, second_errors = validate_canonical_cidr_value('bad', 'code_b')

    assert first_errors[0][ValidationErrorKey.CODE] == 'code_a'
    assert second_errors[0][ValidationErrorKey.CODE] == 'code_b'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  address_family                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_address_family_returns_ipv4_for_ipv4_address() -> None:
    """A parsed IPv4 address maps to the IpAddressFamily.IPV4 token"""
    assert address_family(parse_ip('10.0.0.5')) == IpAddressFamily.IPV4


def test_address_family_returns_ipv6_for_ipv6_address() -> None:
    """A parsed IPv6 address maps to the IpAddressFamily.IPV6 token"""
    assert address_family(parse_ip('2001:db8::5')) == IpAddressFamily.IPV6
