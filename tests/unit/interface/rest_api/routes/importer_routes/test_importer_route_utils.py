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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_route_utils

Covers generate_parsed_output (saves the upload to a temp file, parses it, and always cleans the temp
file up) and verify_import_access (raises AccessDeniedError when the access-filtered query matches no type). The
shared request-parsing helpers moved to routes_helper and are tested there.
"""
import os
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from werkzeug.datastructures import FileStorage

from cmdb.interface.rest_api.routes.importer_routes.importer_route_utils import (
    generate_parsed_output,
    verify_import_access,
)
from cmdb.errors.security import AccessDeniedError
from cmdb.framework import access_engine
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_route_utils'


class TestGenerateParsedOutput:
    """generate_parsed_output saves the upload, parses it, and removes the temp file afterwards."""

    def test_parses_and_cleans_up_temp_file(self, monkeypatch) -> None:
        """The saved upload is parsed and the temporary file is removed once parsing finishes."""
        seen: dict = {}

        class _StubParser:
            """Records the file it was handed (path + content) and returns a marker output."""
            def __init__(self, config: dict) -> None:
                self.config = config

            def parse(self, path: str):
                """Read back the saved upload so the test can assert it was written."""
                seen['path'] = path
                with open(path, 'rb') as handle:
                    seen['content'] = handle.read()
                return 'PARSED_OUTPUT'

        monkeypatch.setattr(f'{MODULE_PATH}.load_parser_class', lambda *_a, **_k: _StubParser)

        upload = FileStorage(stream=BytesIO(b'dg-name\nhost-1\n'), filename='import.csv')
        result = generate_parsed_output(upload, 'csv', {})

        assert result == 'PARSED_OUTPUT'
        assert seen['content'] == b'dg-name\nhost-1\n'
        assert not os.path.exists(seen['path'])  # temp file cleaned up

    def test_temp_file_removed_even_when_parsing_fails(self, monkeypatch) -> None:
        """A parser error still triggers temp-file cleanup (the finally block)."""
        seen: dict = {}

        class _BoomParser:
            """Records the temp path, then fails during parsing."""
            def __init__(self, _config: dict) -> None:
                pass

            def parse(self, path: str):
                """Fail after the temp file has been created."""
                seen['path'] = path
                raise ValueError('bad file')

        monkeypatch.setattr(f'{MODULE_PATH}.load_parser_class', lambda *_a, **_k: _BoomParser)

        upload = FileStorage(stream=BytesIO(b'x'), filename='import.csv')

        with pytest.raises(ValueError):
            generate_parsed_output(upload, 'csv', {})

        assert not os.path.exists(seen['path'])


class TestVerifyImportAccess:
    """verify_import_access raises when the access-filtered type lookup returns nothing (the engine answers from no
    Type ACL - conftest)."""

    @staticmethod
    def _args(iterate_total: int):
        """Builds (user, type, types_manager stub) whose iterate reports the given total."""
        user = SimpleNamespace(group_ids=[2])
        cmdb_type = SimpleNamespace(public_id=5, name='server')
        types_manager = SimpleNamespace(
            iterate=lambda _params: SimpleNamespace(total=iterate_total, results=[], count=0)
        )
        return user, cmdb_type, types_manager

    def test_access_granted_does_not_raise(self) -> None:
        """A matching type (total >= 1) passes without raising."""
        user, cmdb_type, types_manager = self._args(iterate_total=1)

        verify_import_access(user, cmdb_type, types_manager)  # must not raise

    def test_access_denied_raises(self) -> None:
        """No matching type (total == 0) raises AccessDeniedError."""
        user, cmdb_type, types_manager = self._args(iterate_total=0)

        with pytest.raises(AccessDeniedError):
            verify_import_access(user, cmdb_type, types_manager)

    def test_iterate_receives_the_type_public_id(self) -> None:
        """The access query is scoped to the target type's public_id."""
        captured: dict = {}
        user = SimpleNamespace(group_ids=[2])
        cmdb_type = SimpleNamespace(public_id=5, name='server')

        def _iterate(params):
            captured['criteria'] = params.criteria
            return SimpleNamespace(total=1, results=[], count=0)

        verify_import_access(user, cmdb_type, SimpleNamespace(iterate=_iterate))

        assert {'public_id': 5} in captured['criteria']['$and']


# What the stubbed access engine answers as the permitted-types criteria - distinct, so its place is checked
ENGINE_CRITERIA: dict[str, Any] = {'public_id': {'$nin': [77]}}


class TestVerifyImportAccessUsesTheSharedRule:
    """
    The import guard asks the shared access rule, not a query of its own

    ``build_permitted_types_criteria`` hands the question to the access engine. These pin that the guard asks it for
    the importing user and for all three permissions at once (view + create + edit), and adds nothing but the type's
    own id beside the answer.
    """

    @staticmethod
    def _captured(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, list[tuple[Any, Any]]]:
        """
        Runs the guard with the engine stubbed

        Args:
            monkeypatch (pytest.MonkeyPatch): The test's monkeypatch

        Returns:
            tuple[dict, list[tuple[Any, Any]]]: The criteria handed to the manager, and each (user, operations) the
                engine was asked
        """
        captured: dict = {}
        asked: list[tuple[Any, Any]] = []

        def _permitted_types_criteria(user: Any, operations: Any) -> dict[str, Any]:
            asked.append((user, operations))
            return ENGINE_CRITERIA

        def _iterate(params):
            captured['criteria'] = params.get_criteria()
            return SimpleNamespace(total=1, results=[], count=0)

        monkeypatch.setattr(access_engine, 'permitted_types_criteria', _permitted_types_criteria)
        captured['user'] = SimpleNamespace(group_ids=[2])

        verify_import_access(
            captured['user'],
            SimpleNamespace(public_id=5, name='server'),
            SimpleNamespace(iterate=_iterate),
        )

        return captured, asked

    def test_the_criteria_is_the_engines_permitted_types_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The engine's answer itself, so the rule cannot drift here."""
        captured, _ = self._captured(monkeypatch)

        assert ENGINE_CRITERIA in captured['criteria']['$and']

    def test_it_asks_for_the_user_and_all_three_permissions_at_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One question covers read + create + update, asked for the importing user"""
        captured, asked = self._captured(monkeypatch)

        assert asked == [(captured['user'], [ScopeOperation.VIEW, ScopeOperation.CREATE, ScopeOperation.EDIT])]

    def test_it_adds_nothing_but_the_type_it_imports_into(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shared rule and the type's own id - no access clause of the importer's own beside the rule"""
        captured, _ = self._captured(monkeypatch)

        assert captured['criteria'] == {'$and': [ENGINE_CRITERIA, {'public_id': 5}]}
