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
Integration tests: the group-delete member redistribution and its undo, on real Mongo

``redistribute_members`` records the inverse of the member move or the member delete in a WriteLedger, and
``WriteLedger.deleted_many`` undoes a batch delete with one read, one insert and one count. Pinned against the
bound collections: the redistribution lands, its undo restores exactly what was read before it - users and settings
under their old ``_id``, a settings row without a public_id included - and a second undo changes nothing more.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import UserSettingsManager, UsersManager
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_helper import redistribute_members
from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 9671
TARGET_GROUP_ID: int = 9672
MEMBER_IDS: list[int] = [9681, 9682]
OUTSIDER_ID: int = 9683
ALL_USER_IDS: list[int] = [*MEMBER_IDS, OUTSIDER_ID]


@pytest.fixture(name='setup')
def fixture_setup(database_manager: MongoDatabaseManager, database_name: str):
    """Two members of the group, an outsider, and two settings rows of the first member (one without public_id)."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        settings.delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    users.insert_many([
        {'public_id': user_id, 'user_name': f'undo-{user_id}', 'active': True, 'password': 'stub',
         'group_id': GROUP_ID if user_id in MEMBER_IDS else TARGET_GROUP_ID,
         'registration_time': datetime(2026, 1, 1, tzinfo=timezone.utc)}
        for user_id in ALL_USER_IDS
    ])
    settings.insert_many([
        {'public_id': 9691, 'resource': 'undo-a', 'user_id': MEMBER_IDS[0], 'payloads': []},
        {'resource': 'undo-b', 'user_id': MEMBER_IDS[0], 'payloads': []},
    ])
    managers = (UsersManager(database_manager), UserSettingsManager(database_manager))
    yield managers, users, settings
    _purge()


def _state(users: Any, settings: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The test users and settings as stored, `_id` included."""
    return (sorted(users.find({'public_id': {'$in': ALL_USER_IDS}}), key=lambda doc: doc['public_id']),
            sorted(settings.find({'user_id': {'$in': ALL_USER_IDS}}), key=lambda doc: doc['resource']))


class TestMove:
    """The member move and its inverse."""

    def test_moves_the_members_and_the_undo_moves_them_back_twice_safely(self, setup) -> None:
        """Only the members move; the undo restores them and a second undo is harmless."""
        managers, users, settings = setup
        before = _state(users, settings)
        ledger = WriteLedger()

        redistribute_members(ledger, managers, GROUP_ID, GroupDeleteMode.MOVE, TARGET_GROUP_ID)

        assert users.count_documents({'public_id': {'$in': ALL_USER_IDS}, 'group_id': TARGET_GROUP_ID}) == 3
        assert not ledger.undo()
        assert _state(users, settings) == before
        assert not ledger.undo()
        assert _state(users, settings) == before


class TestDelete:
    """The member delete, with the settings cascade, and its inverse."""

    def test_deletes_members_and_settings_and_the_undo_restores_them_under_their_ids(self, setup) -> None:
        """Users and both settings rows back, the id-less row too; a second undo inserts nothing."""
        managers, users, settings = setup
        before = _state(users, settings)
        ledger = WriteLedger()

        redistribute_members(ledger, managers, GROUP_ID, GroupDeleteMode.DELETE, None)

        assert [doc['public_id'] for doc in users.find({'public_id': {'$in': ALL_USER_IDS}})] == [OUTSIDER_ID]
        assert settings.count_documents({'user_id': {'$in': ALL_USER_IDS}}) == 0
        assert not ledger.undo()
        assert _state(users, settings) == before
        assert not ledger.undo()
        assert _state(users, settings) == before

    def test_an_undo_before_the_delete_ran_inserts_nothing(self, setup) -> None:
        """Recorded, never run: every snapshot is still stored, so nothing is duplicated."""
        managers, users, settings = setup
        before = _state(users, settings)
        ledger = WriteLedger()
        users_manager, settings_manager = managers
        ledger.deleted_many(users_manager, users_manager.find(criteria={'public_id': {'$in': MEMBER_IDS}},
                                                              projection=None), 'members')
        ledger.deleted_many(settings_manager, settings_manager.find(criteria={'user_id': {'$in': MEMBER_IDS}},
                                                                    projection=None), 'settings')

        assert not ledger.undo()
        assert _state(users, settings) == before
