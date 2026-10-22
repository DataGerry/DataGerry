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
Tripwire: no test file copies the REST app-context fixture

A test that reaches the database through ManagerProvider needs the REST API app's context, and
``tests/fixtures/fixture_rest_api.rest_api_app_context`` is the one fixture that pushes it - switched on with
``pytest.mark.usefixtures``. A fixture whose whole body is ``with rest_api.application.app_context(): yield`` is a copy
of it, under whatever name. A fixture that also seeds data or yields a value does more than push the context and is
not a copy

Read with ``ast``, so every module is covered whether or not it is collected
"""
import ast
from pathlib import Path

from tests.utils.pylint_limits import REPO_ROOT
# -------------------------------------------------------------------------------------------------------------------- #

TESTS_ROOT: Path = REPO_ROOT / 'tests'
FIXTURES_ROOT: Path = TESTS_ROOT / 'fixtures'
CONTEXT_CALL: str = 'rest_api.application.app_context()'
SHARED_FIXTURE_MODULE: str = 'fixture_rest_api.py'

# The smallest tree the scan must still cover, so a moved folder cannot make it pass vacuously
MIN_SCANNED_TEST_FILES: int = 1000


def _is_context_copy(function: ast.FunctionDef) -> bool:
    """Whether the function's only statement (a docstring aside) pushes the REST app's context and yields nothing"""
    body: list[ast.stmt] = [statement for statement in function.body
                            if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]

    if len(body) != 1 or not isinstance(body[0], ast.With):
        return False

    block: ast.With = body[0]

    return (len(block.items) == 1 and ast.unparse(block.items[0].context_expr) == CONTEXT_CALL
            and len(block.body) == 1 and isinstance(block.body[0], ast.Expr)
            and isinstance(block.body[0].value, ast.Yield) and block.body[0].value.value is None)


def context_fixture_copies(root: Path, allowed: Path | None = None) -> list[str]:
    """
    Every function under a tree that is a copy of the REST app-context fixture

    Args:
        root (Path): The tree to scan
        allowed (Path | None): A folder whose modules may define it - the shared fixture's home

    Returns:
        list[str]: Each copy as '<path relative to root>:<line>'
    """
    return [
        f'{path.relative_to(root).as_posix()}:{node.lineno}'
        for path in sorted(root.rglob('*.py')) if allowed is None or allowed not in path.parents
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
        if isinstance(node, ast.FunctionDef) and _is_context_copy(node)
    ]


def test_no_test_file_copies_the_fixture() -> None:
    """Every module that needs the context switches the shared fixture on"""
    assert not context_fixture_copies(TESTS_ROOT, FIXTURES_ROOT)


def test_the_shared_fixture_is_the_one_the_scan_allows() -> None:
    """The scan would find it, were its folder not allowed - so it really looks for this shape"""
    found: list[str] = context_fixture_copies(FIXTURES_ROOT)

    assert [entry.split(':')[0] for entry in found] == [SHARED_FIXTURE_MODULE]


def test_the_scan_covers_the_tests() -> None:
    """A moved folder cannot make the scan pass on nothing"""
    assert sum(1 for _ in TESTS_ROOT.rglob('*.py')) >= MIN_SCANNED_TEST_FILES


def test_the_scan_finds_copies_and_lets_bigger_fixtures_through(tmp_path: Path) -> None:
    """Any name, with or without a docstring; a fixture that seeds or yields a value is no copy"""
    (tmp_path / 'test_copies.py').write_text(
        'def _app_context(rest_api):\n'
        '    with rest_api.application.app_context():\n'
        '        yield\n'
        'def _render_context(rest_api):\n'
        '    """Pushes the context"""\n'
        '    with rest_api.application.app_context():\n'
        '        yield\n',
        encoding='utf-8')
    (tmp_path / 'test_bigger.py').write_text(
        'def _seeded(rest_api, collection):\n'
        '    collection.insert_one({})\n'
        '    with rest_api.application.app_context():\n'
        '        yield\n'
        'def _manager(rest_api):\n'
        '    with rest_api.application.app_context():\n'
        '        yield make_manager()\n'
        'def _other_app():\n'
        '    with Flask(__name__).app_context():\n'
        '        yield\n',
        encoding='utf-8')

    assert context_fixture_copies(tmp_path) == ['test_copies.py:1', 'test_copies.py:4']
