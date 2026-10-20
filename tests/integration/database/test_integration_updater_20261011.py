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
Integration tests for cmdb.database.updater.versions.updater_20261011 against a real MongoDB

Seeds users and groups with padded names (one whose stripped name is free, one whose stripped name is taken), a
blank name, a name with a control character inside and a clean name, builds both unique indexes, runs the migration,
and asserts:

  - a padded name whose stripped form is free is stripped; nothing else of the document changes
  - a padded name whose stripped form is taken, a blank name and a control character inside stay as they are
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261011 import Update20261011
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #

USER_NAME: str = CmdbUserKey.USER_NAME.value
GROUP_NAME: str = GroupKey.NAME.value

PADDED_USER_ID: int = 98611
TAKEN_PADDED_USER_ID: int = 98612
TAKEN_USER_ID: int = 98613
BLANK_USER_ID: int = 98614
CONTROL_USER_ID: int = 98615
CLEAN_USER_ID: int = 98616
PADDED_GROUP_ID: int = 98621
TAKEN_PADDED_GROUP_ID: int = 98622
TAKEN_GROUP_ID: int = 98623
EMPTY_GROUP_ID: int = 98624

REPAIRED_USER_NAME: str = 'upd-padded-user'
REPAIRED_GROUP_NAME: str = 'upd-padded-group'

# public_id -> stored name, and what the run leaves
USER_NAMES: dict[int, str] = {
    PADDED_USER_ID: f' {REPAIRED_USER_NAME} ',
    TAKEN_PADDED_USER_ID: 'upd-taken-user ',
    TAKEN_USER_ID: 'upd-taken-user',
    BLANK_USER_ID: '   ',
    CONTROL_USER_ID: 'upd\tcontrol',
    CLEAN_USER_ID: 'upd clean user',
}
EXPECTED_USER_NAMES: dict[int, str] = {**USER_NAMES, PADDED_USER_ID: REPAIRED_USER_NAME}

GROUP_NAMES: dict[int, str] = {
    PADDED_GROUP_ID: f'\u00a0{REPAIRED_GROUP_NAME}',
    TAKEN_PADDED_GROUP_ID: ' upd-taken-group',
    TAKEN_GROUP_ID: 'upd-taken-group',
    EMPTY_GROUP_ID: '',
}
EXPECTED_GROUP_NAMES: dict[int, str] = {**GROUP_NAMES, PADDED_GROUP_ID: REPAIRED_GROUP_NAME}

# The documents the run leaves for an administrator - each one logged
LEFT_IDS: list[int] = [TAKEN_PADDED_USER_ID, BLANK_USER_ID, CONTROL_USER_ID, TAKEN_PADDED_GROUP_ID, EMPTY_GROUP_ID]


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded users and groups behind both unique indexes - purged after"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    database_manager.create_indexes(CmdbUser.COLLECTION, database_name, CmdbUser.get_index_keys())
    database_manager.create_indexes(CmdbUserGroup.COLLECTION, database_name, CmdbUserGroup.get_index_keys())

    def _purge() -> None:
        users.delete_many({'public_id': {'$in': list(USER_NAMES)}})
        groups.delete_many({'public_id': {'$in': list(GROUP_NAMES)}})

    _purge()
    users.insert_many([{'public_id': public_id, USER_NAME: name, 'active': True, 'group_id': 2}
                       for public_id, name in USER_NAMES.items()])
    groups.insert_many([{'public_id': public_id, GROUP_NAME: name, 'label': f'Group {public_id}', 'rights': []}
                        for public_id, name in GROUP_NAMES.items()])
    yield {'users': users, 'groups': groups}
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261011(database_manager, database_name).start_update()


def _names(collection: Any, field: str, public_ids: dict[int, str]) -> dict[int, str]:
    """The stored name of each seeded document"""
    return {stored['public_id']: stored[field] for stored in collection.find({'public_id': {'$in': list(public_ids)}})}


def test_only_a_padded_name_with_a_free_stripped_form_is_stripped(collections, database_manager,
                                                                   database_name) -> None:
    """Taken, blank and control-character names stay for an administrator"""
    _run(database_manager, database_name)

    assert _names(collections['users'], USER_NAME, USER_NAMES) == EXPECTED_USER_NAMES
    assert _names(collections['groups'], GROUP_NAME, GROUP_NAMES) == EXPECTED_GROUP_NAMES


def test_nothing_else_of_a_repaired_document_changes(collections, database_manager, database_name) -> None:
    """Only the name"""
    before = collections['groups'].find_one({'public_id': PADDED_GROUP_ID}, {'_id': 0})

    _run(database_manager, database_name)

    after = collections['groups'].find_one({'public_id': PADDED_GROUP_ID}, {'_id': 0})
    assert after == {**before, GROUP_NAME: REPAIRED_GROUP_NAME}


def test_a_left_name_is_logged_by_collection_and_id(database_manager, database_name,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    """The administrator's worklist"""
    _run(database_manager, database_name)

    for public_id in LEFT_IDS:
        assert str(public_id) in caplog.text


def test_a_second_run_changes_nothing(collections, database_manager, database_name) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    first = (_names(collections['users'], USER_NAME, USER_NAMES), _names(collections['groups'], GROUP_NAME,
                                                                          GROUP_NAMES))

    _run(database_manager, database_name)

    assert (_names(collections['users'], USER_NAME, USER_NAMES),
            _names(collections['groups'], GROUP_NAME, GROUP_NAMES)) == first
