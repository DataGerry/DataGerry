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
Unit tests for tests.utils.cmdb_app_stub, and a tripwire against copies of it

``stub_cmdb_app`` is the one builder of a unit test's BaseCmdbApp. Pinned: what each argument sets - the database
manager's three cases (a fresh mock, None kept, a value kept), the mode flags, the fenced-off tenants - and that no
test file defines its own ``_app`` returning a BaseCmdbApp again. A plain ``Flask`` app stays allowed: a test whose
code reads nothing but ``current_app.cloud_mode`` may keep one
"""
import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import current_app

from cmdb.interface.cmdb_app import BaseCmdbApp
from tests.utils.cmdb_app_stub import stub_cmdb_app
from tests.utils.pylint_limits import REPO_ROOT
# -------------------------------------------------------------------------------------------------------------------- #

TESTS_ROOT: Path = REPO_ROOT / 'tests'
STUB_MODULE: Path = TESTS_ROOT / 'utils' / 'cmdb_app_stub.py'
APP_CLASS: str = 'BaseCmdbApp'
HELPER_NAME: str = '_app'
SENTINEL: str = 'the-dbm'
FENCED: frozenset[str] = frozenset({'tenant_a', 'tenant_b'})

# The smallest tree the scan must still cover, so a moved folder cannot make it pass vacuously
MIN_SCANNED_TEST_FILES: int = 1000


class TestStubCmdbApp:
    """What the builder sets"""

    def test_the_defaults(self) -> None:
        """On premise, a fresh mock database manager per app, no tenant fenced off"""
        first, second = stub_cmdb_app(), stub_cmdb_app()

        assert isinstance(first, BaseCmdbApp)
        assert (first.cloud_mode, first.local_mode, first.unavailable_tenants) == (False, False, frozenset())
        assert isinstance(first.database_manager, MagicMock)
        assert first.database_manager is not second.database_manager

    def test_none_leaves_the_app_without_a_database_manager(self) -> None:
        """Code that wrongly reads it fails instead of reading a mock"""
        assert stub_cmdb_app(database_manager=None).database_manager is None

    def test_a_given_database_manager_is_set_as_it_is(self) -> None:
        """A sentinel the test compares against"""
        assert stub_cmdb_app(database_manager=SENTINEL).database_manager == SENTINEL

    @pytest.mark.parametrize('cloud_mode, local_mode', [(True, False), (True, True), (False, False)],
                             ids=['cloud', 'cloud-local', 'on-premise'])
    def test_the_mode_flags(self, cloud_mode: bool, local_mode: bool) -> None:
        """Positional, as most callers pass them"""
        app = stub_cmdb_app(cloud_mode, local_mode)

        assert (app.cloud_mode, app.local_mode) == (cloud_mode, local_mode)

    def test_the_fenced_tenants(self) -> None:
        """What tenant_availability reads"""
        assert stub_cmdb_app(unavailable_tenants=FENCED).unavailable_tenants == FENCED

    def test_the_options_are_keyword_only(self) -> None:
        """A third positional argument cannot be mistaken for a database manager"""
        positional: tuple = (False, False, SENTINEL)

        with pytest.raises(TypeError):
            stub_cmdb_app(*positional)

    def test_current_app_is_the_stub_inside_its_context(self) -> None:
        """What a helper under test reads"""
        app = stub_cmdb_app(cloud_mode=True)

        with app.test_request_context():
            assert current_app.cloud_mode is True


def _returns_a_cmdb_app(function: ast.FunctionDef) -> bool:
    """Whether a helper is annotated to return a BaseCmdbApp, or builds one"""
    annotated: bool = function.returns is not None and APP_CLASS in ast.unparse(function.returns)
    builds: bool = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == APP_CLASS
                       for node in ast.walk(function))

    return annotated or builds


def app_stub_copies(root: Path) -> list[str]:
    """
    Every function named `_app` under a tree that returns or builds a BaseCmdbApp - a copy of the shared stub

    Args:
        root (Path): The tree to scan

    Returns:
        list[str]: Each copy as '<path relative to root>:<line>'
    """
    return [
        f'{path.relative_to(root).as_posix()}:{node.lineno}'
        for path in sorted(root.rglob('*.py')) if path != STUB_MODULE
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
        if isinstance(node, ast.FunctionDef) and node.name == HELPER_NAME and _returns_a_cmdb_app(node)
    ]


class TestNoCopiesOfTheStub:
    """New tests use stub_cmdb_app"""

    def test_no_test_file_defines_its_own(self) -> None:
        """A plain Flask `_app` is allowed; one returning a BaseCmdbApp is a copy"""
        assert not app_stub_copies(TESTS_ROOT)

    def test_the_scan_covers_the_tests(self) -> None:
        """A moved folder cannot make the scan pass on nothing"""
        assert sum(1 for _ in TESTS_ROOT.rglob('*.py')) >= MIN_SCANNED_TEST_FILES

    def test_the_scan_finds_a_copy_and_lets_a_plain_flask_app_through(self, tmp_path: Path) -> None:
        """Module level and nested, annotated or not; the Flask stub stays"""
        (tmp_path / 'test_copy.py').write_text(
            'def _app() -> BaseCmdbApp:\n'
            '    return BaseCmdbApp(__name__)\n'
            'class TestX:\n'
            '    @staticmethod\n'
            '    def _app():\n'
            '        return BaseCmdbApp(__name__)\n',
            encoding='utf-8')
        (tmp_path / 'test_flask.py').write_text(
            'def _app() -> Flask:\n'
            '    return Flask(__name__)\n',
            encoding='utf-8')

        assert app_stub_copies(tmp_path) == ['test_copy.py:1', 'test_copy.py:5']
