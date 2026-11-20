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
Unit tests for cmdb.framework.person_types.person_memberships - a person's memberships changed from its side
"""
from typing import Any

import pytest

from cmdb.framework.person_types.person_memberships import (
    group_members,
    holding_members_criteria,
    members_after,
    membership_targets,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSON: int = 9


@pytest.mark.parametrize('current, add, remove, expected', [
    ({1, 2}, {2, 3}, set(), [3]),
    ({1, 2}, set(), {2, 4}, [2]),
    ({1}, {5}, {1}, [1, 5]),
    ({1}, {1}, {2}, []),
], ids=['joins-only-new', 'leaves-only-held', 'both-ascending', 'nothing-to-write'])
def test_the_targets_are_the_groups_that_change(current: set[int], add: set[int], remove: set[int],
                                                expected: list[int]) -> None:
    """A group already as asked is left alone"""
    assert membership_targets(current, add, remove) == expected


@pytest.mark.parametrize('members, join, expected', [
    ([3, 1], True, [3, 1, PERSON]),
    ([3, PERSON, 1], True, [3, PERSON, 1]),
    (None, True, [PERSON]),
    ([3, PERSON, 1], False, [3, 1]),
    ([3, 1], False, [3, 1]),
    ('broken', False, []),
], ids=['joins-at-the-end', 'joins-once', 'joins-an-empty-group', 'leaves', 'leaves-a-group-without-it',
        'not-a-list'])
def test_the_members_after(members: Any, join: bool, expected: list[Any]) -> None:
    """Every other member kept in its place"""
    assert members_after(members, PERSON, join) == expected


def test_the_stored_members_are_not_changed() -> None:
    """A new list"""
    stored: list[int] = [3]

    members_after(stored, PERSON, True)

    assert stored == [3]


@pytest.mark.parametrize('fields, expected', [
    ([{'name': 'members', 'value': [3, 'x', 1, None]}], [3, 1]),
    ([{'name': 'members', 'value': None}], []),
    ([{'name': 'name', 'value': 'Ops'}], []),
], ids=['ids-only', 'null', 'absent'])
def test_a_groups_members(fields: list[dict[str, Any]], expected: list[int]) -> None:
    """The person ids, in their stored order"""
    assert group_members({'fields': fields}) == expected


def test_the_criteria_select_a_group_holding_any_person() -> None:
    """One elemMatch on the members"""
    assert holding_members_criteria([PERSON, 4]) == {
        'fields': {'$elemMatch': {'name': 'members', 'value': {'$in': [PERSON, 4]}}}}
