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
Tripwire: a boolean flag is read by the API's one rule, never by a rule of its own

The rule is ``routes_helper.read_boolean_query_param`` / ``read_boolean_value``: ``true`` / ``false`` in any casing,
absent is the flag's default, anything else a 400 naming the flag. Flags used to be read their own way, each
defaulting silently on a value it did not recognise. This scan fails on the two shapes that did it:

* a comparison of a request value with the TEXT ``'true'`` / ``'True'`` - ``args.get(...) == 'true'``,
  ``args.get(...).lower() == 'true'``, ``args.get(...) in ['True', 'true']``
* a use of the lenient helpers that existed for it (``is_truthy_query_arg``, ``parse_bool_arg``)

Pure tests: AST only, nothing is imported from the scanned modules
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCANNED_ROOT: Path = REPO_ROOT / 'cmdb'

TRUE_SPELLINGS: frozenset[str] = frozenset({'true', 'True', 'TRUE'})
LENIENT_HELPERS: frozenset[str] = frozenset({'is_truthy_query_arg', 'parse_bool_arg'})

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 500


def _is_true_text(node: ast.AST) -> bool:
    """A string constant spelling true, or a list / tuple / set holding one"""
    if isinstance(node, ast.Constant):
        return node.value in TRUE_SPELLINGS

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_is_true_text(element) for element in node.elts)

    return False


def _reads_a_request_value(node: ast.AST) -> bool:
    """A ``<...>.args.get(...)`` call, possibly lower-cased or stripped"""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'lower', 'strip'}:
        node = node.func.value

    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get'
            and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'args')


def find_own_flag_rules(source: str) -> list[int]:
    """
    The lines that read a boolean flag by a rule of their own

    Args:
        source (str): A module's source

    Returns:
        list[int]: The offending line numbers
    """
    lines: list[int] = []

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare) and _reads_a_request_value(node.left) \
                and any(_is_true_text(comparator) for comparator in node.comparators):
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id in LENIENT_HELPERS:
            lines.append(node.lineno)
        elif isinstance(node, ast.alias) and node.name in LENIENT_HELPERS:
            lines.append(node.lineno)
        elif isinstance(node, ast.FunctionDef) and node.name in LENIENT_HELPERS:
            lines.append(node.lineno)

    return lines


def test_no_flag_has_a_rule_of_its_own() -> None:
    """Every module of cmdb/ - the message names each line to move to read_boolean_query_param"""
    modules: list[Path] = sorted(SCANNED_ROOT.rglob('*.py'))
    offences: list[str] = [
        f'{path.relative_to(REPO_ROOT)}:{line}'
        for path in modules
        for line in find_own_flag_rules(path.read_text(encoding='utf-8'))
    ]

    assert len(modules) >= MIN_SCANNED_MODULES
    assert not offences, 'Read these flags through read_boolean_query_param / read_boolean_value:\n' + '\n'.join(
        offences)


class TestTheDetector:
    """The scan itself, on hand-written snippets"""

    @pytest.mark.parametrize('source', [
        "x = request.args.get('flag') == 'true'",
        "x = request.args.get('flag', 'false').lower() == 'true'",
        "x = request.args.get('flag') in ['True', 'true']",
        "x = req.args.get('flag').strip().lower() == 'true'",
        "from cmdb.utils import is_truthy_query_arg",
        "x = parse_bool_arg(value)",
        "def is_truthy_query_arg(value):\n    return value",
    ], ids=['equals', 'lowered', 'in-list', 'stripped', 'import-helper', 'call-helper', 'define-helper'])
    def test_an_own_rule_is_flagged(self, source: str) -> None:
        """Each shape the scan claims to cover"""
        assert find_own_flag_rules(source)

    @pytest.mark.parametrize('source', [
        "x = read_boolean_query_param('flag', default=False)",
        "x = request.args.get('mode') == 'render'",
        "x = value == 'true'",
        "x = request.args.get('flag')",
    ], ids=['house-rule', 'not-a-flag', 'not-a-request-value', 'plain-read'])
    def test_what_is_not_flagged(self, source: str) -> None:
        """The house rule, a non-boolean comparison and a comparison of something else are left alone"""
        assert not find_own_flag_rules(source)
