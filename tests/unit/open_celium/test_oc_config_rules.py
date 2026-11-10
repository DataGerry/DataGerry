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
Unit tests for cmdb.open_celium.oc_config_rules - what a usable `[OpenCelium]` section is

The one rule the status route reports with and the connector reads with; pure functions, no config file
"""
from typing import Any

import pytest

from cmdb.open_celium.oc_config_rules import (
    is_configured,
    is_usable_host,
    is_usable_setting,
    oc_setting_flags,
    parse_port,
    parse_protocol,
    unusable_oc_settings,
)
from cmdb.open_celium.oc_constants import OC_CONFIG_KEYS, OC_MAX_PORT, OC_MIN_PORT, OC_PROTOCOLS, OcConfigKey
# -------------------------------------------------------------------------------------------------------------------- #

READY_SECTION: dict[str, Any] = {
    'host': 'oc.example.com', 'port': 9090, 'protocol': 'http',
    'email': 'oc@example.com', 'user': 'oc-user', 'password': 'oc-password',
}
PORT_NUMBER: int = 9090


def test_the_bounds_are_the_tcp_port_range() -> None:
    """1 to 65535, the two schemes OpenCelium serves"""
    assert (OC_MIN_PORT, OC_MAX_PORT, OC_PROTOCOLS) == (1, 65535, frozenset({'http', 'https'}))


@pytest.mark.parametrize('value, expected', [
    (None, False), ('', False), ('   ', False), ('127.0.0.1', True), (PORT_NUMBER, True), (0, True), (False, True),
])
def test_is_configured(value: Any, expected: bool) -> None:
    """Only an absent or blank value counts as unconfigured - a literal 0 / false is a real value"""
    assert is_configured(value) is expected


@pytest.mark.parametrize('value, expected', [
    (PORT_NUMBER, PORT_NUMBER), (str(PORT_NUMBER), PORT_NUMBER), (float(PORT_NUMBER), PORT_NUMBER),
    (OC_MIN_PORT, OC_MIN_PORT), (OC_MAX_PORT, OC_MAX_PORT),
    (OC_MAX_PORT + 1, None), (0, None), (-1, None), (None, None), ('', None), ('not-a-port', None),
    (80.5, None), (True, None),
], ids=['int', 'string', 'whole-float', 'min', 'max', 'above-max', 'zero', 'negative', 'none', 'empty', 'word',
        'fraction', 'boolean'])
def test_parse_port(value: Any, expected: int | None) -> None:
    """A whole number from 1 to 65535; a boolean or a fraction is no port"""
    assert parse_port(value) == expected


@pytest.mark.parametrize('value, expected', [
    ('http', 'http'), ('https', 'https'), ('HTTPS', 'https'), (' Http ', 'http'),
    ('ftp', None), ('https://', None), ('htps', None), ('', None), (None, None), (True, None),
], ids=['http', 'https', 'upper', 'padded', 'ftp', 'with-separator', 'typo', 'empty', 'none', 'boolean'])
def test_parse_protocol(value: Any, expected: str | None) -> None:
    """http or https in any case, lower-cased; anything else is no scheme OpenCelium serves"""
    assert parse_protocol(value) == expected


@pytest.mark.parametrize('value, expected', [
    ('oc.example.com', True), ('127.0.0.1', True), ('oc_internal', True), ('[::1]', True),
    ('[fe80::1%eth0]', True), ('http://oc', False), ('oc:9090', False), ('oc/api', False), ('::1', False),
    ('user@oc', False), ('oc host', False), ('', False), (None, False),
], ids=['name', 'ipv4', 'underscore', 'ipv6', 'ipv6-zone', 'scheme', 'port', 'path', 'bare-ipv6', 'user',
        'whitespace', 'empty', 'none'])
def test_is_usable_host(value: Any, expected: bool) -> None:
    """A name or an address only - nothing the composed URL would read as a scheme, port, path or user"""
    assert is_usable_host(value) is expected


@pytest.mark.parametrize('key, value, expected', [
    (OcConfigKey.PORT, OC_MAX_PORT + 1, False), (OcConfigKey.PROTOCOL, 'ftp', False),
    (OcConfigKey.HOST, 'http://oc', False), (OcConfigKey.EMAIL, ' ', False), (OcConfigKey.PASSWORD, False, True),
], ids=['port', 'protocol', 'host', 'credential-blank', 'credential-false'])
def test_each_setting_is_judged_by_its_own_rule(key: OcConfigKey, value: Any, expected: bool) -> None:
    """Port, protocol and host by their rule; the credentials by presence"""
    assert is_usable_setting(key, value) is expected


def test_a_ready_section_flags_every_setting_and_names_none() -> None:
    """Every key, in section order"""
    assert oc_setting_flags(READY_SECTION) == {key.value: True for key in OC_CONFIG_KEYS}
    assert unusable_oc_settings(READY_SECTION) == []


def test_the_unusable_settings_are_named_in_section_order() -> None:
    """A missing key counts too"""
    section: dict[str, Any] = {**READY_SECTION, 'protocol': 'ftp', 'host': 'oc:9090'}
    del section['user']

    assert unusable_oc_settings(section) == ['host', 'protocol', 'user']
