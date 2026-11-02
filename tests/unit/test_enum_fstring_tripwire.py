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
Tripwire: an enum member put into an f-string is written as its ``.value``

A plain ``Enum`` and a ``(str, Enum)`` - ``BaseStrEnum`` and everything built on it - format as ``Class.MEMBER``,
not as their value: ``f"'{IpamUnassignKey.IPS}' must be ..."`` answered a client *"'IpamUnassignKey.IPS' must
be ..."* instead of naming the field it sends, ``'ips'``. ``!s`` and a format spec do the same. ``IntEnum`` and
``StrEnum`` format as their value, and so does a class that defines its own ``__str__`` / ``__format__``; those
are left alone, like ``!r`` / ``!a``, which ask for the representation on purpose.

Read with ``ast``, so every module is covered whether or not a test imports it. The enum classes are found the
same way - every class in ``cmdb/`` whose bases lead to ``Enum``, through any chain of the tree's own classes.
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
PACKAGE_INIT: str = '__init__.py'

# The bases that make a class an enum, and those among them that already format as their value
ENUM_BASES: frozenset[str] = frozenset({'Enum', 'IntEnum', 'StrEnum', 'Flag', 'IntFlag'})
VALUE_FORMATTING_BASES: frozenset[str] = frozenset({'IntEnum', 'StrEnum', 'IntFlag'})
# A class defining one of these decides its own text
FORMATTING_METHODS: frozenset[str] = frozenset({'__str__', '__format__'})
# !r and !a ask for the representation on purpose
REPRESENTATION_CONVERSIONS: frozenset[int] = frozenset({ord('r'), ord('a')})
# How many imports deep a name is followed - re-exports through package __init__ files included
MAX_IMPORT_DEPTH: int = 10

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000
MIN_ENUM_CLASSES: int = 300
MIN_VALUE_INTERPOLATIONS: int = 150


def _base_name(base: ast.expr) -> str | None:
    """The name a base is written as - `Enum` and `enum.Enum` alike"""
    if isinstance(base, ast.Name):
        return base.id

    if isinstance(base, ast.Attribute):
        return base.attr

    return None


