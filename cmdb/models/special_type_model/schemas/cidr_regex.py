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
Shared IP validation regexes used by the IPAM schemas and section templates

CIDR_REGEX matches a network range (address plus '/prefix'); IP_ADDRESS_REGEX matches a bare host
address. Both accept either IPv4 or IPv6, matching the downstream IPAM processing layer (cidr.py,
validators, overviews), which handles both families. These are coarse field-level guards only -
the canonical validation (host-bits-zero, family-specific semantics) is done in code via the
ipaddress module in cmdb.framework.ipam.cidr
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Building blocks (no anchors); only the exported regexes below are anchored
_IPV4_OCTET: str = r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)'
_IPV4: str = rf'(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}'
_IPV4_PREFIX: str = r'(?:3[0-2]|[12]?\d)'

# Full IPv6 form: every '::' compression case plus IPv4-mapped / IPv4-embedded tails
_IPV6: str = (
    r'(?:'
    r'(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,7}:'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}'
    r'|(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}'
    r'|[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}'
    r'|:(?:(?::[0-9A-Fa-f]{1,4}){1,7}|:)'
    rf'|::(?:ffff(?::0{{1,4}})?:)?{_IPV4}'
    rf'|(?:[0-9A-Fa-f]{{1,4}}:){{1,4}}:{_IPV4}'
    r')'
)
_IPV6_PREFIX: str = r'(?:12[0-8]|1[01]\d|\d{1,2})'

# Matches a valid IPv4 or IPv6 CIDR (e.g. '10.0.0.0/8' or '2001:db8::/32')
CIDR_REGEX: str = rf'^(?:{_IPV4}/{_IPV4_PREFIX}|{_IPV6}/{_IPV6_PREFIX})$'

# Matches a valid IPv4 or IPv6 host address (no '/prefix', e.g. '192.0.2.10' or '2001:db8::1')
IP_ADDRESS_REGEX: str = rf'^(?:{_IPV4}|{_IPV6})$'
