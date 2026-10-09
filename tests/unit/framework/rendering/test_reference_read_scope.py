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
Unit tests for cmdb.framework.rendering.reference_read_scope.ReferenceReadScope

Pure tests: the denied-types read is patched. Pins that the scope asks for READ, reads the denied types
lazily and only once, reads nothing without a user, and starts with nothing recorded
"""
from typing import Any
from unittest.mock import Mock

import pytest

from cmdb.framework.rendering import reference_read_scope as scope_module
from cmdb.framework.rendering.reference_read_scope import ReferenceReadScope
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE_IDS: list[int] = [11, 12]


@pytest.fixture(name='reads')
def fixture_reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    """Records every denied-types read; each answers DENIED_TYPE_IDS."""
    reads: list[tuple[Any, Any]] = []

    def _resolve(user: Any, permission: Any) -> list[int]:
        reads.append((user, permission))
        return list(DENIED_TYPE_IDS)

    monkeypatch.setattr(scope_module, 'resolve_denied_type_ids', _resolve)

    return reads


class TestTheDeniedTypes:
    """denied_type_ids."""

    def test_they_are_the_users_read_denials(self, reads: list[tuple[Any, Any]]) -> None:
        """Read for the scope's user and the READ permission"""
        user = Mock(name='user')

        assert ReferenceReadScope(user).denied_type_ids == DENIED_TYPE_IDS
        assert reads == [(user, AccessControlPermission.READ)]

    def test_they_are_read_lazily(self, reads: list[tuple[Any, Any]]) -> None:
        """A scope nobody asks costs no query - a render without references never pays it"""
        ReferenceReadScope(Mock(name='user'))

        assert not reads

    def test_they_are_read_once(self, reads: list[tuple[Any, Any]]) -> None:
        """Every later ask is answered from the first read"""
        scope = ReferenceReadScope(Mock(name='user'))

        for _ in range(3):
            assert scope.denied_type_ids == DENIED_TYPE_IDS

        assert len(reads) == 1

    def test_without_a_user_nothing_is_denied(self, reads: list[tuple[Any, Any]]) -> None:
        """No user reads unscoped, as everywhere else in the object layer - and queries nothing"""
        assert ReferenceReadScope(None).denied_type_ids == []
        assert not reads


class TestANewScope:
    """What a scope starts with."""

    def test_it_records_nothing(self) -> None:
        """No id is unreturned before a load"""
        assert ReferenceReadScope(Mock(name='user')).unreturned_ids == set()

    def test_it_asks_for_read(self) -> None:
        """READ, the permission any read of an object asks"""
        assert ReferenceReadScope(Mock(name='user')).permission == AccessControlPermission.READ
