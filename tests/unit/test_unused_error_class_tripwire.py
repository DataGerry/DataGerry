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
Tripwire: every error class in ``cmdb/errors/`` is raised, caught or extended somewhere

An error class nothing raises still reads like a promise - a docstring names it under Raises, a caller writes an
``except`` arm for it - and it stays in place when the code that raised it is refactored away. The rule: a change that
stops raising an error deletes the class, its re-export and its error-map entry in the same change.

A class counts as used when:

* any module of ``cmdb/`` outside ``cmdb/errors/`` names it (a raise, an ``except`` arm, a declaration such as a
  model's ``INIT_FROM_DATA_ERROR``, a tuple of errors), or
* another class in ``cmdb/errors/`` extends it (a family base a caller catches), or
* an error map (``<MANAGER>_ERRORS`` in an error package's ``__init__``) holds it under a key that some manager reads
  - ``exceptions.get('<key>')`` or ``exceptions['<key>']``. A key nothing reads is itself dead, so every map key must
  be one that is read.

Read with ``ast``, so every module is covered whether or not a test imports it.
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CMDB_ROOT: Path = PROJECT_ROOT / 'cmdb'
ERRORS_ROOT: Path = CMDB_ROOT / 'errors'
PACKAGE_MODULE: str = '__init__.py'

# The attribute a manager keeps its error map under
EXCEPTION_MAP_ATTRIBUTE: str = 'exceptions'
DICT_GET: str = 'get'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_ERROR_CLASSES: int = 300
MIN_ERROR_MAPS: int = 30
MIN_SCANNED_MODULES: int = 900
# The keys GenericManager reads today; the scan must find at least these
EXPECTED_READ_KEYS: frozenset[str] = frozenset({'insert', 'get', 'iterate', 'update', 'delete'})


def defined_error_classes(source: str) -> list[str]:
    """
    The classes a module defines at its top level

    Args:
        source (str): A module's source

    Returns:
        list[str]: The class names, in source order
    """
    return [node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)]


def extended_names(source: str) -> set[str]:
    """
    The names a module's classes extend

    Args:
        source (str): A module's source

    Returns:
        set[str]: Every base class named directly or as an attribute
    """
    bases: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.add(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.add(base.attr)

    return bases


def error_map_entries(source: str) -> list[tuple[str, str]]:
    """
    The (key, class name) pairs of every dict literal mapping a string key to a name

    Args:
        source (str): An error package's ``__init__`` source

    Returns:
        list[tuple[str, str]]: One pair per entry, in source order
    """
    entries: list[tuple[str, str]] = []

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Name):
                    entries.append((key.value, value.id))

    return entries


def _is_exception_map(node: ast.expr) -> bool:
    """``<anything>.exceptions``"""
    return isinstance(node, ast.Attribute) and node.attr == EXCEPTION_MAP_ATTRIBUTE


def read_map_keys(source: str) -> set[str]:
    """
    The literal keys a module reads out of a manager's error map

    Args:
        source (str): A module's source

    Returns:
        set[str]: Every ``k`` of ``<x>.exceptions.get('k', ...)`` and ``<x>.exceptions['k']``
    """
    keys: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == DICT_GET
                and _is_exception_map(node.func.value) and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            keys.add(node.args[0].value)
        elif (isinstance(node, ast.Subscript) and _is_exception_map(node.value)
              and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            keys.add(node.slice.value)

    return keys


def referenced_names(source: str) -> set[str]:
    """
    Every name and attribute a module mentions

    Args:
        source (str): A module's source

    Returns:
        set[str]: The identifiers of every ``ast.Name`` and the attribute of every ``ast.Attribute``
    """
    names: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)

    return names


def find_unused_error_classes(
        error_sources: dict[str, str],
        other_sources: list[str],
        read_keys: set[str]) -> list[str]:
    """
    The error classes nothing raises, catches or extends

    Args:
        error_sources (dict[str, str]): Source per module of the error tree, keyed by its file name
        other_sources (list[str]): The sources of every other module of the tree
        read_keys (set[str]): The error-map keys some module reads

    Returns:
        list[str]: The unused class names, sorted
    """
    defined: set[str] = set()
    extended: set[str] = set()
    mapped_live: set[str] = set()

    for name, source in error_sources.items():
        defined.update(defined_error_classes(source))
        extended.update(extended_names(source))

        if name.endswith(PACKAGE_MODULE):
            mapped_live.update(cls for key, cls in error_map_entries(source) if key in read_keys)

    referenced: set[str] = set()

    for source in other_sources:
        referenced.update(referenced_names(source))

    return sorted(defined - referenced - extended - mapped_live)


def find_unread_map_keys(error_sources: dict[str, str], read_keys: set[str]) -> list[str]:
    """
    The error-map entries under a key no module reads

    Args:
        error_sources (dict[str, str]): Source per module of the error tree, keyed by its file name
        read_keys (set[str]): The error-map keys some module reads

    Returns:
        list[str]: ``<file>: <key> -> <class>`` per dead entry
    """
    return [
        f'{name}: {key} -> {cls}'
        for name, source in sorted(error_sources.items()) if name.endswith(PACKAGE_MODULE)
        for key, cls in error_map_entries(source) if key not in read_keys
    ]


ERROR_SOURCES: dict[str, str] = {
    str(path.relative_to(PROJECT_ROOT)): path.read_text(encoding='utf-8') for path in sorted(ERRORS_ROOT.rglob('*.py'))
}
OTHER_SOURCES: list[str] = [
    path.read_text(encoding='utf-8') for path in sorted(CMDB_ROOT.rglob('*.py')) if ERRORS_ROOT not in path.parents
]
READ_KEYS: set[str] = set().union(*(read_map_keys(source) for source in OTHER_SOURCES))


class TestTheDetector:
    """The scan's own rules, pinned on snippets - a detector that finds nothing passes every module."""

    ERRORS: str = (
        "class FamilyError(Exception):\n    pass\n\n"
        "class RaisedError(FamilyError):\n    pass\n\n"
        "class LiveMapError(FamilyError):\n    pass\n\n"
        "class DeadMapError(FamilyError):\n    pass\n\n"
        "class UnusedError(FamilyError):\n    pass\n"
    )
    PACKAGE: str = "MAP = {'insert': LiveMapError, 'init': DeadMapError}\n"

    def _unused(self, other: str, read_keys: set[str]) -> list[str]:
        """The detector over the fixture tree plus one other module"""
        return find_unused_error_classes(
            {'errors/x_errors.py': self.ERRORS, f'errors/{PACKAGE_MODULE}': self.PACKAGE}, [other], read_keys,
        )

    def test_only_the_unused_classes_are_found(self) -> None:
        """Raised, extended and mapped-under-a-read-key are used; the rest is not"""
        assert self._unused('raise RaisedError()\n', {'insert'}) == ['DeadMapError', 'UnusedError']

    def test_a_map_key_nobody_reads_does_not_keep_its_class(self) -> None:
        """The same map, but nothing reads 'insert' any more"""
        assert self._unused('raise RaisedError()\n', set()) == ['DeadMapError', 'LiveMapError', 'UnusedError']

    @pytest.mark.parametrize('other', [
        'try:\n    pass\nexcept UnusedError:\n    pass\n',
        'from x import errors\nraise errors.UnusedError()\n',
        'ERRORS = (UnusedError, ValueError)\n',
        'class Model:\n    INIT_FROM_DATA_ERROR = UnusedError\n',
    ], ids=['except-arm', 'attribute', 'error-tuple', 'model-declaration'])
    def test_every_spelling_of_a_use_counts(self, other: str) -> None:
        """A use is any mention outside the error tree"""
        assert 'UnusedError' not in self._unused(other, {'insert'})

    def test_a_read_key_is_found_in_both_spellings(self) -> None:
        """``.exceptions.get('k', ...)`` and ``.exceptions['k']``; a variable key and another dict are not"""
        source = (
            "self.exceptions.get('get', Exception)\n"
            "manager.exceptions['update']\n"
            "self.exceptions.get(operation, Exception)\n"
            "other.get('iterate')\n"
        )
        assert read_map_keys(source) == {'get', 'update'}

    def test_an_unread_map_key_is_named(self) -> None:
        """The dead 'init' entry of the fixture map"""
        assert find_unread_map_keys({f'errors/{PACKAGE_MODULE}': self.PACKAGE}, {'insert'}) == [
            f'errors/{PACKAGE_MODULE}: init -> DeadMapError',
        ]


def test_the_scan_covers_the_tree() -> None:
    """Guards the census itself: the error tree, its maps and the rest of cmdb/ are there"""
    assert sum(len(defined_error_classes(source)) for source in ERROR_SOURCES.values()) > MIN_ERROR_CLASSES
    assert sum(1 for name, source in ERROR_SOURCES.items()
               if name.endswith(PACKAGE_MODULE) and error_map_entries(source)) > MIN_ERROR_MAPS
    assert len(OTHER_SOURCES) > MIN_SCANNED_MODULES
    assert EXPECTED_READ_KEYS <= READ_KEYS


def test_no_error_class_is_unused() -> None:
    """A class nothing raises, catches or extends is deleted with the code that stopped raising it"""
    unused: list[str] = find_unused_error_classes(ERROR_SOURCES, OTHER_SOURCES, READ_KEYS)

    assert not unused, f'error classes nothing raises, catches or extends - delete them: {unused}'


def test_no_error_map_holds_a_key_nobody_reads() -> None:
    """Every error-map key is read by some manager - an 'init' key, for one, never is"""
    unread: list[str] = find_unread_map_keys(ERROR_SOURCES, READ_KEYS)

    assert not unread, f'error-map entries under a key no manager reads: {unread}'
