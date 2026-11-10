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
Tripwire: every right the catalogue offers is used by the code, or is listed as reserved

A right in ``ALL_RIGHTS`` is offered by ``GET /rights/`` and the group screens: an administrator can grant it, and a
right nothing asks for changes nothing. The rule: a right is added together with the check that asks for it, and the
change that drops the last check removes the right (and its holders' copies, by an updater) - or lists it in
``RESERVED_RIGHTS`` with the reason.

A specific right (not a ``*`` wildcard, which grants what lies below it) counts as used when a module of ``cmdb/``
outside the catalogue (``cmdb/models/right_model/``) and the updaters:

* names it as a string literal anywhere but as the value of a definition (``right='...'``, a list of rights), or
* references a holder of it: an enum member (``XRight.EDIT``) or a module-level constant (``GROUP_EDIT_RIGHT``) whose
  value it is. A holder that is defined and never referenced does NOT count - that is how ten rights went unnoticed.

The holders are found at runtime, every ``cmdb`` module but the updaters imported (the catalogue's package included),
so a name built by an f-string resolves; the uses are read with ``ast``.
"""
import ast
import enum
import importlib
import pkgutil
from pathlib import Path
from typing import Any

import pytest

import cmdb
from cmdb.models.right_model.all_rights import ALL_RIGHTS_FLAT
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CMDB_ROOT: Path = PROJECT_ROOT / 'cmdb'

# The catalogue itself and the frozen literals of the updaters are no use of a right
EXCLUDED_PATHS: tuple[Path, ...] = (
    CMDB_ROOT / 'models' / 'right_model',
    CMDB_ROOT / 'database' / 'updater' / 'versions',
)
# The holders are collected from the catalogue's package too (``ObjectRightName`` lives there); not from the updaters
HOLDER_EXCLUDED_MODULES: tuple[str, ...] = ('cmdb.database.updater.versions',)

# Rights kept in the catalogue although nothing uses them, each with the reason. Empty: none is kept
RESERVED_RIGHTS: dict[str, str] = {}

# The smallest population the scan must still find, so a moved package cannot make it pass vacuously
MIN_SPECIFIC_RIGHTS: int = 140
MIN_SCANNED_MODULES: int = 1000
MIN_HELD_RIGHTS: int = 50

# One holder of a right: (owner class name or None for a module constant, attribute name)
Holder = tuple[str | None, str]


def specific_right_names() -> set[str]:
    """
    The catalogue's rights that grant one thing - the ``*`` wildcards left out

    Returns:
        set[str]: Their names
    """
    return {right.name for right in ALL_RIGHTS_FLAT if not right.name.endswith(GLOBAL_RIGHT_IDENTIFIER)}


def scanned_sources() -> list[str]:
    """
    The source of every module of ``cmdb/`` outside the excluded paths

    Returns:
        list[str]: One source per module
    """
    return [
        path.read_text(encoding='utf-8') for path in sorted(CMDB_ROOT.rglob('*.py'))
        if not any(path.is_relative_to(excluded) for excluded in EXCLUDED_PATHS)
    ]


def _constant_assignments(module: Any) -> set[str]:
    """The names a module assigns at its top level, read from its source."""
    source_file: str | None = getattr(module, '__file__', None)

    if not source_file:
        return set()

    names: set[str] = set()

    for node in ast.parse(Path(source_file).read_text(encoding='utf-8')).body:
        targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else \
            [node.target] if isinstance(node, ast.AnnAssign) else []
        names.update(target.id for target in targets if isinstance(target, ast.Name))

    return names


def module_holders(module: Any, rights: set[str]) -> dict[str, set[Holder]]:
    """
    The enum members and module-level constants a module defines whose value is a right

    Args:
        module (Any): An imported module
        rights (set[str]): The right names looked for

    Returns:
        dict[str, set[Holder]]: The holders per right name
    """
    holders: dict[str, set[Holder]] = {}
    assigned: set[str] = _constant_assignments(module)

    for name, value in vars(module).items():
        if isinstance(value, type) and issubclass(value, enum.Enum) and value.__module__ == module.__name__:
            for member in value:
                if isinstance(member.value, str) and member.value in rights:
                    holders.setdefault(member.value, set()).add((value.__name__, member.name))
        elif isinstance(value, str) and value in rights and name in assigned:
            holders.setdefault(str(value), set()).add((None, name))

    return holders


def collect_holders(rights: set[str]) -> tuple[dict[str, set[Holder]], int]:
    """
    Imports every ``cmdb`` module but the updaters and collects the holders of each right

    Args:
        rights (set[str]): The right names looked for

    Returns:
        tuple[dict[str, set[Holder]], int]: The holders per right name, and how many modules were imported
    """
    holders: dict[str, set[Holder]] = {}
    count: int = 0

    for info in pkgutil.walk_packages(cmdb.__path__, f'{cmdb.__name__}.'):
        if info.name.startswith(HOLDER_EXCLUDED_MODULES):
            continue

        count += 1

        for right, found in module_holders(importlib.import_module(info.name), rights).items():
            holders.setdefault(right, set()).update(found)

    return holders, count


def _defined_values(tree: ast.AST) -> set[int]:
    """The ids of the string constants that are the whole value of an assignment."""
    return {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant)
    }


def _owner_name(node: ast.expr) -> str | None:
    """The last name of an attribute's object: ``XRight`` for ``XRight.EDIT`` and ``mod.XRight.EDIT``."""
    if isinstance(node, ast.Name):
        return node.id

    return node.attr if isinstance(node, ast.Attribute) else None


def source_uses(source: str, rights: set[str]) -> tuple[set[str], set[Holder]]:
    """
    The rights a module names as a literal use, and the holders it references

    Args:
        source (str): A module's source
        rights (set[str]): The right names looked for

    Returns:
        tuple[set[str], set[Holder]]: The rights named by a literal that is no definition's value, and every
            ``(owner, attribute)`` / ``(None, name)`` the module references
    """
    tree: ast.AST = ast.parse(source)
    definitions: set[int] = _defined_values(tree)
    literals: set[str] = set()
    references: set[Holder] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in rights and id(node) not in definitions:
            literals.add(node.value)
        elif isinstance(node, ast.Attribute):
            references.add((_owner_name(node.value), node.attr))
            references.add((None, node.attr))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            references.add((None, node.id))

    return literals, references


def find_unused_rights(rights: set[str], holders: dict[str, set[Holder]], sources: list[str]) -> list[str]:
    """
    The rights no module uses

    Args:
        rights (set[str]): The right names to judge
        holders (dict[str, set[Holder]]): The holders per right name
        sources (list[str]): The sources of the scanned modules

    Returns:
        list[str]: The unused rights, sorted
    """
    used: set[str] = set()
    references: set[Holder] = set()

    for source in sources:
        literals, referenced = source_uses(source, rights)
        used |= literals
        references |= referenced

    used |= {right for right in rights if holders.get(right, set()) & references}

    return sorted(rights - used)

# ----------------------------------------------------- THE SCAN ----------------------------------------------------- #

@pytest.fixture(name='scan', scope='module')
def fixture_scan() -> dict[str, Any]:
    """The catalogue, the holders and the sources, collected once"""
    rights: set[str] = specific_right_names()
    holders, module_count = collect_holders(rights)

    return {'rights': rights, 'holders': holders, 'modules': module_count, 'sources': scanned_sources()}


def test_the_scan_covers_the_tree(scan: dict[str, Any]) -> None:
    """Guards the scan itself"""
    assert len(scan['rights']) >= MIN_SPECIFIC_RIGHTS
    assert scan['modules'] >= MIN_SCANNED_MODULES
    assert len(scan['holders']) >= MIN_HELD_RIGHTS


def test_every_right_is_used_or_reserved(scan: dict[str, Any]) -> None:
    """Names each right nothing uses: add the check that asks for it, remove it, or reserve it with a reason"""
    unused: list[str] = find_unused_rights(scan['rights'], scan['holders'], scan['sources'])

    assert [right for right in unused if right not in RESERVED_RIGHTS] == []


def test_a_reserved_right_is_in_the_catalogue_and_unused(scan: dict[str, Any]) -> None:
    """A reservation goes when the right is used or leaves the catalogue"""
    unused: list[str] = find_unused_rights(scan['rights'], scan['holders'], scan['sources'])

    assert [right for right in RESERVED_RIGHTS if right not in unused] == []

# ------------------------------------------------- THE SCAN'S RULES ------------------------------------------------- #

def test_a_defined_and_never_referenced_enum_member_is_unused() -> None:
    """The case the name-only scan missed: the member's definition is no use"""
    source: str = "class XRight:\n    ADD = 'base.x.add'\n    EDIT = 'base.x.edit'\n"
    holders: dict[str, set[Holder]] = {'base.x.add': {('XRight', 'ADD')}, 'base.x.edit': {('XRight', 'EDIT')}}
    route: str = "@bp.protect(auth=True, right=XRight.EDIT.value)\ndef f():\n    pass\n"

    assert find_unused_rights({'base.x.add', 'base.x.edit'}, holders, [source, route]) == ['base.x.add']


def test_a_member_reached_through_its_module_counts() -> None:
    """``constants.XRight.EDIT`` is a reference of ``XRight.EDIT``"""
    holders: dict[str, set[Holder]] = {'base.x.edit': {('XRight', 'EDIT')}}

    assert find_unused_rights({'base.x.edit'}, holders, ['right = constants.XRight.EDIT.value\n']) == []


def test_a_referenced_module_constant_counts() -> None:
    """A constant holder is used where its name is read"""
    holders: dict[str, set[Holder]] = {'base.x.edit': {(None, 'X_EDIT_RIGHT')}}
    sources: list[str] = ["X_EDIT_RIGHT: str = 'base.x.edit'\n", 'check(X_EDIT_RIGHT)\n']

    assert find_unused_rights({'base.x.edit'}, holders, sources) == []


def test_a_literal_outside_a_definition_counts() -> None:
    """``right='...'`` and a list of rights are uses; ``X = '...'`` alone is not"""
    rights: set[str] = {'base.x.view', 'base.x.add', 'base.x.edit'}
    sources: list[str] = [
        "@bp.protect(right='base.x.view')\ndef f():\n    pass\n",
        "NEEDED = ['base.x.add']\n",
        "X_EDIT = 'base.x.edit'\n",
    ]

    assert find_unused_rights(rights, {}, sources) == ['base.x.edit']


def test_a_member_of_another_enum_with_the_same_attribute_is_no_reference() -> None:
    """``YRight.EDIT`` does not use ``XRight.EDIT``"""
    holders: dict[str, set[Holder]] = {'base.x.edit': {('XRight', 'EDIT')}}

    assert find_unused_rights({'base.x.edit'}, holders, ['right = YRight.EDIT.value\n']) == ['base.x.edit']


def test_the_wildcards_are_not_judged() -> None:
    """A ``*`` right grants what lies below it, so it is never named by a check"""
    assert not any(right.endswith(GLOBAL_RIGHT_IDENTIFIER) for right in specific_right_names())
