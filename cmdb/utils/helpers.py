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
    * `process_bar` — stdout progress bar driven by the database updater
"""
import re
import sys
import importlib
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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
