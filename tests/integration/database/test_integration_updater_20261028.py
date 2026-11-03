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
Integration tests for updater_20261028 against a real MongoDB

The settings of a user that does not exist - one deleted, one pre-seeded for an id no user has yet - are deleted, the
settings of stored users stay, and a second run deletes nothing more. A database without users keeps its settings
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261028 import Update20261028
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_ID: int = 1
DELETED_USER_ID: int = 99281
FUTURE_USER_ID: int = 99282
RESOURCE: str = 'updater-20261028-table'
SCRATCH_SUFFIX: str = '-updater-20261028'


def _setting(user_id: int) -> dict:
    """A stored setting of the user"""
    return {'public_id': user_id, 'user_id': user_id, 'resource': RESOURCE, 'payloads': [], 'setting_type': 'GLOBAL'}


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The administrator's setting and two without their user; removed again afterwards"""
    collection = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)
    collection.delete_many({'resource': RESOURCE})
    collection.insert_many([_setting(ADMIN_ID), _setting(DELETED_USER_ID), _setting(FUTURE_USER_ID)])

    yield collection

    collection.delete_many({'resource': RESOURCE})


def _owners(collection) -> list[int]:
    """The owners of this test's settings"""
    return sorted(document['user_id'] for document in collection.find({'resource': RESOURCE}))


def test_only_the_settings_of_stored_users_stay(settings, database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
    """The deleted user's and the pre-seeded setting go; the administrator's stays"""
    Update20261028(database_manager, database_name).start_update()

    assert _owners(settings) == [ADMIN_ID]


def test_a_second_run_changes_nothing(settings, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-run safe"""
    Update20261028(database_manager, database_name).start_update()
    Update20261028(database_manager, database_name).start_update()

    assert _owners(settings) == [ADMIN_ID]


def test_a_database_without_users_keeps_its_settings(database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
    """Damaged, not ownerless: nothing is deleted"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][CmdbUserSetting.COLLECTION].insert_one(_setting(ADMIN_ID))

    try:
        Update20261028(database_manager, scratch).start_update()

        assert client[scratch][CmdbUserSetting.COLLECTION].count_documents({}) == 1
        assert client[scratch][CmdbUser.COLLECTION].count_documents({}) == 0
    finally:
        client.drop_database(scratch)
