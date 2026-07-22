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
Helper methods for CmdbSectionTemplate routes

Request-payload validation and coercion helpers shared by the CmdbSectionTemplate CRUD
routes. Each helper aborts with HTTP 400 on malformed input so the route handlers can
stay focused on orchestration.
"""
import json
from typing import Any

from flask import abort

from cmdb.utils.helpers import str_to_bool
# -------------------------------------------------------------------------------------------------------------------- #


def require_params(params: dict[str, Any], keys: list[str]) -> None:
    """
    Aborts 400 when any of the required request parameters is missing

    Args:
        params (dict[str, Any]): The parsed request parameters
        keys (list[str]): The parameter names that must be present
    """
    missing: list[str] = [key for key in keys if key not in params]

    if missing:
        abort(400, f"Missing required parameter(s): {', '.join(missing)}")


def parse_json_fields(raw: Any) -> Any:
    """
    Parses the JSON-encoded 'fields' parameter, aborting 400 on malformed input

    Args:
        raw (Any): The raw 'fields' parameter value (a JSON string)

    Returns:
        Any: The decoded JSON value
    """
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        abort(400, "The 'fields' parameter must be a valid JSON string!")


def coerce_bool(raw: Any) -> bool:
    """
    Coerces a request parameter to a bool, aborting 400 on an unrecognised value

    Args:
        raw (Any): The raw parameter value ('true' / 'false' or a native bool)

    Returns:
        bool: The coerced boolean
    """
    try:
        return str_to_bool(raw)
    except ValueError:
        abort(400, "Boolean parameters must be 'true' or 'false'!")


def coerce_public_id(raw: Any) -> int:
    """
    Coerces the 'public_id' parameter to an int, aborting 400 when it is not numeric

    Args:
        raw (Any): The raw 'public_id' parameter value

    Returns:
        int: The integer public_id
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, "The 'public_id' parameter must be an integer!")
