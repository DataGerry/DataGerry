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
Integration tests for cmdb.database.updater.versions.updater_20261008 against a real MongoDB

Seeds the fixed ``user`` group without the relation view rights (its stored rights are restored afterwards), and
object relations whose stored object types are stale, missing, already right, or point at a deleted object, runs
the migration, and asserts:

  - the group gains both rights, once, and keeps every right it held
  - a stale or missing type becomes the object's live type; a correct one and a deleted object's are left alone;
    nothing else of a relation changes
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261008 import GRANTED_RIGHTS, Update20261008
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

PARENT_OBJECT_ID: int = 97801
CHILD_OBJECT_ID: int = 97802
GONE_OBJECT_ID: int = 97803
PARENT_TYPE_ID: int = 97811
CHILD_TYPE_ID: int = 97812
STALE_TYPE_ID: int = 97813

STALE_RELATION_ID: int = 97821
UNSTAMPED_RELATION_ID: int = 97822
CORRECT_RELATION_ID: int = 97823
GONE_END_RELATION_ID: int = 97824
ALL_RELATION_IDS: list[int] = [STALE_RELATION_ID, UNSTAMPED_RELATION_ID, CORRECT_RELATION_ID, GONE_END_RELATION_ID]

KEPT_RIGHT: str = 'base.framework.object.*'
PARENT_TYPE: str = 'relation_parent_type_id'
CHILD_TYPE: str = 'relation_child_type_id'


def _relation(public_id: int, child_id: int, **types: Any) -> dict[str, Any]:
    """A stored object relation from PARENT_OBJECT_ID to ``child_id``, with whatever types it was written with"""
    return {
        'public_id': public_id, 'relation_id': 1, 'relation_parent_id': PARENT_OBJECT_ID,
        'relation_child_id': child_id, 'field_values': [{'name': 'port', 'value': str(public_id)}], **types,
    }


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded objects and relations, and the user group stripped of the two rights - all restored after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    stored_rights: list[str] = groups.find_one({'public_id': USER_GROUP_ID})['rights']

    def _purge() -> None:
        objects.delete_many({'public_id': {'$in': [PARENT_OBJECT_ID, CHILD_OBJECT_ID]}})
        relations.delete_many({'public_id': {'$in': ALL_RELATION_IDS}})

    _purge()
    groups.update_one({'public_id': USER_GROUP_ID}, {'$set': {'rights': [KEPT_RIGHT]}})
    objects.insert_many([
        {'public_id': PARENT_OBJECT_ID, 'type_id': PARENT_TYPE_ID, 'fields': []},
        {'public_id': CHILD_OBJECT_ID, 'type_id': CHILD_TYPE_ID, 'fields': []},
    ])
    relations.insert_many([
        _relation(STALE_RELATION_ID, CHILD_OBJECT_ID, **{PARENT_TYPE: STALE_TYPE_ID, CHILD_TYPE: STALE_TYPE_ID}),
        _relation(UNSTAMPED_RELATION_ID, CHILD_OBJECT_ID),
        _relation(CORRECT_RELATION_ID, CHILD_OBJECT_ID, **{PARENT_TYPE: PARENT_TYPE_ID, CHILD_TYPE: CHILD_TYPE_ID}),
        _relation(GONE_END_RELATION_ID, GONE_OBJECT_ID, **{PARENT_TYPE: STALE_TYPE_ID, CHILD_TYPE: STALE_TYPE_ID}),
    ])
    yield {'groups': groups, 'relations': relations}
    _purge()
    groups.update_one({'public_id': USER_GROUP_ID}, {'$set': {'rights': stored_rights}})


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261008(database_manager, database_name).start_update()


def _relation_types(collections: dict[str, Any], public_id: int) -> tuple[Any, Any]:
    """The two stored types of one relation"""
    stored = collections['relations'].find_one({'public_id': public_id})

    return stored.get(PARENT_TYPE), stored.get(CHILD_TYPE)


def _snapshot(collections: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    """The user group's rights and every seeded relation, without _id"""
    rights = collections['groups'].find_one({'public_id': USER_GROUP_ID})['rights']
    relations = list(collections['relations'].find({'public_id': {'$in': ALL_RELATION_IDS}}, {'_id': 0})
                     .sort('public_id', 1))

    return rights, relations


class TestTheGrant:
    """The fixed group gains both view rights"""

    def test_both_rights_are_added_and_the_held_ones_kept(self, collections, database_manager,
                                                          database_name) -> None:
        """In addition to what it held"""
        _run(database_manager, database_name)

        assert collections['groups'].find_one({'public_id': USER_GROUP_ID})['rights'] == [KEPT_RIGHT, *GRANTED_RIGHTS]

    def test_a_right_already_held_is_not_added_twice(self, collections, database_manager, database_name) -> None:
        """$addToSet"""
        collections['groups'].update_one({'public_id': USER_GROUP_ID}, {'$set': {'rights': GRANTED_RIGHTS[:1]}})

        _run(database_manager, database_name)

        assert collections['groups'].find_one({'public_id': USER_GROUP_ID})['rights'] == GRANTED_RIGHTS


class TestTheRestamp:
    """Each relation leaves with its objects' live types"""

    @pytest.mark.parametrize('public_id', [STALE_RELATION_ID, UNSTAMPED_RELATION_ID, CORRECT_RELATION_ID],
                             ids=['stale', 'unstamped', 'correct'])
    def test_both_ends_carry_their_objects_type(self, collections, database_manager, database_name,
                                                public_id: int) -> None:
        """Whatever the relation was written with"""
        _run(database_manager, database_name)

        assert _relation_types(collections, public_id) == (PARENT_TYPE_ID, CHILD_TYPE_ID)

    def test_a_deleted_objects_end_keeps_its_stored_type(self, collections, database_manager, database_name) -> None:
        """Only the live end is corrected"""
        _run(database_manager, database_name)

        assert _relation_types(collections, GONE_END_RELATION_ID) == (PARENT_TYPE_ID, STALE_TYPE_ID)

    def test_nothing_else_of_a_relation_changes(self, collections, database_manager, database_name) -> None:
        """Only the two type keys"""
        before = {doc['public_id']: doc for doc in _snapshot(collections)[1]}

        _run(database_manager, database_name)

        for after in _snapshot(collections)[1]:
            untouched = {key: value for key, value in after.items() if key not in (PARENT_TYPE, CHILD_TYPE)}
            assert untouched == {key: value for key, value in before[after['public_id']].items()
                                 if key not in (PARENT_TYPE, CHILD_TYPE)}


def test_a_second_run_changes_nothing(collections, database_manager, database_name) -> None:
    """Re-run safe: the grant adds nothing again and every type already matches"""
    _run(database_manager, database_name)
    after_first = _snapshot(collections)

    _run(database_manager, database_name)

    assert _snapshot(collections) == after_first
