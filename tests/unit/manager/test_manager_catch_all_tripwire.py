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
Tripwire: the manager layer holds no catch-all arm

A catch-all is any arm that catches a programming error: ``except Exception``, ``except BaseException``, a bare
``except:``, and either name inside a tuple (``except (BaseManagerGetError, Exception)``).

A manager that wraps everything its call raises turns a programming error into its domain error - "Failed to
retrieve ... from the database", the route's 400 - instead of letting it reach the route's generic tail and its
500. A manager catches the errors its calls raise: the ``BaseManager*Error`` of the call, the model's declared
(de)serialisation errors, the typed errors of its own helpers.

Every manager is narrowed, so the census of ``cmdb/manager/`` must be empty: any arm fails here, named
``<file>::<Class.function>``.

Read with ``ast``, so every module is covered whether or not a test imports it.
"""
import ast
from pathlib import Path

from tests.utils.catch_all_scan import MODULE_LEVEL, is_catch_all, owner_of, parent_map
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_ROOT: Path = Path(__file__).resolve().parents[3] / 'cmdb' / 'manager'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 60


def catch_all_census(source: str) -> dict[str, int]:
    """
    The module's catch-all arms, counted per owner

    Args:
        source (str): A module's source

    Returns:
        dict[str, int]: owner -> how many arms it has
    """
    tree: ast.Module = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = parent_map(tree)
    census: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and is_catch_all(node):
            owner: str = owner_of(node, parents)
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


def test_the_manager_layer_holds_no_catch_all() -> None:
    """No manager module catches a programming error"""
    census, scanned = _tree_census()

    assert scanned >= MIN_SCANNED_MODULES
    assert not census, f'`except Exception` arm(s) - catch the errors the call raises instead: {census}'
