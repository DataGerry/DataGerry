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
Where a CmdbWebhook may deliver to: public addresses only

The server itself POSTs every matching object write to a webhook's URL, from inside the installation's network, so
the URL decides which hosts the server talks to. **A destination is refused when its host resolves to any address
that is not public**: loopback, private (RFC 1918, ``fc00::/7``), link-local (the cloud metadata address
``169.254.169.254`` included), shared (``100.64.0.0/10``), unspecified, multicast, reserved or documentation ranges -
an IPv4-mapped IPv6 address is judged by the IPv4 address it carries. The check runs on the **resolved** addresses,
not on the URL's text, so ``http://2130706433/`` and ``http://0x7f.1/`` (both 127.0.0.1) are refused like
``http://127.0.0.1/``.

It runs twice: when a webhook is saved (``webhook_helper._validated_webhook_url``, a 400 naming the reason) and again
before every delivery (``webhook_helper.deliver_webhook_event``), because a host name can resolve differently later -
and deliveries never follow a redirect, which would otherwise carry the request to a host nobody checked. A host that
does not resolve is not judged here: nothing can be delivered to it, and the delivery fails as it always did.

``allowed_hosts`` lets named hosts or networks through; it is empty until an operator setting feeds it
"""
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import (
    WEBHOOK_DEFAULT_PORTS,
    WebhookDestinationReason,
)
# -------------------------------------------------------------------------------------------------------------------- #

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def is_public_address(address: IpAddress) -> bool:
    """
    Whether one address is a public, unicast internet address

    Args:
        address (IpAddress): The address

    Returns:
        bool: True for a global unicast address; False for loopback, private, link-local, shared, unspecified,
            multicast, reserved and documentation ranges
    """
    mapped: IpAddress | None = getattr(address, 'ipv4_mapped', None)

    if mapped is not None:
        address = mapped

    return address.is_global and not address.is_multicast


def resolve_addresses(host: str, port: int) -> list[IpAddress]:
    """
    Every address a host name (or address literal) resolves to

    Args:
        host (str): The URL's host
        port (int): The URL's port

    Returns:
        list[IpAddress]: The resolved addresses; empty when the host does not resolve
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return []

    # A scoped IPv6 address carries its zone ('fe80::1%eth0'); the zone is not part of the address
    return [ipaddress.ip_address(str(info[4][0]).split('%', maxsplit=1)[0]) for info in infos]


def _is_allowed(host: str, addresses: list[IpAddress], allowed_hosts: Iterable[str]) -> bool:
    """
    Whether an operator let this host through by name, or let every one of its addresses through by network

    Args:
        host (str): The URL's host
        addresses (list[IpAddress]): What it resolved to
        allowed_hosts (Iterable[str]): Host names and CIDR networks

    Returns:
        bool: True when the host is listed, or every address falls inside a listed network
    """
    names: set[str] = set()
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

    for entry in allowed_hosts:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            names.add(entry.strip().lower())

    if host.lower() in names:
        return True

    return bool(addresses) and all(any(address in network for network in networks) for address in addresses)


def refused_destination_reason(url: str, allowed_hosts: Iterable[str] = ()) -> str | None:
    """
    Judges a webhook URL's destination

    Args:
        url (str): The webhook's URL, already known to carry an http(s) scheme and a host
        allowed_hosts (Iterable[str]): Host names and CIDR networks let through anyway. Defaults to none

    Returns:
        str | None: Why the destination is refused, or None when it may be delivered to (or does not resolve)
    """
    parts = urlsplit(url)
    host: str | None = parts.hostname

    if not host:
        return WebhookDestinationReason.NO_HOST.value

    try:
        port: int = parts.port or WEBHOOK_DEFAULT_PORTS.get(parts.scheme.lower(), WEBHOOK_DEFAULT_PORTS['http'])
    except ValueError:
        return WebhookDestinationReason.INVALID_PORT.value

    addresses: list[IpAddress] = resolve_addresses(host, port)

    if _is_allowed(host, addresses, allowed_hosts):
        return None

    refused: list[str] = sorted({str(address) for address in addresses if not is_public_address(address)})

    if refused:
        return WebhookDestinationReason.NOT_PUBLIC.value.format(host=host, addresses=', '.join(refused))

    return None
