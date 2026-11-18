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
Integration tests of a CmdbUser's group list against a real MongoDB

Pinned: a member query matches a user in any position of its list; a MOVE swaps only the deleted group and keeps a
member's other groups - a member already in the target keeps it once, the list stays sorted; the snapshot read before
the move and written back restores every list exactly; the model declares a non-unique group_ids index
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser, CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #

SOURCE_GROUP: int = 9920
TARGET_GROUP: int = 9921
KEPT_GROUP: int = 9922
LOW_GROUP: int = 9919

ONLY_SOURCE: int = 9931
SOURCE_AND_KEPT: int = 9932
SOURCE_AND_TARGET: int = 9933
NOT_A_MEMBER: int = 9934
ALL_IDS: list[int] = [ONLY_SOURCE, SOURCE_AND_KEPT, SOURCE_AND_TARGET, NOT_A_MEMBER]

SEEDED_LISTS: dict[int, list[int]] = {
    ONLY_SOURCE: [SOURCE_GROUP],
    SOURCE_AND_KEPT: [LOW_GROUP, SOURCE_GROUP, KEPT_GROUP],
    SOURCE_AND_TARGET: [SOURCE_GROUP, TARGET_GROUP],
    NOT_A_MEMBER: [KEPT_GROUP],
}
KEY: str = CmdbUserKey.GROUP_IDS.value
SCRATCH_SUFFIX: str = '-user-group-ids'


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[UsersManager]:
    """A UsersManager with the seeded users, removed before and after"""
    manager = UsersManager(database_manager, database_name)
    collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    collection.delete_many({CmdbUserKey.PUBLIC_ID.value: {'$in': ALL_IDS}})

    for public_id, group_ids in SEEDED_LISTS.items():
        manager.insert_user(CmdbUser(public_id=public_id, user_name=f'group-list-{public_id}', active=True,
                                     group_ids=group_ids, registration_time=datetime.now(timezone.utc)))

    yield manager

    collection.delete_many({CmdbUserKey.PUBLIC_ID.value: {'$in': ALL_IDS}})


def _lists(users_manager: UsersManager) -> dict[int, list[int]]:
    """Every seeded user's stored list"""
    return users_manager.get_group_ids_of(ALL_IDS)


def test_a_member_is_found_in_any_position(users_manager: UsersManager) -> None:
    """The members of the source group, whether it is their only, middle or first group"""
    assert sorted(users_manager.get_group_member_ids(SOURCE_GROUP)) == [ONLY_SOURCE, SOURCE_AND_KEPT, SOURCE_AND_TARGET]
    assert users_manager.has_group_members(KEPT_GROUP)


def test_a_move_swaps_only_the_source_group(users_manager: UsersManager) -> None:
    """Other groups stay, the target is held once, the lists stay sorted, a non-member is untouched"""
    members: list[int] = users_manager.get_group_member_ids(SOURCE_GROUP)

    users_manager.move_users(members, SOURCE_GROUP, TARGET_GROUP)

    assert _lists(users_manager) == {
        ONLY_SOURCE: [TARGET_GROUP],
        SOURCE_AND_KEPT: [LOW_GROUP, TARGET_GROUP, KEPT_GROUP],
        SOURCE_AND_TARGET: [TARGET_GROUP],
        NOT_A_MEMBER: [KEPT_GROUP],
    }


def test_the_snapshot_restores_every_list_exactly(users_manager: UsersManager) -> None:
    """Read before the move, written back after it - also for the member who already held the target"""
    members: list[int] = users_manager.get_group_member_ids(SOURCE_GROUP)
    snapshot: dict[int, list[int]] = users_manager.get_group_ids_of(members)

    users_manager.move_users(members, SOURCE_GROUP, TARGET_GROUP)
    users_manager.restore_group_ids(snapshot)

    assert _lists(users_manager) == SEEDED_LISTS


def test_the_declared_indexes_include_the_group_ids_index(database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
    """Created from the model's declaration in a scratch database: a non-unique index on group_ids"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)

    try:
        database_manager.create_indexes(CmdbUser.COLLECTION, scratch, CmdbUser.get_index_keys())
        index: dict[str, Any] = client[scratch][CmdbUser.COLLECTION].index_information()[KEY]
    finally:
        client.drop_database(scratch)

    assert index['key'] == [(KEY, 1)] and not index.get('unique', False)
