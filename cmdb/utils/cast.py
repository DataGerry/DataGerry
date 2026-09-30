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

**The rule is: recognise only what is unambiguous, and leave everything else alone.** `int()` and
`float()` themselves accept far more than a data file means by "a number", and every one of those
acceptances destroys a value that cannot be recovered afterwards:

| was | became | now |
|---|---|---|
| `'007'`, `'0042'` | `7`, `42` — an asset tag or serial silently renumbered | stays a string |
| `'+49123'` | `49123` — a phone number with its country code removed | stays a string |
| `'1_000'` | `1000` — Python's numeric underscore is not a CSV convention | stays a string |
| `'٧'`, `'０７'` | `7` — `int()` accepts every Unicode decimal digit | stays a string |
| `'nan'`, `'inf'` | non-finite doubles BSON stores and no query ever matches | stays a string |
| `'null'`, `'None'` | `None` — a value erased, and only in those two spellings | stays a string |
| `3.5` (a real float) | `3` — `int()` claimed it and truncated | returned unchanged |
| `None`, `['a']` | `'None'`, `"['a']"` | returned unchanged |

**Nothing was lost by tightening it, because a typed layer already runs downstream.** The CSV
importer coerces every value against its target field's declared `type`
(`object_import_validator._coerce_scalar_value`: NUMBER, CHECKBOX, DATE and the reference types).
The guess here ran *first* and destroyed the input before the layer that actually knows the type
could look at it — `'007'` reached a TEXT field as `'7'`, having been an `int` in between. Now a
NUMBER field still stores `7` and a TEXT field keeps `'007'`, which is what each of them was asked
for.

What is still cast, and why it is safe: `'27017'` is a number in any reading, `'true'` is a boolean
in any reading. Those two are what the config file needs and what a spreadsheet's numeric columns
mean, and neither has a second interpretation to lose
"""
import re
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# Accepted spellings of a boolean, compared case-insensitively against the stripped value
_TRUTHY_VALUES: frozenset[str] = frozenset({'true'})
_FALSY_VALUES: frozenset[str] = frozenset({'false'})

#: The digits of a number with no leading zero: a single `0`, or a non-zero digit and the rest.
#: `007` is an identifier that happens to be spelled with digits, and stays text
_DIGITS: str = r'(?:0|[1-9][0-9]*)'

#: An integer. ASCII digits only, no underscore separators, and **no leading `+`** - a leading plus
#: belongs to international phone numbers far more often than to a number a data file means, and
#: casting `+49123` to `49123` would silently rewrite one. A leading `-` is kept: a negative number
#: is a number
_INTEGER_PATTERN: re.Pattern[str] = re.compile(rf'^-?{_DIGITS}$')

#: A decimal number, ASCII digits only, same leading-zero and leading-plus rules as the integer.
#: A digit is required on at least one side of the point and an exponent must carry its digits, so
#: `nan`, `inf`, `Infinity`, `1_0.5` and `1e` are all rejected - spellings Python's `float()`
#: accepts and a data file does not mean
_FLOAT_PATTERN: re.Pattern[str] = re.compile(
    rf'^-?(?:{_DIGITS}\.[0-9]*|\.[0-9]+|{_DIGITS})(?:[eE][+-]?[0-9]+)?$'
)

# -------------------------------------------------------------------------------------------------------------------- #

def boolify(s: Any) -> bool:
    """
    Converts a string representation of a boolean to its corresponding boolean value

    Accepts `true` / `false` in any capitalisation, with surrounding whitespace ignored, so the
    `TRUE` / `FALSE` a spreadsheet export writes is read as the same boolean as the `true` / `false`
    a hand-written CSV or config file carries. Anything else - including `yes` / `no` and `1` / `0` -
    is rejected, which is what lets `auto_cast` fall through to its numeric caster

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


def numberify(s: Any) -> int | float:
    """
    Converts a string that unambiguously spells a number into an `int` or a `float`

    Strict where `int()` and `float()` are permissive, because every spelling those two accept and a
    data file does not mean is a value destroyed without recourse. Rejected, and therefore kept as
    text: a leading zero (`007` is an identifier), a leading `+` (`+49123` is a phone number), an
    underscore separator (`1_000` is Python syntax), a non-ASCII digit (`٧`, `０７`), and `nan` /
    `inf` / `Infinity` in any capitalisation

    Surrounding whitespace is ignored, the same rule `boolify` applies - see the module docstring on
    why the casters share one normalisation

    Args:
        s (Any): The value to be converted

    Raises:
        ValueError: If the input is not a string spelling a number under the rules above

    Returns:
        int | float: The number; an `int` when the value carries no fraction or exponent
    """
    if not isinstance(s, str):
        raise ValueError(f"Invalid number value: {s}")

    normalized = s.strip()

    if _INTEGER_PATTERN.match(normalized):
        return int(normalized)

    if _FLOAT_PATTERN.match(normalized):
        return float(normalized)

    raise ValueError(f"Invalid number value: {s}")


def auto_cast(val: Any) -> Any:
    """
    Converts an untyped string into the type it unambiguously spells, and leaves anything else alone

    Tries the two typed casters in order and keeps the first that does not raise:
    - Boolean (`true` / `false`, any capitalisation)
    - Number (`int` or `float`, under the strict rules in `numberify`)

    A string no caster claims is returned **as itself**, not as a copy or a reconstruction - so no
    value can be altered by passing through here. **A non-string is returned unchanged**: the
    callers hand over text, and a value that already has a type has nothing to gain from a caster
    that can only guess. That is deliberate rather than incidental - `int()` claims a real `float`
    and truncates it (`3.5` comes back as `3`), and `str()` turns a real `None` into
    the text `'None'`

    Note what is *not* here any more: an untyped source has no way to spell "absent". `'null'` and
    `'None'` are now the text they are, and a genuinely empty CSV cell is turned into `None` by the
    importer (`CsvObjectImporter._blank_to_none`), which is the layer that knows an empty cell is
    what the user meant

    Args:
        val (Any): The value to be converted

    Returns:
        Any: A `bool` or a number for a string that spells one, otherwise the value unchanged
    """
    if not isinstance(val, str):
        return val

    for caster in (boolify, numberify):
        try:
            return caster(val)
        except ValueError:
            pass

    return val
