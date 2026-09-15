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
All general helper methods for Document Generator
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# Conversion factor from millimetres to typographic points (1 mm = 72 / 25.4 pt)
MM_TO_PT_FACTOR: float = 2.83465
# CSS length unit appended to numeric style values
PT_UNIT: str = "pt"
# CSS property that must stay unitless
LINE_HEIGHT_PROP: str = "line-height"


def mm_to_pt(value: Any, default: int) -> int:
    """
    Converts a length from millimetres to (rounded down) typographic points

    A falsy value (None, 0 or an empty string) is treated as unset and yields `default`; a value
    that cannot be parsed as a number also yields `default`.

    Args:
        value (Any): The length in mm (number or numeric string), or a falsy value for "unset"
        default (int): The value to return when `value` is unset or unparseable

    Returns:
        int: The length in points, or `default`
    """
    try:
        if not value:
            return default

        return int(float(value) * MM_TO_PT_FACTOR)
    except (TypeError, ValueError):
        return default


def format_value(prop: str, value: Any) -> str:
    """
    Formats a CSS property value, adding a pt unit to bare numbers

    The line-height property is kept unitless; every other numeric value gets a pt unit, and
    non-numeric values are stringified as-is.

    Args:
        prop (str): The CSS property name the value belongs to
        value (Any): The value to format

    Returns:
        str: The formatted CSS value
    """
    if prop == LINE_HEIGHT_PROP:
        return str(value)  # unitless

    if isinstance(value, (int, float)):
        return f"{value}{PT_UNIT}"

    return str(value)
