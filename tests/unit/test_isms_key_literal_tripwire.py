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
Tripwire: ISMS code spells ISMS document keys through their key enums, never as string literals

Every ISMS document key has a member on one of the `*Key` enums in `cmdb/models/isms_model/*_constants.py`.
A literal spelling of the same key keeps working until someone renames the key in one place and not the
other, and the ISMS code has drifted back to literals before. This scan fails on a string literal in a
KEY position - a dict key, a subscript, the first argument of `.get` / `.pop` / `.setdefault` - whose value
is the value of an ISMS key enum member.

What it deliberately does not flag:

* `public_id` and `name` (`GENERIC_KEYS`): every model has them, and ISMS code reads them off object groups,
  persons, types and objects as often as off ISMS documents, so a literal says nothing about ownership.
* Index declarations (a dict carrying a `keys` entry): `name` / `keys` / `unique` are the DAO convention.

Pure tests: AST only, nothing is imported from the scanned modules
"""
import ast
import importlib
import inspect
from enum import Enum
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ISMS_CONSTANTS_GLOB: str = 'cmdb/models/isms_model/*_constants.py'

SCANNED_GLOBS: tuple[str, ...] = (
    'cmdb/manager/isms_manager/**/*.py',
    'cmdb/interface/rest_api/routes/isms_routes/**/*.py',
    'cmdb/interface/rest_api/routes/importer_routes/importer_isms_routes.py',
    'cmdb/class_schema/isms_model/**/*.py',
    'cmdb/models/isms_model/**/*.py',
    'cmdb/framework/isms/**/*.py',
)

GENERIC_KEYS: frozenset[str] = frozenset({'public_id', 'name'})
INDEX_DECLARATION_KEY: str = 'keys'
KEY_ACCESS_METHODS: frozenset[str] = frozenset({'get', 'pop', 'setdefault'})


def _isms_key_values() -> dict[str, list[str]]:
    """Maps every ISMS key-enum value to the members that carry it (`RiskKey.THREATS`, ...)."""
    values: dict[str, list[str]] = {}

    for path in sorted(REPO_ROOT.glob(ISMS_CONSTANTS_GLOB)):
        module = importlib.import_module('.'.join(path.relative_to(REPO_ROOT).with_suffix('').parts))

        for enum_name, enum_cls in vars(module).items():
            is_key_enum = (inspect.isclass(enum_cls) and issubclass(enum_cls, Enum)
                           and enum_cls.__module__ == module.__name__ and enum_name.endswith('Key'))
            if not is_key_enum:
                continue

            for member in enum_cls:
                if isinstance(member.value, str):
                    values.setdefault(member.value, []).append(f'{enum_name}.{member.name}')

    return values


def _scanned_files() -> list[str]:
    """Every scanned module, repo-relative, constants modules excluded (they define the enums)."""
    files: set[str] = set()

    for pattern in SCANNED_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.name.endswith('_constants.py'):
                files.add(path.relative_to(REPO_ROOT).as_posix())

    return sorted(files)


def _key_nodes(tree: ast.AST) -> list[ast.AST]:
    """The nodes sitting in a key position, index declarations left out."""
    index_declarations: set[int] = {
        id(node) for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == INDEX_DECLARATION_KEY for key in node.keys)
    }
    nodes: list[ast.AST] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and id(node) not in index_declarations:
            nodes.extend(key for key in node.keys if key is not None)
        elif isinstance(node, ast.Subscript):
            nodes.append(node.slice)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in KEY_ACCESS_METHODS and node.args):
            nodes.append(node.args[0])

    return nodes


def find_literal_keys(relative_path: str, key_values: dict[str, list[str]]) -> list[str]:
    """
    Lists the ISMS key literals in one module

    Args:
        relative_path (str): The module, relative to the repository root
        key_values (dict[str, list[str]]): ISMS key-enum value -> the members carrying it

    Returns:
        list[str]: One `path:line: 'key' -> Enum.MEMBER` line per literal
    """
    tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding='utf-8'))

    return [
        f"{relative_path}:{node.lineno}: '{node.value}' -> {' / '.join(key_values[node.value])}"
        for node in _key_nodes(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value in key_values and node.value not in GENERIC_KEYS
    ]


@pytest.fixture(scope='module', name='key_values')
def fixture_key_values() -> dict[str, list[str]]:
    """The ISMS key-enum values, read once."""
    return _isms_key_values()


def test_the_scan_sees_the_isms_code(key_values: dict[str, list[str]]) -> None:
    """An empty glob or an empty enum map would make the tripwire pass vacuously."""
    scanned = _scanned_files()

    assert len(scanned) > 50
    assert 'risk_assessment_id' in key_values


def test_no_isms_key_is_spelled_as_a_literal(key_values: dict[str, list[str]]) -> None:
    """The message lists every literal with the enum member to use instead."""
    offences = [
        line
        for path in _scanned_files()
        for line in find_literal_keys(path, key_values)
    ]

    assert not offences, 'Spell these ISMS keys through their enum:\n' + '\n'.join(offences)


class TestTheDetector:
    """The scan itself, on hand-written snippets."""

    @pytest.mark.parametrize('source', [
        "x = {'risk_id': 1}",
        "x = doc['risk_id']",
        "x = doc.get('risk_id')",
        "x = doc.pop('risk_id', None)",
    ], ids=['dict-key', 'subscript', 'get', 'pop'])
    def test_a_key_position_is_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """Each key position the scan claims to cover."""
        assert self._scan(source, tmp_path, monkeypatch)

    @pytest.mark.parametrize('source', [
        "x = {'public_id': 1, 'name': 'a'}",
        "INDEX_KEYS = [{'keys': [('risk_id', 1)], 'name': 'risk_id', 'unique': False}]",
        "x = 'risk_id'",
        "x = {'not_an_isms_key': 1}",
    ], ids=['generic-keys', 'index-declaration', 'plain-string', 'unknown-key'])
    def test_what_is_not_flagged(self, source: str, tmp_path: Path, monkeypatch) -> None:
        """A value outside a key position, a generic key and an index declaration are all left alone."""
        assert not self._scan(source, tmp_path, monkeypatch)

    @staticmethod
    def _scan(source: str, tmp_path: Path, monkeypatch) -> list[str]:
        """Runs the detector over one snippet, with a one-entry enum map."""
        (tmp_path / 'snippet.py').write_text(source, encoding='utf-8')
        monkeypatch.setattr(f'{__name__}.REPO_ROOT', tmp_path)

        return find_literal_keys('snippet.py', {'risk_id': ['RiskAssessmentKey.RISK_ID']})
