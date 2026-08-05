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
Shared search-input normalization helpers used by the IPAM overview builders

Concrete substring matchers (against subnet CIDRs, against IP addresses, against future
fields) live next to the data they filter; this module owns only the bits every IPAM
search route needs in common: stripping the raw query, applying the MIN_QUERY_LENGTH gate,
and reporting whether the query is active. The MAX_QUERY_LENGTH truncation is still the
route's responsibility - it happens once at the route boundary so deeper helpers do not
have to repeat it
"""
from cmdb.models.special_type_model.ipam_constants import IpamSearch
# -------------------------------------------------------------------------------------------------------------------- #


def active_search(search: str) -> str | None:
    """
    Normalizes a raw search query and reports whether it is active

    A query is active when, after stripping surrounding whitespace, it carries at least
    IpamSearch.MIN_QUERY_LENGTH characters. Active queries are returned as the stripped
    string callers should pass to their substring matcher; inactive queries
    (None / empty / whitespace / too short) return None so callers can keep the "no filter"
    branch as a simple ``is None`` check. The IpamSearch.MAX_QUERY_LENGTH truncation is
    the route's responsibility - this helper does not re-clip

    Args:
        search (str): Raw search query as received by the caller

    Returns:
        str | None: The stripped query when active, None otherwise
    """
    needle: str = (search or '').strip()

    if len(needle) >= IpamSearch.MIN_QUERY_LENGTH:
        return needle

    return None
