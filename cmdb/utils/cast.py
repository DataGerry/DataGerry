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
Auto-casting of the string values DataGerry reads from untyped sources

Both callers hand over text that carries no type information of its own and needs one before it is
stored or used:

    * `SystemConfigReader` casts every `etc/cmdb.conf` value and every `DATAGERRY_*` environment
      override, so `port = 27017` reaches the database manager as an `int` and `ssl = false` as a
      `bool` rather than as the strings configparser and `os.environ` hand back
    * the CSV object importer casts **every cell** of an uploaded file, so a spreadsheet column of
      numbers is stored as numbers instead of as text

`auto_cast` is therefore the only place that decides what an untyped value *becomes*, and its
conversions are deliberately narrow - see the per-function notes for what is and is not accepted
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# Accepted spellings of a boolean, compared case-insensitively against the stripped value
_TRUTHY_VALUES: frozenset[str] = frozenset({'true'})
_FALSY_VALUES: frozenset[str] = frozenset({'false'})

# Accepted spellings of an absent value. Deliberately compared as written - case-sensitively and
# without stripping - so only these two exact spellings are erased (see discussion-backlog #193)
_NONE_VALUES: tuple[str, ...] = ('None', 'null')

# -------------------------------------------------------------------------------------------------------------------- #

def boolify(s: Any) -> bool:
    """
    Converts a string representation of a boolean to its corresponding boolean value

    Accepts `true` / `false` in any capitalisation, with surrounding whitespace ignored, so the
    `TRUE` / `FALSE` a spreadsheet export writes is read as the same boolean as the `true` / `false`
    a hand-written CSV or config file carries. Anything else - including `yes` / `no` and `1` / `0` -
    is rejected, which is what lets `auto_cast` fall through to its numeric casters

    Args:
        s (Any): The value to be converted

    Raises:
        ValueError: If the input is not a valid boolean representation

    Returns:
        bool: True for 'true', False for 'false' (either in any capitalisation)
    """
    if isinstance(s, str):
        normalized = s.strip().lower()

        if normalized in _TRUTHY_VALUES:
            return True
        if normalized in _FALSY_VALUES:
            return False

    raise ValueError(f"Invalid boolean value: {s}")


def noneify(s: Any) -> None:
    """
    Converts a string representation of 'None' to a NoneType value

    Unlike `boolify`, the comparison is exact: `None` and `null` are erased, `NULL` and `none` are
    not. That asymmetry is deliberate for now and parked as discussion-backlog #193

    Args:
        s (Any): The value to be converted

    Raises:
        ValueError: If the input is not a valid representation of None

    Returns:
        None: If the input is 'None' or 'null'
    """
    if s in _NONE_VALUES:
        return None

    raise ValueError(f"Invalid None value: {s}")


def auto_cast(val: Any) -> float | int | str | bool | None:
    """
    Attempts to automatically convert a value into its most appropriate data type

    Tries the following conversions in order, keeping the first that does not raise:
    - Boolean (true/false, any capitalisation)
    - Integer
    - NoneType (None/null)
    - Float
    - String (fallback)

    The string fallback is the last resort and applies to anything the four typed casters reject, so
    every input yields something. Note the consequences of the numeric casters accepting what
    Python's `int()` and `float()` accept: `'007'` becomes `7`, `'1_000'` becomes `1000`, and
    `'nan'` / `'inf'` become the corresponding floats (discussion-backlog #192 and #194)

    Args:
        val (Any): The value to be converted

    Returns:
        bool | int | None | float | str: The converted value
    """
    for caster in (boolify, int, noneify, float):
        try:
            return caster(val)
        except (ValueError, TypeError):
            pass

    return str(val)
