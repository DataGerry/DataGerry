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
Tripwire: every write of the access rules drops the request's access grants

The access engine reads a user's grants once per request (``access_engine.load_grants``); a request that changes
assignments or scope roles and decides afterwards would decide on the grants read before the change. So every function
writing them calls ``forget_grants`` too:

* anywhere in ``cmdb/``, a function calling a write of the access collections that is no generic manager write
  (``pull_type_from_roles``, ``pull_missing_types``, ``delete_assignments``)
* in the access routes, a function calling a generic write (``insert_item``, ``update_item_from_payload``,
  ``delete_item``)

The managers (which define the writes) and the migrations (no request) are left out. Read with ``ast``, so every
module is covered whether or not a test imports it
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
ACCESS_ROUTES_DIR: Path = CMDB_ROOT / 'interface' / 'rest_api' / 'routes' / 'access_routes'
EXCLUDED_DIRS: tuple[Path, ...] = (CMDB_ROOT / 'manager', CMDB_ROOT / 'database')
FORGET_CALL: str = 'forget_grants'
ACCESS_WRITES: frozenset[str] = frozenset({'pull_type_from_roles', 'pull_missing_types', 'delete_assignments'})
GENERIC_WRITES: frozenset[str] = frozenset({'insert_item', 'update_item_from_payload', 'delete_item'})

# The fewest writers each scan must find, so a moved package cannot make it pass vacuously
MIN_ACCESS_WRITERS: int = 3
MIN_GENERIC_WRITERS: int = 3


def _called_names(node: ast.AST) -> set[str]:
    """The names every call inside the node calls - a plain name or an attribute's"""
    names: set[str] = set()

    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                names.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                names.add(call.func.attr)

    return names


def _functions(path: Path) -> list[ast.FunctionDef]:
    """The module's top-level functions and the methods of its top-level classes - a nested function counts as its
    enclosing one's"""
    tree: ast.Module = ast.parse(path.read_text(encoding='utf-8'))
    found: list[ast.FunctionDef] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found.append(node)
        elif isinstance(node, ast.ClassDef):
            found.extend(item for item in node.body if isinstance(item, ast.FunctionDef))

    return found


def _writers(paths: list[Path], writes: frozenset[str]) -> dict[str, set[str]]:
    """Per function (``module::name``) that calls one of the writes, every name it calls"""
    writers: dict[str, set[str]] = {}

    for path in paths:
        for function in _functions(path):
            called: set[str] = _called_names(function)

            if called & writes:
                writers[f'{path.relative_to(CMDB_ROOT)}::{function.name}'] = called

    return writers


def _scanned(root: Path) -> list[Path]:
    """The modules under the root, the excluded folders left out"""
    return [path for path in sorted(root.rglob('*.py'))
            if not any(path.is_relative_to(excluded) for excluded in EXCLUDED_DIRS)]


ACCESS_WRITERS: dict[str, set[str]] = _writers(_scanned(CMDB_ROOT), ACCESS_WRITES)
GENERIC_WRITERS: dict[str, set[str]] = _writers(_scanned(ACCESS_ROUTES_DIR), GENERIC_WRITES)


@pytest.mark.parametrize('writer', sorted(ACCESS_WRITERS), ids=sorted(ACCESS_WRITERS))
def test_an_access_collection_writer_forgets_the_grants(writer: str) -> None:
    """Group delete, Type delete, configuration reset"""
    assert FORGET_CALL in ACCESS_WRITERS[writer]


@pytest.mark.parametrize('writer', sorted(GENERIC_WRITERS), ids=sorted(GENERIC_WRITERS))
def test_an_access_route_writer_forgets_the_grants(writer: str) -> None:
    """The create, update and delete helpers of the access routes"""
    assert FORGET_CALL in GENERIC_WRITERS[writer]


def test_the_scans_find_the_writers() -> None:
    """A moved package cannot make the census pass on nothing"""
    assert len(ACCESS_WRITERS) >= MIN_ACCESS_WRITERS
    assert len(GENERIC_WRITERS) >= MIN_GENERIC_WRITERS
