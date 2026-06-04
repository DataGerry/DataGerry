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
Pure CIDR helpers used across the IPAM feature (IPv4 and IPv6)

Consumers include both the validators (subnet, supernet, interface, range-change guards,
enforcement) and the overview builders (subnet overview, supernet overview). Every helper
here is stateless and free of DB / Flask access so it can be unit-tested in isolation.
Parsing accepts either address family via the ipaddress module's version-agnostic factories;
the containment / overlap helpers treat two networks of different families as disjoint (the
stdlib raises TypeError when mixing families, so each helper guards on '.version' first).
Prefix-length policy constants (point-to-point threshold, network/broadcast reservation) live
in cmdb.models.special_type_model.ipam_constants.IpamPrefixPolicy and apply to IPv4 only -
IPv6 reserves neither a network nor a broadcast address
"""
from ipaddress import (
    ip_network,
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
)
from typing import Any

from cmdb.models.special_type_model.ipam_constants import (
    IpamAddressFormat,
    IpamPrefixPolicy,
    IpamValidationDetailKey,
    IpVersion,
    IpAddressFamily,
)
from cmdb.utils import build_error
# -------------------------------------------------------------------------------------------------------------------- #

# Family-agnostic aliases: an IPAM network / address is either the IPv4 or the IPv6 variant
Network = IPv4Network | IPv6Network
Address = IPv4Address | IPv6Address


def parse_cidr(value: str) -> Network | None:
    """
    Parses a string as a strict IPv4 or IPv6 CIDR network in canonical 'address/N' notation

    Strict on two axes. Host bits must be zero (e.g. '10.0.0.0/24' and '2001:db8::/32' are
    accepted, '10.0.0.5/24' is not). The prefix length must be a plain integer; Python's
    ip_network would additionally accept IPv4 '/A.B.C.D' netmask or hostmask forms
    ('/255.255.255.0', '/0.0.0.255') and a bare address with no slash (interpreting it as a
    host route), but those forms are rejected here so stored values are always canonical CIDR.
    The address family is inferred from the value: a string with a ':' parses as IPv6

    Args:
        value (str): The candidate CIDR string

    Returns:
        Network | None: The parsed IPv4Network / IPv6Network, or None if the input is not
            canonical CIDR
    """
    if not isinstance(value, str):
        return None

    if '/' not in value:
        return None

    _, _, prefix_part = value.rpartition('/')

    if not prefix_part.isdigit():
        return None

    try:
        return ip_network(value, strict=True)
    except ValueError:
        return None


def validate_canonical_cidr_value(
    value: Any,
    error_code: str,
) -> tuple[Network | None, list[dict[str, Any]]]:
    """
    Validates an arbitrary value is a canonical IPv4 or IPv6 CIDR string, surfacing a structured
    error when it is not

    Accepts Any so callers passing a raw field value (which may be None / int / something else
    from a partially populated CmdbObject) don't have to guard the call themselves. Non-string
    inputs and non-canonical strings both fail with the same caller-supplied error code so the
    emitted error stays meaningful to the surrounding validator

    Args:
        value (Any): The candidate value (typically a 'dg-network-range' field value)
        error_code (str): Error code to embed in the emitted error dict when validation fails
            (callers pass their domain-specific code, e.g. SubnetErrorCode.CIDR_INVALID)

    Returns:
        tuple[Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors;
            empty list when the value is canonical)
    """
    parsed: Network | None = parse_cidr(value) if isinstance(value, str) else None

    if parsed is None:
        return None, [build_error(
            error_code,
            f"'{value}' is not a canonical IPv4/IPv6 CIDR (host bits must be zero)",
            {IpamValidationDetailKey.NETWORK_RANGE: value},
        )]

    return parsed, []


def parse_ip(value: str) -> Address | None:
    """
    Parses a string as an IPv4 (dotted-quad) or IPv6 host address

    The family is selected by syntax: a string containing ':' is parsed as IPv6, otherwise it
    must be canonical dotted-quad IPv4 ('A.B.C.D'). For IPv4, Python's IPv4Address would also
    accept integer-formatted strings (e.g. '3232235521' as 192.168.1.1) and bare integers, but
    those forms are rejected via the dot-count guard so that stored interface values are always
    human-readable. The function returns None for any input that is not a valid host address

    Args:
        value (str): The candidate IP address string

    Returns:
        Address | None: The parsed IPv4Address / IPv6Address, or None if the input is not a
            valid host address
    """
    if not isinstance(value, str):
        return None

    if ':' in value:
        try:
            return IPv6Address(value)
        except ValueError:
            return None

    if value.count('.') != IpamAddressFormat.DOTTED_QUAD_DOT_COUNT:
        return None

    try:
        return IPv4Address(value)
    except ValueError:
        return None


def network_family(network: Network) -> str:
    """
    Returns the address-family token of a parsed network as an IpAddressFamily value

    Single source of truth for mapping a parsed network to the 'ipv4' / 'ipv6' tokens used by
    the SUBNET / SUPERNET 'dg-*-type' selectors, so the validators (family-consistency checks)
    and the supernet overview (row grouping) agree on the mapping

    Args:
        network (Network): The parsed network

    Returns:
        str: IpAddressFamily.IPV6 for an IPv6 network, IpAddressFamily.IPV4 otherwise
    """
    return IpAddressFamily.IPV6 if network.version == IpVersion.V6 else IpAddressFamily.IPV4


def address_family(address: Address) -> str:
    """
    Returns the address-family token of a parsed host address as an IpAddressFamily value

    Address counterpart of ``network_family``: maps a parsed IP to the same 'ipv4' / 'ipv6'
    tokens the IPAM selectors use, so per-row family-consistency checks (e.g. the interface
    row's 'dg-interface-type' against its IP) agree with the network-level mapping

    Args:
        address (Address): The parsed host address

    Returns:
        str: IpAddressFamily.IPV6 for an IPv6 address, IpAddressFamily.IPV4 otherwise
    """
    return IpAddressFamily.IPV6 if address.version == IpVersion.V6 else IpAddressFamily.IPV4


def contains(parent: Network, child: Network) -> bool:
    """
    Reports whether 'child' is a subnet of (or equal to) 'parent'

    Networks of different address families are treated as disjoint (False) rather than raising,
    so a cross-family pair can be compared safely without a TypeError

    Args:
        parent (Network): The (potentially) enclosing network
        child (Network): The (potentially) enclosed network

    Returns:
        bool: True if every address in 'child' is also in 'parent', False otherwise (including
            when the two networks are of different families)
    """
    if parent.version != child.version:
        return False

    return child.subnet_of(parent)


def is_strict_subnet(parent: Network, child: Network) -> bool:
    """
    Reports whether 'child' is strictly inside 'parent' (subnet, but not equal)

    Networks of different address families are treated as disjoint (False) rather than raising

    Args:
        parent (Network): The enclosing network
        child (Network): The candidate child network

    Returns:
        bool: True if 'child' is contained in 'parent' AND not the same network, False otherwise
            (including when the two networks are of different families)
    """
    if parent.version != child.version:
        return False

    return child != parent and child.subnet_of(parent)


def overlaps(a: Network, b: Network) -> bool:
    """
    Reports whether two networks share any address

    Networks of different address families are treated as non-overlapping (False) rather than
    raising

    Args:
        a (Network): First network
        b (Network): Second network

    Returns:
        bool: True if the networks share at least one address, False otherwise (including when
            the two networks are of different families)
    """
    if a.version != b.version:
        return False

    return a.overlaps(b)


def ip_in_network(address: Address, network: Network) -> bool:
    """
    Reports whether an address falls inside a given network

    An address of a different family than the network is never a member (False), matching the
    address-family guard used by the network-to-network helpers

    Args:
        address (Address): The address to test
        network (Network): The network to test against

    Returns:
        bool: True if 'address' is part of 'network', False otherwise (including on a
            family mismatch)
    """
    if address.version != network.version:
        return False

    return address in network


def total_address_count(network: Network) -> int:
    """
    Returns the total number of addresses in a network, including the network and broadcast
    addresses

    This is the denominator used by the IP-Verteilung grid and the headline 'Gesamt IPs' KPI,
    where the address space is shown as a contiguous whole rather than split into 'usable' and
    'reserved' subsets. For IPv6 the value is a Python big int (e.g. 2**64 for a /64)

    Args:
        network (Network): The parsed network

    Returns:
        int: Total address count of the network (always >= 1)
    """
    return network.num_addresses


def assignable_address_count(network: Network) -> int:
    """
    Returns the number of addresses the interface validator would accept inside a network

    IPv6 reserves neither a network nor a broadcast address, so every address counts as
    assignable (num_addresses). For IPv4, /32 reports 1 (host route), /31 reports 2 (RFC 3021
    point-to-point), and /30 and shorter report 'num_addresses - 2' to exclude the network and
    broadcast addresses. This is the denominator used by 'free_ips' and by the paginated IP
    table, which only lists addresses that can actually be assigned

    Args:
        network (Network): The parsed network

    Returns:
        int: Number of addresses an interface row may legitimately claim
    """
    if network.version == IpVersion.V6:
        return network.num_addresses

    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return network.num_addresses

    return network.num_addresses - IpamPrefixPolicy.RESERVED_ADDRESSES_PER_NETWORK


def first_assignable_int(network: Network) -> int:
    """
    Returns the integer value of the first assignable address in a network

    IPv6 reserves no addresses, so the first assignable address is the network address itself.
    For IPv4 /31 and /32 this is also the network address (no exclusion applies); for IPv4 /30
    and shorter the network address is skipped and the first host follows at
    IpamPrefixPolicy.FIRST_HOST_OFFSET. Every valid prefix has at least one assignable address
    under the current policy, so the function always returns an int

    Args:
        network (Network): The parsed network

    Returns:
        int: Integer of the first assignable address
    """
    if network.version == IpVersion.V6:
        return int(network.network_address)

    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return int(network.network_address)

    return int(network.network_address) + IpamPrefixPolicy.FIRST_HOST_OFFSET


def is_network_or_broadcast(address: Address, network: Network) -> bool:
    """
    Reports whether an address equals the network address or the broadcast address of a network

    IPv6 has no broadcast address and reserves no network address, so the result is always
    False for an IPv6 network. For IPv4 /31 and /32 networks neither concept applies either, so
    the result is False there too

    Args:
        address (Address): The address to test
        network (Network): The network the address sits in

    Returns:
        bool: True if 'address' is the reserved network or broadcast address, False otherwise
    """
    if network.version == IpVersion.V6:
        return False

    if network.prefixlen >= IpamPrefixPolicy.POINT_TO_POINT_THRESHOLD:
        return False

    return address in (network.network_address, network.broadcast_address)
