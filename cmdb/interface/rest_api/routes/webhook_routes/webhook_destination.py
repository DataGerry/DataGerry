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

**The operator's allowlist.** An installation whose receiver is an internal service lists it in ``cmdb.conf``::

    [Webhooks]
    allowed_hosts = receiver.corp.local, 10.20.0.0/16

or in the environment as ``DATAGERRY_Webhooks_allowed_hosts`` (case-sensitive; it overrides the file). An entry is a
host name - let through by name, whatever it resolves to - or a CIDR network / single address, which lets a host
through when EVERY address it resolves to lies inside one. ``configured_allowed_hosts`` reads it on every check, so
the save and every delivery judge with the same list; an invalid entry is logged and ignored, and a missing section or
an unloaded config file is no allowlist at all. **The hosted cloud ignores it** (``--cloud`` without ``--local``): a
shared host's internal network is never a tenant's
"""
import ipaddress
import re
import socket
from collections.abc import Iterable
from logging import Logger, getLogger
from typing import Any
from urllib.parse import urlsplit

import cmdb
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import (
    WEBHOOK_DEFAULT_PORTS,
    WEBHOOKS_ALLOWED_HOST_PATTERN,
    WEBHOOKS_ALLOWED_HOSTS_KEY,
    WEBHOOKS_ALLOWED_HOSTS_SEPARATOR,
    WEBHOOKS_CONFIG_SECTION,
    WebhookDestinationReason,
)

from cmdb.errors.system_config import ConfigFileNotFound, ConfigNotLoaded, SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# What reading the setting may raise when there is nothing to read: no config file loaded, no [Webhooks] section, no
# allowed_hosts key in it - each simply means "no allowlist"
UNREADABLE_SETTING_ERRORS: tuple[type[Exception], ...] = (ConfigFileNotFound, ConfigNotLoaded, SectionError, KeyError)

_ALLOWED_HOST_NAME: re.Pattern[str] = re.compile(WEBHOOKS_ALLOWED_HOST_PATTERN)


def is_valid_allowlist_entry(entry: str) -> bool:
    """
    Whether an allowlist entry is a network / address or a well-formed host name

    Args:
        entry (str): One stripped, non-empty entry

    Returns:
        bool: True for an IPv4 / IPv6 network or address (host bits allowed) or a host name
    """
    try:
        ipaddress.ip_network(entry, strict=False)
        return True
    except ValueError:
        return bool(_ALLOWED_HOST_NAME.fullmatch(entry))


def parse_allowed_hosts(raw: Any) -> tuple[str, ...]:
    """
    The entries of an ``allowed_hosts`` setting: split at commas, stripped, blanks dropped, invalid ones ignored

    The config reader casts a value it can read as a number or a boolean (``auto_cast``), so a non-string value - a
    lone ``10`` - is no host and is ignored whole. Every ignored entry is logged as a warning naming it, so a typo is
    visible without stopping the server

    Args:
        raw (Any): The setting's value as the config reader serves it; None or empty for none

    Returns:
        tuple[str, ...]: The valid entries, in the order given
    """
    if raw is None:
        return ()

    if not isinstance(raw, str):
        # The reader cast it (a lone number or boolean): no host name or network reads like that
        LOGGER.warning("[parse_allowed_hosts] Ignoring the invalid [%s] %s value '%s'",
                       WEBHOOKS_CONFIG_SECTION, WEBHOOKS_ALLOWED_HOSTS_KEY, raw)
        return ()

    entries: list[str] = []

    for part in raw.split(WEBHOOKS_ALLOWED_HOSTS_SEPARATOR):
        entry: str = part.strip()

        if not entry:
            continue

        if is_valid_allowlist_entry(entry):
            entries.append(entry)
        else:
            LOGGER.warning("[parse_allowed_hosts] Ignoring the invalid [%s] %s entry '%s'",
                           WEBHOOKS_CONFIG_SECTION, WEBHOOKS_ALLOWED_HOSTS_KEY, entry)

    return tuple(entries)


def is_hosted_cloud() -> bool:
    """
    Whether this process is the hosted cloud product - ``--cloud`` without ``--local``

    Returns:
        bool: True in the hosted cloud, where the operator allowlist is ignored
    """
    return bool(cmdb.__CLOUD_MODE__) and not cmdb.__LOCAL_MODE__


def configured_allowed_hosts() -> tuple[str, ...]:
    """
    The operator's allowlist of webhook destinations, read from the configuration on every call

    Returns:
        tuple[str, ...]: Host names and networks let through although not public; empty in the hosted cloud, and when
            the configuration holds no ``[Webhooks] allowed_hosts`` (or no config file is loaded)
    """
    if is_hosted_cloud():
        return ()

    try:
        raw: Any = SystemConfigReader().get_value(WEBHOOKS_ALLOWED_HOSTS_KEY, WEBHOOKS_CONFIG_SECTION, default=None)
    except UNREADABLE_SETTING_ERRORS:
        return ()

    return parse_allowed_hosts(raw)


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
