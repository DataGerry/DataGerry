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
Integration tests of GroupsManager.get_groups against a real MongoDB

Pinned: the asked groups come back built, ordered by id, with their rights resolved; an id no group carries is left
out; the union of the read groups grants what either holds
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.models.group_model import CmdbUserGroup, EffectiveRights
# -------------------------------------------------------------------------------------------------------------------- #

VIEWER_GROUP_ID: int = 93960
EDITOR_GROUP_ID: int = 93961
MISSING_GROUP_ID: int = 93969
TYPE_VIEW: str = 'base.framework.type.view'
OBJECT_WILDCARD: str = 'base.framework.object.*'
OBJECT_EDIT: str = 'base.framework.object.edit'


def _group_doc(public_id: int, *rights: str) -> dict[str, Any]:
    """A stored group holding the named rights"""
    return {'public_id': public_id, 'name': f'get-groups-{public_id}', 'label': 'Get groups', 'rights': list(rights)}


@pytest.fixture(name='groups_manager')
def fixture_groups_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[GroupsManager]:
    """Two groups, removed before and after"""
    collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    ids: list[int] = [VIEWER_GROUP_ID, EDITOR_GROUP_ID]
    collection.delete_many({'public_id': {'$in': ids}})
    collection.insert_many([_group_doc(EDITOR_GROUP_ID, OBJECT_WILDCARD), _group_doc(VIEWER_GROUP_ID, TYPE_VIEW)])

    yield GroupsManager(database_manager, database_name)

    collection.delete_many({'public_id': {'$in': ids}})


def test_the_asked_groups_are_read_ordered_with_their_rights(groups_manager: GroupsManager) -> None:
    """A missing id is left out; the rights are resolved through the tree"""
    groups = groups_manager.get_groups([EDITOR_GROUP_ID, MISSING_GROUP_ID, VIEWER_GROUP_ID])

    assert [group.public_id for group in groups] == [VIEWER_GROUP_ID, EDITOR_GROUP_ID]
    assert [[right.name for right in group.rights] for group in groups] == [[TYPE_VIEW], [OBJECT_WILDCARD]]


def test_the_union_grants_what_either_group_holds(groups_manager: GroupsManager) -> None:
    """The type right from one group, an object right through the other's wildcard"""
    rights = EffectiveRights(groups_manager.get_groups([VIEWER_GROUP_ID, EDITOR_GROUP_ID]))

    assert rights.grants(TYPE_VIEW) and rights.grants(OBJECT_EDIT)
    assert not rights.grants('base.framework.type.edit')


def test_the_union_lists_every_stored_right_once(groups_manager: GroupsManager) -> None:
    """What the login answer and GET /users/<id>/rights hand out: both groups' stored rights, by name, each once"""
    rights = EffectiveRights(groups_manager.get_groups([VIEWER_GROUP_ID, EDITOR_GROUP_ID, VIEWER_GROUP_ID]))

    assert [right['name'] for right in rights.rights_json()] == sorted([OBJECT_WILDCARD, TYPE_VIEW])
