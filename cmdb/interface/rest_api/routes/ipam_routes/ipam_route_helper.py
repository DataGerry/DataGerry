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
Shared request readers for the IPAM route modules

Every paginated IPAM view reads the same `page` / `page_size` / `search` triple off the query string
with the same defaults and the same truncation, and every IPAM write route reads the same JSON object
body, so the parsing lives here instead of being repeated per route. These helpers only normalise what
arrives on the wire - the values are still validated by the framework-layer builders that consume them
"""
from typing import Any

from flask import abort, request

from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamPagination,
    IpamSearch,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Page number served when the client sends none, an unparsable one, or an explicit 0
DEFAULT_PAGE: int = 1


def read_pagination_params() -> tuple[int, int]:
    """
    Reads the `page` / `page_size` pair off the current request's query string

    A missing, unparsable or zero value falls back to the default; the builders clamp the result
    into the valid range afterwards, so no bounds are enforced here

    Returns:
        tuple[int, int]: The requested page number and page size
    """
    page: int = request.args.get(IpamOverviewKey.PAGE, default=DEFAULT_PAGE, type=int) or DEFAULT_PAGE
    page_size: int = (
        request.args.get(IpamOverviewKey.PAGE_SIZE, default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
        or IpamPagination.DEFAULT_PAGE_SIZE
    )

    return page, page_size


def read_search_param() -> str:
    """
    Reads the `search` filter off the current request's query string

    Truncated at `IpamSearch.MAX_QUERY_LENGTH` here so an oversized query never reaches a builder;
    queries shorter than `IpamSearch.MIN_QUERY_LENGTH` are ignored by the builders themselves

    Returns:
        str: The raw search query, truncated to the maximum length; empty when none was sent
    """
    raw_search: str = request.args.get(IpamOverviewKey.SEARCH, default='', type=str) or ''

    return raw_search[:IpamSearch.MAX_QUERY_LENGTH]


def read_json_object_body() -> dict[str, Any]:
    """
    Reads the current request's body as a JSON object

    A body that is absent, unparseable, or parses to something other than an object is rejected here.
    Without this guard `request.get_json(silent=True) or {}` turns all three cases into an empty dict,
    and the caller is told a required field is missing rather than that its body never arrived

    Raises:
        HTTPException: 400 when the body is not a JSON object

    Returns:
        dict[str, Any]: The decoded body
    """
    payload: Any = request.get_json(silent=True)

    if not isinstance(payload, dict):
        abort(400, "Request body must be a JSON object!")

    return payload
