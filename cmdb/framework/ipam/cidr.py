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
Pure IPv4 CIDR helpers used across the IPAM feature

Consumers include both the validators (subnet, supernet, interface, range-change guards,
enforcement) and the overview builders (subnet overview, supernet overview). Every helper
here is stateless and free of DB / Flask access so it can be unit-tested in isolation.
Prefix-length policy constants (point-to-point threshold, network/broadcast reservation)
live in cmdb.models.special_type_model.ipam_constants.IpamPrefixPolicy
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from cmdb.models.special_type_model.ipam_constants import (
    IpamAddressFormat,
    IpamPrefixPolicy,
    IpamValidationDetailKey,
)
from cmdb.utils import build_error
# -------------------------------------------------------------------------------------------------------------------- #


def parse_cidr(value: str) -> IPv4Network | None:
    """
    Parses a string as a strict IPv4 CIDR network in canonical 'A.B.C.D/N' notation

    Strict on two axes. Host bits must be zero (e.g. '10.0.0.0/24' is accepted, '10.0.0.5/24'
    is not). The prefix length must be a plain integer (e.g. '10.0.0.0/24'); Python's
    IPv4Network would additionally accept '/A.B.C.D' netmask or hostmask forms ('/255.255.255.0',
    '/0.0.0.255') and a bare address with no slash (interpreting it as a /32 host route), but
    those forms are rejected here so stored values are always canonical CIDR

    Args:
        value (str): The candidate CIDR string

    Returns:
        IPv4Network | None: The parsed network, or None if the input is not canonical CIDR
    """
    if not isinstance(value, str):
        return None

    if '/' not in value:
        return None

    _, _, prefix_part = value.rpartition('/')

    if not prefix_part.isdigit():
        return None

    try:
        return IPv4Network(value, strict=True)
    except ValueError:
        return None


def validate_canonical_cidr_value(
    value: Any,
    error_code: str,
) -> tuple[IPv4Network | None, list[dict[str, Any]]]:
    """
    Validates an arbitrary value is a canonical IPv4 CIDR string, surfacing a structured error
    when it is not

    Accepts Any so callers passing a raw field value (which may be None / int / something else
    from a partially populated CmdbObject) don't have to guard the call themselves. Non-string
    inputs and non-canonical strings both fail with the same caller-supplied error code so the
    emitted error stays meaningful to the surrounding validator

    Args:
        value (Any): The candidate value (typically a 'dg-network-range' field value)
        error_code (str): Error code to embed in the emitted error dict when validation fails
            (callers pass their domain-specific code, e.g. SubnetErrorCode.CIDR_INVALID)

    Returns:
        tuple[IPv4Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors;
            empty list when the value is canonical)
    """
    parsed: IPv4Network | None = parse_cidr(value) if isinstance(value, str) else None

    if parsed is None:
        return None, [build_error(
            error_code,
            f"'{value}' is not a canonical IPv4 CIDR (host bits must be zero)",
            {IpamValidationDetailKey.NETWORK_RANGE: value},
        )]

    return parsed, []


def parse_ipv4(value: str) -> IPv4Address | None:
    """
    Parses a string as an IPv4 address in dotted-quad notation

    Only the canonical dotted-quad form ('A.B.C.D') is accepted. Python's IPv4Address would
    additionally accept integer-formatted strings (e.g. '3232235521' as 192.168.1.1) and bare
    integers, but those forms are rejected here so that stored interface values are always
    human-readable. The function returns None for any input that is not a four-octet string

    Args:
        value (str): The candidate IPv4 address string

    Returns:
        IPv4Address | None: The parsed address, or None if the input is not a valid
            dotted-quad IPv4 address
    """
    if not isinstance(value, str):
        return None

    if value.count('.') != IpamAddressFormat.DOTTED_QUAD_DOT_COUNT:
        return None

    try:
        return IPv4Address(value)
    except ValueError:
        return None


def contains(parent: IPv4Network, child: IPv4Network) -> bool:
    """
    Reports whether 'child' is a subnet of (or equal to) 'parent'

    Args:
        parent (IPv4Network): The (potentially) enclosing network
        child (IPv4Network): The (potentially) enclosed network

    Returns:
        bool: True if every address in 'child' is also in 'parent', False otherwise
    """
    return child.subnet_of(parent)


def is_strict_subnet(parent: IPv4Network, child: IPv4Network) -> bool:
    """
    Reports whether 'child' is strictly inside 'parent' (subnet, but not equal)

    Args:
        parent (IPv4Network): The enclosing network
        child (IPv4Network): The candidate child network

    Returns:
        bool: True if 'child' is contained in 'parent' AND not the same network, False otherwise
    """
    return child != parent and child.subnet_of(parent)


def overlaps(a: IPv4Network, b: IPv4Network) -> bool:
    """
    Reports whether two IPv4 networks share any address

    Args:
        a (IPv4Network): First network
        b (IPv4Network): Second network

    Returns:
        bool: True if the networks share at least one address, False otherwise
    """
    return a.overlaps(b)


def ip_in_network(address: IPv4Address, network: IPv4Network) -> bool:
    """
    Reports whether an IPv4 address falls inside a given network

    Args:
        address (IPv4Address): The address to test
        network (IPv4Network): The network to test against

    Returns:
        bool: True if 'address' is part of 'network', False otherwise
    """
    return address in network


def total_address_count(network: IPv4Network) -> int:
    """
    Returns the total number of addresses in a network, including the network and broadcast
    addresses

    This is the denominator used by the IP-Verteilung grid and the headline 'Gesamt IPs' KPI,
    where the address space is shown as a contiguous whole rather than split into 'usable' and
    'reserved' subsets

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int: Total address count of the network (always >= 1)
    """
    return network.num_addresses


def assignable_address_count(network: IPv4Network) -> int:
    """
    Returns the number of addresses the interface validator would accept inside a network

    /32 reports 1 (host route), /31 reports 2 (RFC 3021 point-to-point), and /30 and shorter
    report 'num_addresses - 2' to exclude the network and broadcast addresses. This is the
    denominator used by 'free_ips' and by the paginated IP table, which only lists addresses
    that can actually be assigned

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int: Number of addresses an interface row may legitimately claim
    """
    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return network.num_addresses

    return network.num_addresses - IpamPrefixPolicy.RESERVED_ADDRESSES_PER_NETWORK


def first_assignable_int(network: IPv4Network) -> int:
    """
    Returns the integer value of the first assignable address in a network

    For /31 and /32 networks this is the network address itself (no exclusion applies). For
    /30 and shorter the network address is skipped and the first host follows at
    IpamPrefixPolicy.FIRST_HOST_OFFSET. Every valid IPv4 prefix has at least one assignable
    address under the current policy, so the function always returns an int

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int: Integer of the first assignable address
    """
    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return int(network.network_address)

    return int(network.network_address) + IpamPrefixPolicy.FIRST_HOST_OFFSET


def is_network_or_broadcast(address: IPv4Address, network: IPv4Network) -> bool:
    """
    Reports whether an address equals the network address or the broadcast address of a network

    For /31 and /32 networks neither concept applies, so the result is always False there

    Args:
        address (IPv4Address): The address to test
        network (IPv4Network): The network the address sits in

    Returns:
        bool: True if 'address' is the reserved network or broadcast address, False otherwise
    """
    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return False

    return address == network.network_address or address == network.broadcast_address
