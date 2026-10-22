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
Tripwire: no class of the cmdb/ tree defines more public methods than pylint's limit

CI's lint gate is a score, so pylint's ``too-many-public-methods`` (R0904) only lowers it and never fails a build - a
class grows past ``max-public-methods`` unnoticed. This scan makes crossing the limit a failing test. The limit is
read from .pylintrc, and the methods are counted the way pylint counts them: every function a class defines in its
own body whose name does not start with an underscore - inherited ones are not counted, which is why a mixin is the
way to split a class.

A class already over the limit would be listed in ``KNOWN_OVER_LIMIT`` with its count when listed; it may shrink
but not grow, and once it is back under the limit the entry must go - a stale entry fails too. The list is empty

Read with ``ast``, so every module is covered whether or not a test imports it
"""
import ast
from pathlib import Path

import pytest

from tests.utils.pylint_limits import REPO_ROOT, pylint_limit
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = REPO_ROOT / 'cmdb'
PUBLIC_METHODS_OPTION: str = 'max-public-methods'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_CLASSES: int = 1000

# Classes over the limit that are still to be split, as '<path relative to cmdb/>::<class>', with their count
KNOWN_OVER_LIMIT: dict[str, int] = {}


def public_method_counts(source: str) -> dict[str, int]:
    """
    Counts the public methods every class of a module defines in its own body

    Args:
        source (str): The module's source

    Returns:
        dict[str, int]: The count per class, by the class's name - a nested class by its dotted path
    """
    counts: dict[str, int] = {}

    def _visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                name: str = f'{prefix}{child.name}'
                counts[name] = sum(
                    1 for item in child.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith('_')
                )
                _visit(child, f'{name}.')
            else:
                _visit(child, prefix)

    _visit(ast.parse(source), '')

    return counts


def tree_counts(root: Path) -> dict[str, int]:
    """
    Counts the public methods of every class under a tree

    Args:
        root (Path): The tree to scan

    Returns:
        dict[str, int]: The count per class, as '<path relative to root>::<class>'
    """
    return {
        f'{path.relative_to(root).as_posix()}::{name}': count
        for path in sorted(root.rglob('*.py'))
        for name, count in public_method_counts(path.read_text(encoding='utf-8')).items()
    }


@pytest.fixture(name='counts', scope='module')
def fixture_counts() -> dict[str, int]:
    """The counts of the cmdb/ tree, scanned once"""
    return tree_counts(CMDB_ROOT)


def test_no_class_is_newly_over_the_limit(counts: dict[str, int]) -> None:
    """A class not listed as a known exception stays within max-public-methods"""
    limit: int = pylint_limit(PUBLIC_METHODS_OPTION)

    assert {key: count for key, count in counts.items() if count > limit and key not in KNOWN_OVER_LIMIT} == {}


@pytest.mark.parametrize('key, listed_count', KNOWN_OVER_LIMIT.items())
def test_a_known_exception_does_not_grow(counts: dict[str, int], key: str, listed_count: int) -> None:
    """It may only shrink until it is split"""
    assert counts[key] <= listed_count


@pytest.mark.parametrize('key', KNOWN_OVER_LIMIT)
def test_a_known_exception_is_still_over_the_limit(counts: dict[str, int], key: str) -> None:
    """One back under the limit is taken off the list, so the list never hides a class that grows again"""
    assert counts[key] > pylint_limit(PUBLIC_METHODS_OPTION)


def test_the_scan_covers_the_tree(counts: dict[str, int]) -> None:
    """A moved or renamed package cannot make the scan pass on nothing"""
    assert len(counts) >= MIN_SCANNED_CLASSES


def test_the_base_manager_is_counted_without_what_it_inherits(counts: dict[str, int]) -> None:
    """The class this tripwire was written for: its mixins' methods are theirs, not its own"""
    assert counts['manager/base_manager.py::BaseManager'] <= pylint_limit(PUBLIC_METHODS_OPTION)
    assert counts['manager/other_collection_access_mixin.py::OtherCollectionAccessMixin'] > 0


class TestPublicMethodCounts:
    """The counter itself, on sources of its own"""

    def test_only_public_functions_of_the_body_count(self) -> None:
        """Private and dunder methods do not count; static, class, property and async ones do"""
        source = (
            'class Sample:\n'
            '    def __init__(self): pass\n'
            '    def _hidden(self): pass\n'
            '    def shown(self): pass\n'
            '    @staticmethod\n'
            '    def static(): pass\n'
            '    @property\n'
            '    def value(self): return 1\n'
            '    async def later(self): pass\n'
            '    LIMIT = 3\n'
        )

        assert public_method_counts(source) == {'Sample': 4}

    def test_inherited_methods_are_not_counted(self) -> None:
        """Like pylint: a subclass counts what it defines"""
        source = (
            'class Base:\n'
            '    def one(self): pass\n'
            '    def two(self): pass\n'
            'class Child(Base):\n'
            '    def three(self): pass\n'
        )

        assert public_method_counts(source) == {'Base': 2, 'Child': 1}

    def test_a_nested_class_counts_on_its_own(self) -> None:
        """Its methods are not its owner's; a class inside a function is still found"""
        source = (
            'class Outer:\n'
            '    def one(self): pass\n'
            '    class Inner:\n'
            '        def two(self): pass\n'
            '        def three(self): pass\n'
            'if True:\n'
            '    class Guarded:\n'
            '        def four(self): pass\n'
            'def factory():\n'
            '    class Local:\n'
            '        def five(self): pass\n'
        )

        assert public_method_counts(source) == {'Outer': 1, 'Outer.Inner': 2, 'Guarded': 1, 'Local': 1}

    def test_the_tree_keys_carry_the_path(self, tmp_path: Path) -> None:
        """'<path>::<class>', so two classes of the same name never collide"""
        (tmp_path / 'package').mkdir()
        (tmp_path / 'package' / 'a.py').write_text('class Same:\n    def one(self): pass\n', encoding='utf-8')
        (tmp_path / 'b.py').write_text('class Same:\n    pass\n', encoding='utf-8')

        assert tree_counts(tmp_path) == {'b.py::Same': 0, 'package/a.py::Same': 1}
