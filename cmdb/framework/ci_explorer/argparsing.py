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
Pure validators / parsers for the query-string arguments accepted by /ci_explorer/items

Every helper takes already-extracted primitive values (no Flask `request` dependency) so
it can be exercised in isolation. Validators that detect bad client input call
`flask.abort(400, ...)` - the exception type is what the route's outer error handler
converts to a 4xx response, and tests assert against `werkzeug.exceptions.HTTPException`
"""
import ast

from flask import abort

from cmdb.models.ci_explorer_model import NodeType
# -------------------------------------------------------------------------------------------------------------------- #


def validate_target_id(raw_value: int | None) -> int:
    """
    Validates the required ``target_id`` query argument

    Args:
        raw_value (int | None): The value as parsed by request.args.get(..., type=int);
            None indicates the argument was missing or could not be parsed to an int

    Returns:
        int: The validated target_id

    Raises:
        HTTPException: 400 when ``raw_value`` is None
    """
    if raw_value is None:
        abort(400, "Missing ID of target Object!")

    return raw_value


def validate_node_type(raw_value: str) -> NodeType:
    """
    Validates the ``target_type`` query argument and returns the matching ``NodeType`` member

    Accepts the upper-case string form ('CHILD', 'PARENT', 'BOTH'). The caller is responsible
    for upper-casing before passing it in (matches the current route behaviour)

    Args:
        raw_value (str): The upper-case target_type value (e.g. 'BOTH')

    Returns:
        NodeType: The matching enum member

    Raises:
        HTTPException: 400 when ``raw_value`` is not a known NodeType member
    """
    if not NodeType.is_valid(raw_value):
        abort(
            400,
            f"Invalid target_type '{raw_value}'. Need one of: {', '.join(NodeType.__members__.keys())}",
        )

    return NodeType(raw_value)


def parse_bool_arg(raw_value: str | None, default: bool = False) -> bool:
    """
    Parses a string query argument into a bool using the route's existing convention

    The route compares ``.lower() == 'true'`` so 'TRUE', 'True', 'true' all map to True
    and anything else (including 'false', '1', 'yes' and missing) maps to ``default``.
    Kept verbatim so the wire-format the FE sends today continues to work

    Args:
        raw_value (str | None): The raw query-string value
        default (bool): Value returned when ``raw_value`` is None or empty

    Returns:
        bool: True when the value equals 'true' (case-insensitive); ``default`` otherwise
    """
    if raw_value is None or raw_value == '':
        return default

    return raw_value.lower() == 'true'


def clamp_item_limit(raw_value: int | None) -> int:
    """
    Normalises the ``item_limit`` query argument to a non-negative integer

    Matches the current route's contract: a missing, falsy or negative value collapses
    to ``0`` which means 'unlimited' downstream. Any positive integer is passed through

    Args:
        raw_value (int | None): The value as parsed by request.args.get(..., type=int);
            None indicates the argument was missing or unparsable

    Returns:
        int: A non-negative integer; 0 when unlimited / unset
    """
    if not raw_value or raw_value < 0:
        return 0

    return raw_value


def parse_int_list_filter(raw_value: str | None) -> frozenset[int]:
    """
    Parses a JSON-encoded list of integers into an immutable set

    Accepts the wire format the FE already sends - e.g. ``'[1,2,3]'`` - using
    ``ast.literal_eval`` (safe against arbitrary code execution). Empty/None input yields
    an empty set so the caller can branch on ``if filter:``. Anything that does not
    parse to a list of integers raises HTTP 400 with the argument name in the message

    Args:
        raw_value (str | None): The raw query-string value, or None when the argument
            was absent

    Returns:
        frozenset[int]: The parsed integers; empty when ``raw_value`` is missing / empty

    Raises:
        HTTPException: 400 when ``raw_value`` is not a JSON-style list of integers
    """
    if not raw_value:
        return frozenset()

    try:
        parsed = ast.literal_eval(raw_value)
    except (SyntaxError, ValueError):
        abort(400, "Invalid format for filter argument. Must be a list of integers like [1,2,3].")

    if not isinstance(parsed, list):
        abort(400, "Invalid format for filter argument. Must be a list of integers like [1,2,3].")

    try:
        return frozenset(int(item) for item in parsed)
    except (TypeError, ValueError):
        abort(400, "Invalid format for filter argument. Must be a list of integers like [1,2,3].")
