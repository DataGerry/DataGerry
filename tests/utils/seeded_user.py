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
Seeds users and user groups for route tests

A route test that needs a caller other than the administrator account - a member of another group, or a second
member of the admin group - writes the user with ``seeded_user`` and has it removed afterwards, so the session's users
stay as seeded. A test that routes the managers to a scratch database copies the session's user groups into it with
``copy_user_groups``: a route's right check reads the caller's group from the caller's tenant database
"""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

# The key a user document is found by
PUBLIC_ID_KEY: str = 'public_id'
# Left out of a copied document, so the copy gets its own
MONGO_ID_KEY: str = '_id'


@contextmanager
def seeded_user(database_manager: MongoDatabaseManager, database_name: str, public_id: int, user_name: str,
                group_id: int) -> Iterator[CmdbUser]:
    """
    Writes an active user of a group, yields it, and deletes it again

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
        public_id (int): The user's id - one no other test seeds
        user_name (str): The user's name
        group_id (int): The group the user is a member of

    Yields:
        CmdbUser: The user, as the request user of a test request
    """
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({PUBLIC_ID_KEY: public_id})
    users.insert_one({PUBLIC_ID_KEY: public_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
                      'registration_time': datetime.now(timezone.utc)})

    try:
        yield CmdbUser(public_id=public_id, user_name=user_name, active=True, group_id=group_id)
    finally:
        users.delete_many({PUBLIC_ID_KEY: public_id})


def copy_user_groups(database_manager: MongoDatabaseManager, source: str, target: str) -> None:
    """
    Copies every user group of one database into another, ids and rights as stored

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        source (str): The database holding the groups - the session's test database
        target (str): The scratch database the managers are routed to
    """
    groups = list(database_manager.get_collection(CmdbUserGroup.COLLECTION, source).find({}, {MONGO_ID_KEY: 0}))
    database_manager.get_collection(CmdbUserGroup.COLLECTION, target).insert_many(groups)
