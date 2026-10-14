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
Tripwire: the manager layer's catch-all arms only ever shrink

A catch-all is any arm that catches a programming error: ``except Exception``, ``except BaseException``, a bare
``except:``, and either name inside a tuple (``except (BaseManagerGetError, Exception)``).

A manager that wraps everything its call raises turns a programming error into its domain error - "Failed to
retrieve ... from the database", the route's 400 - instead of letting it reach the route's generic tail and its
500. A manager catches the errors its calls raise: the ``BaseManager*Error`` of the call, the model's declared
(de)serialisation errors, the typed errors of its own helpers.

``GenericManager``, ``ObjectsManager``, ``TypesManager``, ``LocationsManager`` and ``UsersManager`` are narrowed
(``NARROWED_FILES``); the rest of ``cmdb/manager/`` is the baseline
(``manager_catch_all_baseline.json``: ``<file>::<Class.function>`` -> how many arms). A NEW arm fails here. A
narrowed one fails too, until it is dropped from the baseline - so the file stays the true remainder.

Read with ``ast``, so every module is covered whether or not a test imports it.
"""
import ast
import json
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_ROOT: Path = Path(__file__).resolve().parents[3] / 'cmdb' / 'manager'
BASELINE_PATH: Path = Path(__file__).resolve().parent / 'manager_catch_all_baseline.json'

# The handler types that catch everything a programming error raises - a bare ``except:`` counts too
CATCH_ALL_NAMES: frozenset[str] = frozenset({'Exception', 'BaseException'})
MODULE_LEVEL: str = '<module>'

# The managers narrowed so far: they may never appear in the census again
NARROWED_FILES: tuple[str, ...] = (
    'generic_manager.py',
    'objects_manager.py',
    'types_manager.py',
    'locations_manager.py',
    'users_manager.py',
)

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 60


def _owner(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """
    The ``Class.function`` (or ``function``, or ``<module>``) an except arm sits in

    Args:
        node (ast.AST): The except handler
        parents (dict[ast.AST, ast.AST]): Each node's parent in its module

    Returns:
        str: The owner's qualified name
    """
    function: str | None = None
    current: ast.AST = node

    while current in parents:
        current = parents[current]

        if function is None and isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = current.name
        elif function is not None and isinstance(current, ast.ClassDef):
            return f'{current.name}.{function}'

    return function or MODULE_LEVEL


def _is_catch_all(handler: ast.ExceptHandler) -> bool:
    """
    Whether an except arm catches every exception - bare, ``Exception``/``BaseException``, or either inside a tuple

    Args:
        handler (ast.ExceptHandler): The except arm

    Returns:
        bool: True when the arm catches a programming error as well
    """
    if handler.type is None:
        return True

    names: list[ast.expr] = list(handler.type.elts) if isinstance(handler.type, ast.Tuple) else [handler.type]

    return any(isinstance(name, ast.Name) and name.id in CATCH_ALL_NAMES for name in names)


def catch_all_census(source: str) -> dict[str, int]:
    """
    The module's catch-all arms, counted per owner

    Args:
        source (str): A module's source

    Returns:
        dict[str, int]: owner -> how many arms it has
    """
    tree: ast.Module = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    census: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_catch_all(node):
            owner: str = _owner(node, parents)
            census[owner] = census.get(owner, 0) + 1

    return census


def _tree_census() -> tuple[dict[str, int], int]:
    """Every arm of cmdb/manager/, keyed ``<file>::<owner>``, and how many modules were scanned"""
    census: dict[str, int] = {}
    modules: list[Path] = sorted(MANAGER_ROOT.rglob('*.py'))

    for path in modules:
        for owner, count in catch_all_census(path.read_text(encoding='utf-8')).items():
            census[f'{path.relative_to(MANAGER_ROOT).as_posix()}::{owner}'] = count

    return census, len(modules)


def test_the_census_finds_arms_by_their_owner() -> None:
    """The scan itself: a method's arm, a nested function's, a module-level one, and a typed arm ignored"""
    source = '''
def helper():
    try:
        pass
    except Exception:
        pass

class Manager:
    def method(self):
        try:
            pass
        except Exception:
            pass
        try:
            pass
        except Exception as err:
            raise
        try:
            pass
        except ValueError:
            pass

try:
    pass
except Exception:
    pass
'''
    assert catch_all_census(source) == {'helper': 1, 'Manager.method': 2, MODULE_LEVEL: 1}


def test_the_census_finds_every_spelling_of_a_catch_all() -> None:
    """A typed error next to Exception in a tuple, BaseException, and a bare except all catch a bug"""
    source = '''
class Manager:
    def method(self):
        try:
            pass
        except (KeyError, Exception):
            pass
        try:
            pass
        except BaseException:
            pass
        try:
            pass
        except:
            pass
        try:
            pass
        except (KeyError, ValueError):
            pass
'''
    assert catch_all_census(source) == {'Manager.method': 3}


def test_the_manager_layer_holds_no_new_catch_all() -> None:
    """Every arm is in the baseline, and the baseline holds no arm that is gone"""
    census, scanned = _tree_census()
    baseline: dict[str, int] = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))

    assert scanned >= MIN_SCANNED_MODULES

    new: dict[str, int] = {key: count for key, count in census.items() if count > baseline.get(key, 0)}
    gone: dict[str, int] = {key: count for key, count in baseline.items() if census.get(key, 0) < count}

    assert not new, f'new `except Exception` arm(s) - catch the errors the call raises instead: {new}'
    assert not gone, f'narrowed - drop these from {BASELINE_PATH.name} (or lower their count): {gone}'


def test_the_narrowed_managers_stay_narrowed() -> None:
    """Neither the code nor the baseline may bring a catch-all back to a narrowed manager"""
    census, _ = _tree_census()
    baseline: dict[str, int] = json.loads(BASELINE_PATH.read_text(encoding='utf-8'))

    for key in list(census) + list(baseline):
        assert key.split('::', 1)[0] not in NARROWED_FILES, key