class EnumIndex:
    """
    Which names, in which module, are enum classes that format as `Class.MEMBER`

    A name is resolved the way Python resolves it: a class defined in the module, or the name an import brings in -
    followed into the imported module of the scanned tree, through package re-exports. A class is such an enum when
    its bases lead to `Enum` and no class on the way is `IntEnum` / `StrEnum` / `IntFlag` or defines `__str__` /
    `__format__`. Two classes of the same name in different modules are told apart.
    """

    def __init__(self, root: Path, sources: dict[Path, str]) -> None:
        """
        Args:
            root (Path): The folder the package paths start from (the one holding the top-level package)
            sources (dict[Path, str]): Every module of the tree by its path
        """
        self.root: Path = root
        self.trees: dict[Path, ast.Module] = {path: ast.parse(source) for path, source in sources.items()}
        # Answers already worked out - every module asks about the same few enums
        self._resolved: dict[tuple[str, Path], tuple[Path, ast.ClassDef] | str | None] = {}
        self._formatting: dict[tuple[Path, str], tuple[bool, bool]] = {}

    def _module_path(self, module: str | None, level: int, importer: Path) -> Path | None:
        """The scanned file an import names - None for a module outside the tree"""
        if level:
            package: Path = importer.parent

            for _ in range(level - 1):
                package = package.parent

            base: Path = package.joinpath(*module.split('.')) if module else package
        else:
            if not module:
                return None

            base = self.root.joinpath(*module.split('.'))

        for candidate in (base.with_suffix('.py'), base / PACKAGE_INIT):
            if candidate in self.trees:
                return candidate

        return None

    def resolve(self, name: str, path: Path, depth: int = 0) -> tuple[Path, ast.ClassDef] | str | None:
        """
        What a name means in a module

        Returns:
            tuple[Path, ast.ClassDef] | str | None: The class of the tree it names, the name itself when it comes
                from outside the tree (``Enum``), or None when the module does not bind it
        """
        if (name, path) not in self._resolved:
            self._resolved[(name, path)] = self._resolve(name, path, depth)

        return self._resolved[(name, path)]

    def _resolve(self, name: str, path: Path, depth: int) -> tuple[Path, ast.ClassDef] | str | None:
        """`resolve`, uncached"""
        tree: ast.Module = self.trees[path]

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                return path, node

        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue

            for alias in node.names:
                if (alias.asname or alias.name) != name:
                    continue

                target: Path | None = self._module_path(node.module, node.level, path)

                if target is None:
                    return alias.name

                if depth >= MAX_IMPORT_DEPTH:
                    return None

                return self.resolve(alias.name, target, depth + 1)

        return None

    def formatting(self, path: Path, class_name: str) -> tuple[bool, bool]:
        """(is an enum, formats as its value) for a class of the tree"""
        if (path, class_name) not in self._formatting:
            self._formatting[(path, class_name)] = self._formatting_of(path, class_name)

        return self._formatting[(path, class_name)]

    def _formatting_of(self, path: Path, class_name: str) -> tuple[bool, bool]:
        """`formatting`, uncached"""
        resolved = self.resolve(class_name, path)

        if not isinstance(resolved, tuple):
            return False, False

        class_path, node = resolved
        is_enum: bool = False
        by_value: bool = any(isinstance(item, ast.FunctionDef) and item.name in FORMATTING_METHODS
                             for item in node.body)

        for base in node.bases:
            base_name: str | None = _base_name(base)

            if base_name is None:
                continue

            if isinstance(base, ast.Name):
                base_resolved = self.resolve(base_name, class_path)
            else:
                base_resolved = base_name

            if isinstance(base_resolved, tuple):
                base_is_enum, base_by_value = self.formatting(base_resolved[0], base_resolved[1].name)
            elif base_resolved in ENUM_BASES:
                base_is_enum, base_by_value = True, base_resolved in VALUE_FORMATTING_BASES
            else:
                base_is_enum, base_by_value = False, False

            is_enum = is_enum or base_is_enum
            by_value = by_value or (base_is_enum and base_by_value)

        return is_enum, by_value

    def formats_by_name(self, name: str, path: Path) -> bool:
        """Whether a name used in a module is an enum class that formats as `Class.MEMBER`"""
        resolved = self.resolve(name, path)

        return isinstance(resolved, tuple) and self.formatting(resolved[0], resolved[1].name) == (True, False)

    def enum_classes(self) -> list[tuple[Path, str]]:
        """Every class of the tree that formats as `Class.MEMBER`"""
        return [(path, node.name) for path, tree in self.trees.items() for node in tree.body
                if isinstance(node, ast.ClassDef) and self.formatting(path, node.name) == (True, False)]

    def find_interpolations(self, path: Path) -> list[tuple[int, str]]:
        """
        The f-string interpolations of an enum member that print `Class.MEMBER` in one module

        Returns:
            list[tuple[int, str]]: (line, `Class.MEMBER`) of each, `!s` and format specs included
        """
        found: list[tuple[int, str]] = []

        for node in ast.walk(self.trees[path]):
            if not isinstance(node, ast.FormattedValue) or node.conversion in REPRESENTATION_CONVERSIONS:
                continue

            value: ast.expr = node.value

            if (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                    and self.formats_by_name(value.value.id, path)):
                found.append((node.lineno, f'{value.value.id}.{value.attr}'))

        return found

    def count_value_interpolations(self, path: Path) -> int:
        """How many f-string interpolations of one module write an enum member as `.value` - the rule's spelling"""
        count: int = 0

        for node in ast.walk(self.trees[path]):
            if not (isinstance(node, ast.FormattedValue) and isinstance(node.value, ast.Attribute)):
                continue

            member: ast.expr = node.value.value

            if (node.value.attr == 'value' and isinstance(member, ast.Attribute)
                    and isinstance(member.value, ast.Name) and self.formats_by_name(member.value.id, path)):
                count += 1

        return count


MODULES: list[Path] = sorted(CMDB_ROOT.rglob('*.py'))
INDEX: EnumIndex = EnumIndex(CMDB_ROOT.parent, {path: path.read_text(encoding='utf-8') for path in MODULES})

