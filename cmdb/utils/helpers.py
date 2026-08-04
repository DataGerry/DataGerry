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
Small, dependency-light utilities reused across DataGerry's runtime layers

Provides:
    * `load_class` — dynamic class loader used by the process manager (service classes),
      the database updater (per-version `updater_<date>` modules) and the exporter
      framework (per-format classes under `cmdb.framework.exporter.format.*`)
    * `str_to_bool` — lenient string/bool coercer used to normalise REST query params
    * `parse_import_bool` — the more permissive boolean parser the object- and type-imports apply to
      an uploaded flag, reporting an unusable value instead of raising
    * `is_non_blank_string` — the "usable name / label" predicate the type import applies to every
      name, label and icon it reads
    * `duplicate_names` — reports the values occurring more than once in a sequence, used by the
      object- and type-import validators to reject duplicate field / section identifiers
    * `random_hex_color` — random '#RRGGBB' color, used wherever a CI-Explorer color is defaulted
    * `process_bar` — stdout progress bar driven by the database updater
"""
import re
import sys
import random
import importlib
from logging import Logger, getLogger
from typing import Any, Iterable
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Accepted string spellings for a boolean import value (compared case-insensitively, stripped)
_TRUTHY_IMPORT_VALUES: frozenset[str] = frozenset({'true', 'yes', '1'})
_FALSY_IMPORT_VALUES: frozenset[str] = frozenset({'false', 'no', '0'})

# Bounds of a random '#RRGGBB' CI-Explorer color: a value in [0, MAX] rendered as zero-padded hex
_HEX_COLOR_MAX: int = 0xFFFFFF
_HEX_COLOR_WIDTH: int = 6

# -------------------------------------------------------------------------------------------------------------------- #

def load_class(classname: str) -> type:
    """
    Loads a class by fully-qualified dotted name

    Splits `classname` at the *last* dot — everything before it is treated as the import
    path, everything after as the class attribute on the imported module — then performs
    a regular `importlib.import_module` + `getattr`. This is how the codebase wires
    config-driven class references: `ProcessManager` resolves registered service classes
    this way, the database updater loads `cmdb.database.updater.versions.updater_<date>`
    modules, and the exporter framework loads per-format classes
    (`cmdb.framework.exporter.format.<ClassName>`)

    Args:
        classname (str): Fully-qualified `pkg.module.ClassName` path; must contain at
            least one dot

    Returns:
        type: The resolved class object

    Raises:
        Exception: When `classname` does not contain a dot (the split fails)
        ModuleNotFoundError: When the module portion cannot be imported
        AttributeError: When the module is imported but the named attribute is missing
    """
    pattern = re.compile(r"(.*)\.(.*)")
    match = pattern.fullmatch(classname)

    if match is None:
        raise Exception(f"Could not load class {classname}")

    module_name = match.group(1)
    class_name = match.group(2)
    loaded_module = importlib.import_module(module_name)
    loaded_class = getattr(loaded_module, class_name)

    return loaded_class


def str_to_bool(s: Any) -> bool:
    """
    Coerces a permissive string / bool value into a strict `bool`

    Accepts the literal strings `"true"` / `"false"` (case-insensitive, surrounding
    whitespace stripped) and passes through native `bool` values unchanged. Any other
    input — including ints, `None`, or unrecognised strings like `"yes"` / `"0"` — is
    rejected. Used by the REST layer to normalise query-string params that arrive as
    strings but represent boolean flags (e.g. `?active=true`)

    Args:
        s (Any): Input value; expected to be `str` or `bool`

    Returns:
        bool: `True` for `"true"` / `True`, `False` for `"false"` / `False`

    Raises:
        ValueError: When `s` is neither a recognised boolean string nor a `bool`
    """
    if isinstance(s, str):
        s = s.strip().lower()
        if s == 'true':
            return True
        if s == 'false':
            return False

    if isinstance(s, bool):
        return s

    raise ValueError("Invalid value for conversion to boolean")


def is_truthy_query_arg(value: Any, default: bool = False) -> bool:
    """
    Leniently interprets a query-string boolean flag, never raising

    Wraps `str_to_bool` for the REST query-parameter case where an absent or unrecognised value should
    fall back to a default rather than raise: `"true"` / `"True"` (and native `True`) become `True`,
    `"false"` / `False` become `False`, and anything else (missing param, `None`, `"1"`, `"yes"`, ...)
    returns `default`. Replaces the ad-hoc `value in ['True', 'true']` checks scattered across the routes.

    Args:
        value (Any): The raw query-parameter value (typically `request.args.get(...)`)
        default (bool): Value returned when `value` is missing or unrecognised. Defaults to False

    Returns:
        bool: The interpreted boolean flag
    """
    try:
        return str_to_bool(value)
    except ValueError:
        return default


def process_bar(name: str, total: int, progress: int) -> None:
    """
    Writes (or rewrites) a single-line stdout progress bar

    Uses a carriage return so successive calls overwrite the same terminal line; emits a
    newline once `progress >= total` so the next stdout write starts cleanly. The bar is
    a fixed 50 chars wide, filled in proportion to `progress / total`. The `[x/y]`
    segment shows the raw step counts (`progress` and `total`) while the bar fill and
    percentage are clamped to a maximum of 100%. Calls with `total <= 0` return without
    writing anything

    Args:
        name (str): Label printed before the bar
        total (int): Total number of steps; non-positive values are treated as a no-op
        progress (int): Steps completed so far

    Example:
        >>> process_bar('Task', 100, 45)
        Task: [######################----------------------------] 45% [45/100]
    """
    if total <= 0:
        return

    fraction = min(float(progress) / float(total), 1.0)
    status = "\r\n" if fraction >= 1.0 else ""

    bar_length = 50
    block = int(round(bar_length * fraction))

    progress_percentage = f"{fraction * 100:.0f}%"
    through_of = f"[{progress}/{total}]"
    progress_bar = f'[{ "#" * block + "-" * (bar_length - block)}] {progress_percentage} {through_of}'

    sys.stdout.write(f'\r{name}: {progress_bar}{status}')
    sys.stdout.flush()


def parse_import_bool(value: Any) -> bool | None:
    """
    Parses a boolean value as accepted by an import

    Accepts real booleans, the integers ``1``/``0``, and (case-insensitive, whitespace-tolerant)
    the strings ``true``/``yes``/``1`` and ``false``/``no``/``0``. Any other value is rejected.
    Unlike `str_to_bool`, an unusable value is reported as None instead of raising, so an import can
    collect it as a per-entry message. Shared by the object import (`active`) and the type import
    (`active`, `selectable_as_parent`)

    Args:
        value (Any): The value to parse

    Returns:
        bool | None: The parsed boolean, or None if the value is not an accepted boolean
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, int):  # bool is handled above, so this is a plain int (e.g. 1 / 0)
        if value == 1:
            return True
        if value == 0:
            return False
        return None

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in _TRUTHY_IMPORT_VALUES:
            return True
        if normalized in _FALSY_IMPORT_VALUES:
            return False

    return None


