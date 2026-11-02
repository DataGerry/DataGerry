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
Unit tests for cmdb_objects.objects_group_helper - the dashboard chart's rows from per-type counts and their types

A group whose type is gone is skipped and costs no place of the cap; every row is exactly the four chart keys; the
order of the counts is kept
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectGroupKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_group_helper import label_type_groups
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_TYPE_ID: int = 11
SECOND_TYPE_ID: int = 12
GONE_TYPE_ID: int = 13
CAP: int = 5


def _type(type_id: int) -> SimpleNamespace:
    """A CmdbType stand-in with a distinct label and colour"""
    return SimpleNamespace(label=f'label-{type_id}', ci_explorer_color=f'#{type_id:06d}')


def _group(type_id: int, count: int) -> dict[str, Any]:
    """One per-type count, as the manager answers it"""
    return {ObjectGroupKey.ID.value: type_id, ObjectGroupKey.COUNT.value: count}


def test_a_group_is_labelled_with_its_type() -> None:
    """The four chart keys, values from the group and from its type"""
    rows = label_type_groups([_group(FIRST_TYPE_ID, 3)], {FIRST_TYPE_ID: _type(FIRST_TYPE_ID)}, CAP)

    assert rows == [{'_id': FIRST_TYPE_ID, 'count': 3, 'label': f'label-{FIRST_TYPE_ID}',
                     'type_color': f'#{FIRST_TYPE_ID:06d}'}]


def test_a_group_whose_type_is_gone_is_skipped() -> None:
    """Objects of a deleted type have nothing to label them with"""
    rows = label_type_groups([_group(GONE_TYPE_ID, 9), _group(FIRST_TYPE_ID, 3)],
                             {FIRST_TYPE_ID: _type(FIRST_TYPE_ID)}, CAP)

    assert [row['_id'] for row in rows] == [FIRST_TYPE_ID]


def test_a_skipped_group_costs_no_place_of_the_cap() -> None:
    """The cap counts answered rows"""
    rows = label_type_groups([_group(GONE_TYPE_ID, 9), _group(FIRST_TYPE_ID, 3), _group(SECOND_TYPE_ID, 1)],
                             {FIRST_TYPE_ID: _type(FIRST_TYPE_ID), SECOND_TYPE_ID: _type(SECOND_TYPE_ID)}, 2)

    assert [row['_id'] for row in rows] == [FIRST_TYPE_ID, SECOND_TYPE_ID]


@pytest.mark.parametrize('cap', [1, 2])
def test_no_more_rows_than_the_cap(cap: int) -> None:
    """The largest groups first, as they came"""
    groups = [_group(type_id, 10 - type_id) for type_id in range(1, 6)]
    type_map = {type_id: _type(type_id) for type_id in range(1, 6)}

    assert [row['_id'] for row in label_type_groups(groups, type_map, cap)] == list(range(1, cap + 1))


def test_the_manager_groups_are_not_mutated() -> None:
    """New rows - the counts stay as the manager answered them"""
    groups = [_group(FIRST_TYPE_ID, 3)]

    label_type_groups(groups, {FIRST_TYPE_ID: _type(FIRST_TYPE_ID)}, CAP)

    assert groups == [_group(FIRST_TYPE_ID, 3)]


def test_no_groups_no_rows() -> None:
    """A tenant without objects"""
    assert not label_type_groups([], {}, CAP)
