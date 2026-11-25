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
Unit tests for cmdb.framework.access_engine.access_type_set

A role's stored ``types`` reads as every Type ('*'), its ids (non-int values passed over) or nothing (any other value);
every Type contains any id, also one no Type has; a union is every Type as soon as one side is
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import TypeSet
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_TYPE_ID: int = 11
SECOND_TYPE_ID: int = 12
OTHER_TYPE_ID: int = 13


class TestFromRoleTypes:
    """TypeSet.from_role_types"""

    def test_the_all_types_value_is_every_type(self) -> None:
        """'*' - every Type, no ids"""
        assert TypeSet.from_role_types('*') == TypeSet(every_type=True, ids=frozenset())

    def test_a_list_is_its_ids(self) -> None:
        """Repeats collapse"""
        assert TypeSet.from_role_types([FIRST_TYPE_ID, SECOND_TYPE_ID, FIRST_TYPE_ID]) == TypeSet.of(
            [FIRST_TYPE_ID, SECOND_TYPE_ID])

    def test_a_list_keeps_only_integers(self) -> None:
        """A bool, a string and None are no Type id"""
        assert TypeSet.from_role_types([FIRST_TYPE_ID, True, '12', None]).ids == frozenset({FIRST_TYPE_ID})

    @pytest.mark.parametrize('stored', [None, 'all', {'types': '*'}, 7], ids=['none', 'string', 'dict', 'int'])
    def test_any_other_value_names_no_type(self, stored: Any) -> None:
        """Fail closed: an unreadable value neither grants nor restricts"""
        assert TypeSet.from_role_types(stored).is_empty()


class TestContains:
    """TypeSet.contains"""

    def test_ids_contain_their_own(self) -> None:
        """Only the listed ids"""
        type_set: TypeSet = TypeSet.of([FIRST_TYPE_ID])

        assert type_set.contains(FIRST_TYPE_ID)
        assert not type_set.contains(SECOND_TYPE_ID)

    def test_every_type_contains_any_id(self) -> None:
        """Also an id no Type carries"""
        assert TypeSet.everything().contains(OTHER_TYPE_ID)


class TestUnion:
    """TypeSet.union and union_of"""

    def test_ids_join(self) -> None:
        """Both sides' ids"""
        assert TypeSet.of([FIRST_TYPE_ID]).union(TypeSet.of([SECOND_TYPE_ID])).ids == frozenset(
            {FIRST_TYPE_ID, SECOND_TYPE_ID})

    @pytest.mark.parametrize('left, right', [
        (TypeSet.everything(), TypeSet.of([FIRST_TYPE_ID])),
        (TypeSet.of([FIRST_TYPE_ID]), TypeSet.everything()),
    ], ids=['left', 'right'])
    def test_every_type_wins_on_either_side(self, left: TypeSet, right: TypeSet) -> None:
        """No ids kept beside it"""
        assert left.union(right) == TypeSet.everything()

    def test_union_of_nothing_is_empty(self) -> None:
        """No sets - no Type"""
        assert TypeSet.union_of([]).is_empty()

    def test_union_of_many(self) -> None:
        """Every set's ids"""
        assert TypeSet.union_of([TypeSet.of([FIRST_TYPE_ID]), TypeSet(), TypeSet.of([OTHER_TYPE_ID])]).ids == frozenset(
            {FIRST_TYPE_ID, OTHER_TYPE_ID})


class TestCovers:
    """TypeSet.covers"""

    @pytest.mark.parametrize('holder, other, expected', [
        (TypeSet.everything(), TypeSet.everything(), True),
        (TypeSet.everything(), TypeSet.of([FIRST_TYPE_ID]), True),
        (TypeSet.of([FIRST_TYPE_ID]), TypeSet.everything(), False),
        (TypeSet.of([FIRST_TYPE_ID, SECOND_TYPE_ID]), TypeSet.of([SECOND_TYPE_ID]), True),
        (TypeSet.of([FIRST_TYPE_ID]), TypeSet.of([FIRST_TYPE_ID, OTHER_TYPE_ID]), False),
        (TypeSet(), TypeSet(), True),
    ], ids=['every-every', 'every-ids', 'ids-every', 'superset', 'missing-one', 'empty'])
    def test_covers(self, holder: TypeSet, other: TypeSet, expected: bool) -> None:
        """Every Type covers anything; ids cover their subsets only"""
        assert holder.covers(other) is expected


def test_is_empty() -> None:
    """Only the set with neither every Type nor an id"""
    assert TypeSet().is_empty()
    assert not TypeSet.of([FIRST_TYPE_ID]).is_empty()
    assert not TypeSet.everything().is_empty()
