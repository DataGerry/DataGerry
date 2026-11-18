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
Unit tests for cmdb.models.group_model.effective_rights - the union of a user's groups

Pinned with real CmdbUserGroups and real rights: a right held directly or through a wildcard in any group is
granted; a right no group holds is not; no group grants nothing; the ids are the groups', sorted
"""
import pytest

from cmdb.models.group_model import CmdbUserGroup, EffectiveRights
from cmdb.models.right_model.all_rights import ALL_RIGHTS_FLAT
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_VIEW: str = 'base.framework.type.view'
OBJECT_VIEW: str = 'base.framework.object.view'
OBJECT_WILDCARD: str = 'base.framework.object.*'
OBJECT_EDIT: str = 'base.framework.object.edit'
FIRST_GROUP_ID: int = 41
SECOND_GROUP_ID: int = 42


def _group(public_id: int, *right_names: str) -> CmdbUserGroup:
    """A group holding the named rights of the real right tree"""
    return CmdbUserGroup.from_data(
        {'public_id': public_id, 'name': f'group-{public_id}', 'label': 'Group', 'rights': list(right_names)},
        ALL_RIGHTS_FLAT,
    )


RIGHTS: EffectiveRights = EffectiveRights([_group(SECOND_GROUP_ID, OBJECT_WILDCARD), _group(FIRST_GROUP_ID, TYPE_VIEW)])


@pytest.mark.parametrize('right_name', [TYPE_VIEW, OBJECT_VIEW, OBJECT_EDIT], ids=['direct', 'wildcard', 'wildcard-2'])
def test_a_right_of_any_group_is_granted(right_name: str) -> None:
    """Directly in the first group, through a wildcard in the second"""
    assert RIGHTS.grants(right_name)


def test_a_right_no_group_holds_is_not_granted() -> None:
    """The union adds, it never invents"""
    assert not RIGHTS.grants('base.framework.type.edit')


def test_direct_and_extended_are_asked_apart() -> None:
    """has_right is the direct holding only; has_extended_right the wildcard only"""
    assert (RIGHTS.has_right(TYPE_VIEW), RIGHTS.has_extended_right(TYPE_VIEW)) == (True, False)
    assert (RIGHTS.has_right(OBJECT_VIEW), RIGHTS.has_extended_right(OBJECT_VIEW)) == (False, True)


def test_no_group_grants_nothing() -> None:
    """A user none of whose groups exists"""
    assert not EffectiveRights([]).grants(TYPE_VIEW)


def test_the_group_ids_are_sorted() -> None:
    """Whatever order the groups came in"""
    assert RIGHTS.group_ids == [FIRST_GROUP_ID, SECOND_GROUP_ID]


def test_the_rights_are_the_union_each_once_sorted_by_name() -> None:
    """Two groups holding the same right add it once; a wildcard stays a wildcard"""
    rights = EffectiveRights([
        _group(FIRST_GROUP_ID, TYPE_VIEW, OBJECT_WILDCARD),
        _group(SECOND_GROUP_ID, OBJECT_WILDCARD, OBJECT_EDIT),
    ])

    assert [right.name for right in rights.rights] == sorted({TYPE_VIEW, OBJECT_WILDCARD, OBJECT_EDIT})


def test_the_rights_json_is_the_groups_answer_shape() -> None:
    """What GET /groups/<id> answers a group's rights as - so a client reads both alike"""
    group: CmdbUserGroup = _group(FIRST_GROUP_ID, TYPE_VIEW, OBJECT_EDIT)

    assert EffectiveRights([group]).rights_json() == CmdbUserGroup.to_json(group)['rights']


def test_no_group_has_no_rights() -> None:
    """An empty list, not None"""
    assert EffectiveRights([]).rights_json() == []
