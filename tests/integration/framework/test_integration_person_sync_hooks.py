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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests of ``person_sync.sync_hooks.sync_user_outside_request`` against a real MongoDB

The entry point of an LDAP sign-in and the cloud admin set-up. Pinned: with the sync on the user's person is created,
credited to the user itself; a failed sync writes no person, marks the user ``sync_pending`` and raises nothing; the
next sync that succeeds removes the mark; with the sync off nothing is written and nothing marked
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.person_types.default_person_types import build_default_person_type
from cmdb.framework.person_sync.person_sync_constants import PERSON_SYNC_SETTINGS_SECTION
from cmdb.framework.person_sync.sync_hooks import sync_user_outside_request
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings, write_sync_settings
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE_ID: int = 43201
USER_ID: int = 43211
USER: CmdbUser = CmdbUser(public_id=USER_ID, user_name='it-sync-hook-user', active=True, group_ids=[2],
                          first_name='Ann', last_name='Lee')


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """A PERSON Type, the stored user and the user sync on; all removed afterwards"""
    database = database_manager.connector.client[database_name]
    document = build_default_person_type(SpecialType.PERSON, 'it-sync-hook-person', PERSON_TYPE_ID)
    document['system_type'] = False
    database[CmdbType.COLLECTION].insert_one(document)
    database[CmdbUser.COLLECTION].insert_one(CmdbUser.to_json(USER))
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings(
        users=UserSyncSettings(active=True, default_type_id=PERSON_TYPE_ID)))

    yield database

    database[CmdbObject.COLLECTION].delete_many({'type_id': PERSON_TYPE_ID})
    database[CmdbType.COLLECTION].delete_one({'public_id': PERSON_TYPE_ID})
    database[CmdbUser.COLLECTION].delete_one({'public_id': USER_ID})
    SettingsManager(database_manager, database_name).delete_section(PERSON_SYNC_SETTINGS_SECTION)


def _person(db: Any) -> dict[str, Any] | None:
    """The user's person"""
    return db[CmdbObject.COLLECTION].find_one({'system_ref.kind': 'user', 'system_ref.id': USER_ID})


def _marked(db: Any) -> bool:
    """Whether the user carries the pending mark"""
    return CmdbUserKey.SYNC_PENDING.value in db[CmdbUser.COLLECTION].find_one({'public_id': USER_ID})


def test_the_person_is_created_by_the_user_itself(db: Any, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
    """No mark"""
    sync_user_outside_request(database_manager, database_name, USER)

    assert _person(db)['author_id'] == USER_ID
    assert not _marked(db)


def test_a_failed_sync_marks_the_user_and_raises_nothing(db: Any, database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
    """Then the next one that succeeds removes the mark"""
    db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'active': False}})

    sync_user_outside_request(database_manager, database_name, USER)

    assert (_person(db), _marked(db)) == (None, True)

    db[CmdbType.COLLECTION].update_one({'public_id': PERSON_TYPE_ID}, {'$set': {'active': True}})
    sync_user_outside_request(database_manager, database_name, USER)

    assert _person(db) is not None and not _marked(db)


def test_with_the_sync_off_nothing_happens(db: Any, database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
    """No person, no mark"""
    write_sync_settings(SettingsManager(database_manager, database_name), PersonSyncSettings())

    sync_user_outside_request(database_manager, database_name, USER)

    assert (_person(db), _marked(db)) == (None, False)
