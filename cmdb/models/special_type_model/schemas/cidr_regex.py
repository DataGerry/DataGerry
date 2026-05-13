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
Shared regular expressions used by SpecialType schemas
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Matches an IPv4 CIDR (e.g. '10.0.0.0/8'). Each octet is 0-255 and the prefix length is 0-32.
# IPv6 is intentionally not supported yet
IPV4_CIDR_REGEX: str = (
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)'
    r'(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)){3})'
    r'/(?:3[0-2]|[12]?\d)$'
)