def random_hex_color() -> str:
    """
    Generates a random hex color in the form #RRGGBB

    Used wherever a CI-Explorer color has to be filled in for a CmdbType that brings none, so every
    type shows up with a distinguishable color instead of no color at all

    Returns:
        str: A random color string such as '#1A2B3C'
    """
    return f'#{random.randint(0, _HEX_COLOR_MAX):0{_HEX_COLOR_WIDTH}X}'


def is_non_blank_string(value: Any) -> bool:
    """
    Reports whether a value is a string carrying more than whitespace

    The check behind "this name / label is usable": the type import applies it to every field name,
    section name, label and icon an upload brings, where `None`, `''`, `'   '` and a stray number all
    mean the same thing - nothing to identify or display

    Args:
        value (Any): The value to test

    Returns:
        bool: True for a non-blank string, False for anything else
    """
    return isinstance(value, str) and bool(value.strip())


def coerce_whole_number(value: Any) -> int | None:
    """
    Coerces a value to a whole number, or returns None when it is not one

    The check behind every "this is a count / an index / a slot" field. Accepts an int, a float with no
    fractional part (a JSON client may send 42.0) and a string holding either (a CSV import has no other
    way to carry a number). Booleans are rejected on purpose: bool is an int subclass in Python, so
    `True` would otherwise pass as 1

    Args:
        value (Any): The value to coerce

    Returns:
        int | None: The value as an int, or None when it is not a whole number
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value) if value.is_integer() else None

    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass

        try:
            as_float = float(value.strip())
        except ValueError:
            return None

        return int(as_float) if as_float.is_integer() else None

    return None


def duplicate_names(names: Iterable[Any]) -> list:
    """
    Returns the values that occur more than once, each listed once, in first-seen order

    Shared by the import validators, which reject duplicate identifiers (object field names, type
    field / section names) and report exactly which ones collided

    Args:
        names (Iterable[Any]): The values to inspect

    Returns:
        list: The duplicated values (empty when all are unique)
    """
    seen: set = set()
    duplicates: list = []

    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)

        seen.add(name)

    return duplicates
