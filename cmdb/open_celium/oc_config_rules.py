# DataGerry - OpenSource Enterprise CMDB
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
What a usable on-premise `[OpenCelium]` section is - one rule for the status route and the connector

The connector composes `<protocol>://<host>:<port>/api` from the section and logs in with the credentials; the status
route (`GET /config_file/status/opencelium`) reports, per setting, whether that will work. Both read the section
through these functions, so a section the route reports ready is one the connector can use, and the connector reads
each value exactly as the route judged it:

* `port` - a whole number from `OC_MIN_PORT` to `OC_MAX_PORT`; a boolean or a fraction is no port (`parse_port`)
* `protocol` - `http` or `https`, in any case; the connector uses it lower-cased (`parse_protocol`)
* `host` - a name or an address only, IPv6 in brackets; a scheme, a port or a path inside it is refused
* every other setting (the credentials) - present and not blank
"""
import re
from typing import Any

from cmdb.utils import coerce_whole_number
from cmdb.open_celium.oc_constants import (
    OC_CONFIG_KEYS,
    OC_HOST_PATTERN,
    OC_MAX_PORT,
    OC_MIN_PORT,
    OC_PROTOCOLS,
    OcConfigKey,
)
# -------------------------------------------------------------------------------------------------------------------- #


def is_configured(value: Any) -> bool:
    """
    Whether a config value counts as configured: present and not blank

    Values arrive already cast by the reader's `auto_cast`, so a literal `false` / `0` setting is a bool / int here.
    Only absence and an empty (or whitespace-only) value mean "not configured" - a password of `false` is a password

    Args:
        value (Any): The value the section holds for a setting, or None when it holds none

    Returns:
        bool: True when the setting carries a non-blank value
    """
    return value is not None and str(value).strip() != ''


def parse_port(value: Any) -> int | None:
    """
    The TCP port a config value names, when it names one

    `coerce_whole_number` refuses booleans and fractions, so `port = true` or `port = 80.5` is no port rather than
    silently 1 or 80

    Args:
        value (Any): The value the section holds for the port, or None when unset

    Returns:
        int | None: The port, from `OC_MIN_PORT` to `OC_MAX_PORT`; None for anything else
    """
    port: int | None = coerce_whole_number(value)

    return port if port is not None and OC_MIN_PORT <= port <= OC_MAX_PORT else None


def parse_protocol(value: Any) -> str | None:
    """
    The URL scheme a config value names, lower-cased, when OpenCelium serves it

    Args:
        value (Any): The value the section holds for the protocol, or None when unset

    Returns:
        str | None: `http` or `https`; None for anything else (`ftp`, `https://`, a typo)
    """
    if not isinstance(value, str):
        return None

    protocol: str = value.strip().lower()

    return protocol if protocol in OC_PROTOCOLS else None


def is_usable_host(value: Any) -> bool:
    """
    Whether a config value is a host the connector can put between `://` and `:<port>`

    Args:
        value (Any): The value the section holds for the host, or None when unset

    Returns:
        bool: True for a host name, an IPv4 address or a bracketed IPv6 address (`OC_HOST_PATTERN`)
    """
    return value is not None and re.fullmatch(OC_HOST_PATTERN, str(value).strip()) is not None


def is_usable_setting(key: OcConfigKey, value: Any) -> bool:
    """
    Whether one `[OpenCelium]` setting is usable

    Args:
        key (OcConfigKey): The setting
        value (Any): The value the section holds for it, or None when it holds none

    Returns:
        bool: The port, protocol and host by their own rule; every other setting when it is configured
    """
    if key is OcConfigKey.PORT:
        return parse_port(value) is not None

    if key is OcConfigKey.PROTOCOL:
        return parse_protocol(value) is not None

    if key is OcConfigKey.HOST:
        return is_usable_host(value)

    return is_configured(value)


def oc_setting_flags(section_values: dict[str, Any]) -> dict[str, bool]:
    """
    One usable-flag per `[OpenCelium]` setting

    Args:
        section_values (dict[str, Any]): The section as the config reader serves it (cast values)

    Returns:
        dict[str, bool]: Every `OC_CONFIG_KEYS` key, in order, with whether its value is usable
    """
    return {key.value: is_usable_setting(key, section_values.get(key.value)) for key in OC_CONFIG_KEYS}


def unusable_oc_settings(section_values: dict[str, Any]) -> list[str]:
    """
    The `[OpenCelium]` settings that are not usable

    Args:
        section_values (dict[str, Any]): The section as the config reader serves it (cast values)

    Returns:
        list[str]: Their keys, in section order; empty when the section is ready
    """
    return [key for key, usable in oc_setting_flags(section_values).items() if not usable]