ENUMS_MODULE: str = (
    "from enum import Enum, IntEnum, StrEnum\n"
    "class Base(str, Enum):\n    pass\n"
    "class Key(Base):\n    A = 'a'\n"
    "class Plain(Enum):\n    A = 'a'\n"
    "class Number(IntEnum):\n    A = 1\n"
    "class Text(StrEnum):\n    A = 'a'\n"
    "class Own(str, Enum):\n    A = 'a'\n    def __str__(self):\n        return self.value\n"
    "class Right:\n    A = 'a'\n"
)
IMPORTS: str = "from pkg.enums import Key, Plain, Number, Text, Own\nfrom pkg.other import Right\n"


@pytest.fixture(name='snippet_index')
def fixture_snippet_index(tmp_path: Path):
    """
    A tiny tree: `pkg/enums.py` with every kind of class, `pkg/other.py` with a plain class named like an enum
    elsewhere, `pkg/__init__.py` re-exporting an enum; returns a scanner of one extra module of `pkg`
    """
    files: dict[str, str] = {
        'pkg/__init__.py': "from .enums import Key as ReKey\n",
        'pkg/enums.py': ENUMS_MODULE,
        'pkg/other.py': "class Right:\n    A = 'a'\n",
    }

    def _scan(snippet: str) -> list[tuple[int, str]]:
        modules: dict[str, str] = {**files, 'pkg/use.py': snippet}
        sources: dict[Path, str] = {tmp_path / name: source for name, source in modules.items()}
        return EnumIndex(tmp_path, sources).find_interpolations(tmp_path / 'pkg/use.py')

    return _scan


class TestTheDetector:
    """The scan's own rule, pinned on snippets - a detector that finds nothing passes every module"""

    @pytest.mark.parametrize('snippet, member', [
        (IMPORTS + "x = f'{Key.A}'\n", 'Key.A'),
        (IMPORTS + "x = f'field {Plain.A} is missing'\n", 'Plain.A'),
        (IMPORTS + "x = f'{Key.A!s}'\n", 'Key.A'),
        (IMPORTS + "x = f'{Key.A:>10}'\n", 'Key.A'),
        ("from pkg import ReKey\nx = f'{ReKey.A}'\n", 'ReKey.A'),
        ("from .enums import Key as K\nx = f'{K.A}'\n", 'K.A'),
    ], ids=['bare', 'in-text', 'str-conversion', 'format-spec', 're-exported', 'relative-alias'])
    def test_a_member_formatted_by_name_is_found(self, snippet_index, snippet: str, member: str) -> None:
        """Every spelling that prints `Class.MEMBER`, however the class was imported"""
        assert [found for _, found in snippet_index(snippet)] == [member]

    @pytest.mark.parametrize('snippet', [
        IMPORTS + "x = f'{Key.A.value}'\n",
        IMPORTS + "x = f'{Key.A!r}'\n",
        IMPORTS + "x = f'{Number.A}'\n",
        IMPORTS + "x = f'{Text.A}'\n",
        IMPORTS + "x = f'{Own.A}'\n",
        IMPORTS + "x = f'{Right.A}'\n",
        IMPORTS + "x = '{Key.A}'\n",
        "x = f'{Key.A}'\n",
    ], ids=['value', 'repr', 'int-enum', 'str-enum', 'own-str', 'plain-class', 'not-an-f-string', 'unbound-name'])
    def test_what_the_rule_leaves_alone(self, snippet_index, snippet: str) -> None:
        """The value, the representation, whatever formats as its value already, and names that are no enum"""
        assert not snippet_index(snippet)


def test_the_scan_covers_the_tree() -> None:
    """Guards the census itself: the tree is there, holds enums and writes their values into f-strings"""
    assert len(MODULES) > MIN_SCANNED_MODULES
    assert len(INDEX.enum_classes()) > MIN_ENUM_CLASSES
    assert sum(INDEX.count_value_interpolations(path) for path in MODULES) > MIN_VALUE_INTERPOLATIONS


def test_no_enum_member_is_formatted_by_its_name() -> None:
    """Write `{Class.MEMBER.value}` - the f-string prints `Class.MEMBER` otherwise"""
    found: list[str] = [
        f'{path.relative_to(CMDB_ROOT)}:{line}: {{{member}}}'
        for path in MODULES
        for line, member in INDEX.find_interpolations(path)
    ]

    assert not found, '\n'.join(found)
