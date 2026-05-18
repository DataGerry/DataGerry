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
Pure IPv4 CIDR helpers used by the IPAM validators

Every helper is stateless and free of DB access so it can be unit-tested in isolation
"""
from ipaddress import IPv4Address, IPv4Network, AddressValueError, NetmaskValueError
# -------------------------------------------------------------------------------------------------------------------- #


def parse_cidr(value: str) -> IPv4Network | None:
    """
    Parses a string as a strict IPv4 CIDR network

    'Strict' means host bits must be zero (e.g. '10.0.0.0/24' is accepted, '10.0.0.5/24' is not)

    Args:
        value (str): The candidate CIDR string

    Returns:
        IPv4Network | None: The parsed network, or None if the string is not a strict IPv4 CIDR
    """
    if not isinstance(value, str):
        return None

    try:
        return IPv4Network(value, strict=True)
    except (AddressValueError, NetmaskValueError, ValueError):
        return None


def is_canonical_cidr(value: str) -> bool:
    """
    Reports whether a string is a syntactically valid, canonical IPv4 CIDR

    'Canonical' means host bits are zero (network address form)

    Args:
        value (str): The candidate CIDR string

    Returns:
        bool: True if the value parses as a strict IPv4 CIDR, False otherwise
    """
    return parse_cidr(value) is not None


def parse_ipv4(value: str) -> IPv4Address | None:
    """
    Parses a string as an IPv4 address

    Args:
        value (str): The candidate IPv4 address string

    Returns:
        IPv4Address | None: The parsed address, or None if the string is not a valid IPv4 address
    """
    if not isinstance(value, str):
        return None

    try:
        return IPv4Address(value)
    except (AddressValueError, ValueError):
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
    if network.prefixlen >= 31:
        return network.num_addresses

    return network.num_addresses - 2


def first_assignable_int(network: IPv4Network) -> int | None:
    """
    Returns the integer value of the first assignable address in a network

    For /31 and /32 this is the network address itself (no exclusion). For /30 and shorter the
    network address is skipped. Returns None only when the network has zero assignable
    addresses, which currently cannot occur for any valid IPv4 prefix

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int | None: Integer of the first assignable address, or None if none exist
    """
    if assignable_address_count(network) == 0:
        return None

    if network.prefixlen >= 31:
        return int(network.network_address)

    return int(network.network_address) + 1


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
    if network.prefixlen >= 31:
        return False

    return address == network.network_address or address == network.broadcast_address
