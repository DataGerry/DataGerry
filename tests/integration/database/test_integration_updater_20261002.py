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
Integration tests for cmdb.database.updater.versions.updater_20261002 against a real MongoDB

Seeds CmdbUserGroups with every kind of ``rights`` a database written before the item rule may hold, runs the
migration, and asserts:

  - each group keeps exactly its known right names, in their stored order; a clean group is not rewritten
  - a group that could not be read before (an unhashable entry) reads again, with its rights resolved
  - a non-list ``rights`` becomes an empty list, a null one is left alone
  - the version is bumped, and a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261002 import Update20261002
from cmdb.manager.groups_manager import GroupsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

KNOWN_RIGHT: str = 'base.framework.object.view'
OTHER_KNOWN_RIGHT: str = 'base.framework.type.*'
UNKNOWN_RIGHT: str = 'base.no-such-right'

UNHASHABLE_GROUP_ID: int = 96801
UNKNOWN_NAME_GROUP_ID: int = 96802
NUMBER_GROUP_ID: int = 96803
NOT_A_LIST_GROUP_ID: int = 96804
NULL_GROUP_ID: int = 96805
CLEAN_GROUP_ID: int = 96806

# public_id -> the stored rights
STORED_RIGHTS: dict[int, Any] = {
    UNHASHABLE_GROUP_ID: [{}, KNOWN_RIGHT],
    UNKNOWN_NAME_GROUP_ID: [OTHER_KNOWN_RIGHT, UNKNOWN_RIGHT, KNOWN_RIGHT],
    NUMBER_GROUP_ID: [1, None, [KNOWN_RIGHT]],
    NOT_A_LIST_GROUP_ID: KNOWN_RIGHT,
    NULL_GROUP_ID: None,
    CLEAN_GROUP_ID: [KNOWN_RIGHT, OTHER_KNOWN_RIGHT],
}

# public_id -> what the migration leaves stored
EXPECTED_RIGHTS: dict[int, Any] = {
    UNHASHABLE_GROUP_ID: [KNOWN_RIGHT],
    UNKNOWN_NAME_GROUP_ID: [OTHER_KNOWN_RIGHT, KNOWN_RIGHT],
    NUMBER_GROUP_ID: [],
    NOT_A_LIST_GROUP_ID: [],
    NULL_GROUP_ID: None,
    CLEAN_GROUP_ID: [KNOWN_RIGHT, OTHER_KNOWN_RIGHT],
}

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'
CREATION_DATE: int = 20261002


def _group_doc(public_id: int, rights: Any) -> dict[str, Any]:
    """A minimal CmdbUserGroup document carrying the given rights value"""
    return {'public_id': public_id, 'name': f'grp-{public_id}', 'label': f'Group {public_id}', 'rights': rights}


def _stored(groups, public_id: int) -> Any:
    """The stored rights value of a seeded group"""
    return groups.find_one({'public_id': public_id})['rights']


@pytest.fixture(name='groups')
def fixture_groups(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the groups + preserves the updater setting, restoring everything afterwards"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    groups.delete_many({'public_id': {'$in': list(STORED_RIGHTS)}})
    groups.insert_many([_group_doc(public_id, rights) for public_id, rights in STORED_RIGHTS.items()])

    yield groups

    groups.delete_many({'public_id': {'$in': list(STORED_RIGHTS)}})
    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


class TestUpdater20261002:
    """The migration keeps only known right names in every group and bumps the version"""

    @pytest.mark.parametrize('public_id', list(STORED_RIGHTS))
    def test_each_group_keeps_its_known_names(
        self, groups, database_manager: MongoDatabaseManager, database_name: str, public_id: int,
    ) -> None:
        """Every seeded shape ends in the expected stored value"""
        Update20261002(database_manager, database_name).start_update()

        assert _stored(groups, public_id) == EXPECTED_RIGHTS[public_id]

    def test_an_unreadable_group_reads_again(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A group whose unhashable entry failed every read resolves its rights after the repair"""
        del groups
        groups_manager = GroupsManager(database_manager, database_name)

        with pytest.raises(GroupsManagerGetError):
            groups_manager.get_group(UNHASHABLE_GROUP_ID)

        Update20261002(database_manager, database_name).start_update()

        repaired: CmdbUserGroup = groups_manager.get_group(UNHASHABLE_GROUP_ID)
        assert [right.name for right in repaired.rights] == [KNOWN_RIGHT]
        assert repaired.has_right(KNOWN_RIGHT)

    def test_version_bumped(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The persisted updater version records the migration"""
        del groups
        Update20261002(database_manager, database_name).start_update()

        settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
        assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == CREATION_DATE

    def test_second_run_changes_nothing(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After one run nothing is selected any more, so the stored documents stay as the first run left them"""
        Update20261002(database_manager, database_name).start_update()
        after_first: list[dict[str, Any]] = list(groups.find({'public_id': {'$in': list(STORED_RIGHTS)}}))

        Update20261002(database_manager, database_name).start_update()
        after_second: list[dict[str, Any]] = list(groups.find({'public_id': {'$in': list(STORED_RIGHTS)}}))

        assert after_second == after_first
        assert {doc['public_id']: doc['rights'] for doc in after_second} == EXPECTED_RIGHTS
