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
Imports every module of a package as the FIRST module of that package a process loads

A two-way dependency between two packages makes `import cmdb.x` depend on what the process imported
before it: whichever half is entered first re-enters itself half-initialised. The app, gunicorn and the
test suite all enter through the same half, so such a cycle stays invisible until a script or a
PyInstaller hidden import enters through the other one. `tests/unit/test_standalone_module_imports.py`
pins the modules that have broken before; this scan covers all of them. It takes about a minute, which is
why it runs as its own CI step instead of inside the test suite:

    python -m tests.utils.first_import_scan

Exits 0 when every module imports, 1 otherwise, listing each failure
"""
import importlib
import sys
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCANNED_PACKAGE: str = 'cmdb'
PACKAGE_INIT: str = '__init__.py'
# The longest error text kept per failure; the cycle's module names come first in the message
ERROR_TEXT_LIMIT: int = 200


def discover_modules(root: Path, package: str) -> list[str]:
    """
    Lists every importable module of a package, in a stable order

    Args:
        root (Path): The directory the package lives in
        package (str): The top-level package name

    Returns:
        list[str]: The dotted module names; a package is named by its `__init__.py`
    """
    modules: set[str] = set()

    for path in (root / package).rglob('*.py'):
        parts = path.relative_to(root).with_suffix('').parts

        modules.add('.'.join(parts[:-1] if path.name == PACKAGE_INIT else parts))

    return sorted(modules)


def purge_package(package: str) -> None:
    """
    Removes a package and all of its submodules from `sys.modules`

    Args:
        package (str): The top-level package name
    """
    for name in [name for name in sys.modules if name == package or name.startswith(f'{package}.')]:
        del sys.modules[name]


def scan(modules: list[str], package: str) -> list[str]:
    """
    Imports each module with the package purged first, so each one is the first of its package

    Args:
        modules (list[str]): The dotted module names to import
        package (str): The top-level package purged before each import

    Returns:
        list[str]: One `module: ErrorType: message` line per module that failed to import
    """
    failures: list[str] = []

    for module in modules:
        purge_package(package)

        try:
            importlib.import_module(module)
        except Exception as err:  # pylint: disable=broad-exception-caught
            failures.append(f'{module}: {type(err).__name__}: {str(err)[:ERROR_TEXT_LIMIT]}')

    purge_package(package)

    return failures


def main() -> int:
    """
    Scans every `cmdb` module and reports the result

    Returns:
        int: The process exit code - 0 when every module imported, 1 otherwise
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    modules = discover_modules(REPO_ROOT, SCANNED_PACKAGE)
    failures = scan(modules, SCANNED_PACKAGE)

    print(f'{len(modules)} modules imported first, {len(failures)} failed')

    for failure in failures:
        print(failure)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
