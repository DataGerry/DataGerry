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
A cache that lives exactly as long as the current request - for reads that cannot change within one request and are
asked for by several callers
"""
from typing import Any

from flask import has_request_context, request
# -------------------------------------------------------------------------------------------------------------------- #


def request_cache(key: str) -> dict[Any, Any] | None:
    """
    Returns the per-request cache under the given key, creating it on first use

    Kept on the REQUEST object, which lives exactly as long as the request. `flask.g` would too, as long as nothing
    pushes an application context of its own inside the request - and none of the decorators does

    Args:
        key (str): The request attribute holding the cache

    Returns:
        dict[Any, Any] | None: The cache, or None when there is no request to scope it to (a unit test calling a
            helper directly, or a CLI code path)
    """
    if not has_request_context():
        return None

    cache: dict[Any, Any] | None = getattr(request, key, None)

    if cache is None:
        cache = {}
        setattr(request, key, cache)

    return cache
