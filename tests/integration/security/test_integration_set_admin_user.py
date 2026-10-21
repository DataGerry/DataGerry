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
Integration tests for `cloud_user_helper.set_admin_user` / `retrieve_user` against a real MongoDB

A failed read of the existing user is no longer "no such user": nothing is inserted, so the tenant keeps ONE user
with the email - the old swallow stored a second admin when the portal answered a renamed user_name. A subscription
whose level is no number is the typed insert error before anything is written, and `retrieve_user` lets a stored
user the model cannot read through as the read error instead of answering "not found"
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
from cmdb.interface.cloud_user_helper import retrieve_user, set_admin_user
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 97401
EMAIL: str = 'set-admin@x.io'
BROKEN_EMAIL: str = 'set-admin-broken@x.io'


@pytest.fixture(name='users')
def fixture_users(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """One stored user under EMAIL; yields the collection inside the app's context"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'email': {'$in': [EMAIL, BROKEN_EMAIL]}})
    users.insert_one({'public_id': USER_ID, 'user_name': 'set-admin-old', 'email': EMAIL, 'active': True,
                      'group_id': 1, 'database': database_name, 'registration_time': datetime.now(timezone.utc)})

    with rest_api.application.app_context():
        yield users

    users.delete_many({'email': {'$in': [EMAIL, BROKEN_EMAIL]}})


def _subscription(database_name: str, api_level: Any = 1) -> dict[str, Any]:
    """A subscription of the test tenant"""
    return {'database': database_name, 'api_level': api_level, 'config_item_limit': 5}


def test_a_failed_read_leaves_one_user(users, database_name: str) -> None:
    """The portal renamed the user; the read fails - no second admin is stored"""
    portal: dict[str, Any] = {'email': EMAIL, 'user_name': 'set-admin-renamed', 'password': 'h'}

    with patch.object(UsersManager, 'get_user_by', side_effect=UsersManagerGetError('read failed')):
        with pytest.raises(UsersManagerGetError):
            set_admin_user(portal, _subscription(database_name))

    assert users.count_documents({'email': EMAIL}) == 1


def test_a_successful_sync_updates_the_one_user(users, database_name: str) -> None:
    """The control: the stored user takes the subscription's level, no insert"""
    set_admin_user({'email': EMAIL, 'user_name': 'set-admin-old', 'password': 'h'}, _subscription(database_name, 3))

    assert users.count_documents({'email': EMAIL}) == 1
    assert users.find_one({'email': EMAIL})['api_level'] == 3


def test_a_level_that_is_no_number_writes_nothing(users, database_name: str) -> None:
    """The typed insert error, before any read or write"""
    with pytest.raises(UsersManagerInsertError):
        set_admin_user({'email': EMAIL, 'user_name': 'x', 'password': 'h'}, _subscription(database_name, 'high'))

    assert users.find_one({'email': EMAIL}).get('api_level') is None


def test_an_unreadable_stored_user_is_the_read_error(users, database_name: str) -> None:
    """retrieve_user answered None ("not found") for it"""
    users.insert_one({'public_id': USER_ID + 1, 'email': BROKEN_EMAIL, 'active': True, 'group_id': 1,
                      'registration_time': datetime.now(timezone.utc)})

    with pytest.raises(UsersManagerGetError):
        retrieve_user({'email': BROKEN_EMAIL}, database_name)
