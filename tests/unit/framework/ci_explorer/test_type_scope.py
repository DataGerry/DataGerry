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
Unit tests for cmdb.framework.ci_explorer.type_scope

The type scope is what every CI Explorer source puts into its own read before the item_limit budget is spent:
the caller's types filter (allow-list) and the types the caller may not read (deny-list)
"""
from typing import Any

import pytest

from cmdb.framework.ci_explorer.type_scope import NeighbourTypeScope
# -------------------------------------------------------------------------------------------------------------------- #

ALLOWED: frozenset[int] = frozenset({7, 3})
DENIED: frozenset[int] = frozenset({11, 5})


class TestTypeClause:
    """The condition on a type_id value."""

    @pytest.mark.parametrize('scope,expected', [
        (NeighbourTypeScope(), {}),
        (NeighbourTypeScope(allowed=ALLOWED), {'$in': [3, 7]}),
        (NeighbourTypeScope(denied=DENIED), {'$nin': [5, 11]}),
        (NeighbourTypeScope(allowed=ALLOWED, denied=DENIED), {'$in': [3, 7], '$nin': [5, 11]}),
    ])
    def test_each_half_only_when_it_constrains(self, scope: NeighbourTypeScope, expected: dict[str, Any]) -> None:
        """Sorted, so the read is the same on every request"""
        assert scope.type_clause() == expected


class TestObjectCriteria:
    """The fragment an object read merges in."""

    def test_nothing_constrains_nothing_is_added(self) -> None:
        """An unscoped read stays unscoped"""
        assert not NeighbourTypeScope().object_criteria()

    def test_under_the_object_type_key(self) -> None:
        """type_id, the key a CmdbObject carries its type under"""
        assert NeighbourTypeScope(allowed=ALLOWED, denied=DENIED).object_criteria() == {
            'type_id': {'$in': [3, 7], '$nin': [5, 11]},
        }


class TestAdmits:
    """For a source that reads one object by id."""

    @pytest.mark.parametrize('scope,type_id,expected', [
        (NeighbourTypeScope(), 42, True),
        (NeighbourTypeScope(allowed=ALLOWED), 7, True),
        (NeighbourTypeScope(allowed=ALLOWED), 42, False),
        (NeighbourTypeScope(denied=DENIED), 11, False),
        (NeighbourTypeScope(denied=DENIED), 42, True),
        (NeighbourTypeScope(allowed=frozenset({11}), denied=DENIED), 11, False),
    ])
    def test_allowed_and_not_denied(self, scope: NeighbourTypeScope, type_id: int, expected: bool) -> None:
        """A denied type is refused even when the caller's filter names it"""
        assert scope.admits(type_id) is expected
