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
Integration tests for cmdb.database.updater.versions.updater_20261121 against a real MongoDB

Every user's one group becomes a one-entry list and ``group_id`` is gone; a missing, null or 0 group becomes the
default group; a user already carrying ``group_ids`` keeps it; every other key stays; a second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261121 import Update20261121
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261121'
USERS: str = 'management.users'
ADMIN_GROUP: int = 1
DEFAULT_GROUP: int = 2
CUSTOM_GROUP: int = 7
SEEDED: list[dict[str, Any]] = [
    {'public_id': 1, 'user_name': 'admin', 'active': True, 'group_id': ADMIN_GROUP},
    {'public_id': 2, 'user_name': 'custom', 'active': False, 'group_id': CUSTOM_GROUP, 'email': 'c@example.org'},
    {'public_id': 3, 'user_name': 'missing', 'active': True},
    {'public_id': 4, 'user_name': 'null', 'active': True, 'group_id': None},
    {'public_id': 5, 'user_name': 'zero', 'active': True, 'group_id': 0},
    {'public_id': 6, 'user_name': 'both', 'active': True, 'group_id': ADMIN_GROUP, 'group_ids': [CUSTOM_GROUP]},
    {'public_id': 7, 'user_name': 'converted', 'active': True, 'group_ids': [ADMIN_GROUP, CUSTOM_GROUP]},
]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A database with the seeded users, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][USERS].insert_many([dict(user) for user in SEEDED])

    yield scratch

    client.drop_database(scratch)


def _users(database_manager: MongoDatabaseManager, scratch: str) -> dict[int, dict[str, Any]]:
    """Every user without its _id"""
    return {user['public_id']: user for user in database_manager.connector.client[scratch][USERS].find({}, {'_id': 0})}


def test_every_user_carries_a_group_list_and_no_single_group(database_manager: MongoDatabaseManager,
                                                             scratch: str) -> None:
    """Twice: the second run changes nothing"""
    for _ in range(2):
        Update20261121(database_manager, scratch).start_update()
        users = _users(database_manager, scratch)

        assert {public_id: user['group_ids'] for public_id, user in users.items()} == {
            1: [ADMIN_GROUP], 2: [CUSTOM_GROUP], 3: [DEFAULT_GROUP], 4: [DEFAULT_GROUP], 5: [DEFAULT_GROUP],
            6: [CUSTOM_GROUP], 7: [ADMIN_GROUP, CUSTOM_GROUP],
        }
        assert all('group_id' not in user for user in users.values())


def test_every_other_key_stays(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Only the group keys change"""
    Update20261121(database_manager, scratch).start_update()

    assert _users(database_manager, scratch)[2] == {
        'public_id': 2, 'user_name': 'custom', 'active': False, 'email': 'c@example.org', 'group_ids': [CUSTOM_GROUP],
    }
