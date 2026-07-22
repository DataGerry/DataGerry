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
Integration tests for the CmdbUser CRUD surface of UsersManager

Pins the manager-layer behavior against a real MongoDB instance: insert returns the
new public_id and persists the doc, get_user resolves both present and missing ids,
update overwrites the existing payload, delete returns True and removes the doc,
and the admin-protection guard refuses to delete public_id=1
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager.users_manager import UsersManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_USER_ID: int = 1
DEFAULT_GROUP_ID: int = 1
DEFAULT_API_LEVEL: int = 0

USER_ID_FOR_GET: int = 9801
USER_ID_FOR_UPDATE: int = 9802
USER_ID_FOR_DELETE: int = 9803
USER_ID_FOR_INSERT: int = 9804
MISSING_USER_ID: int = 9899

SEED_USER_IDS: list[int] = [
    USER_ID_FOR_GET,
    USER_ID_FOR_UPDATE,
    USER_ID_FOR_DELETE,
    USER_ID_FOR_INSERT,
]

ORIGINAL_FIRST_NAME: str = 'Original'
UPDATED_FIRST_NAME: str = 'Updated'


def _user_data(public_id: int, first_name: str = ORIGINAL_FIRST_NAME) -> dict[str, Any]:
    """Builds a minimal CmdbUser payload acceptable to ``UsersManager.insert_user``."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'active': True,
        'group_id': DEFAULT_GROUP_ID,
        'api_level': DEFAULT_API_LEVEL,
        'registration_time': datetime.now(timezone.utc),
        'first_name': first_name,
        'password': 'hashed-stub',
    }


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded_users(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed CmdbUser docs after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': SEED_USER_IDS}})


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager) -> UsersManager:
    """Provides a UsersManager wired to the test database."""
    return UsersManager(database_manager)


def _delete_user_by_id(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one CmdbUser doc directly via the collection, used for per-test cleanup."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertUser:
    """``UsersManager.insert_user`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        users_manager: UsersManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id of the new doc and a follow-up find sees the persisted row."""
        try:
            returned_id = users_manager.insert_user(_user_data(USER_ID_FOR_INSERT))

            assert returned_id == USER_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
                .find_one({'public_id': USER_ID_FOR_INSERT})
            assert stored is not None
            assert stored['user_name'] == f'user-{USER_ID_FOR_INSERT}'
        finally:
            _delete_user_by_id(database_manager, database_name, USER_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetUser:
    """``UsersManager.get_user`` returns a CmdbUser by id, or None when missing."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        users_manager: UsersManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single user before each test in this class and removes it after."""
        users_manager.insert_user(_user_data(USER_ID_FOR_GET))
        yield
        _delete_user_by_id(database_manager, database_name, USER_ID_FOR_GET)

    def test_returns_cmdb_user_instance(self, users_manager: UsersManager) -> None:
        """A present user is returned as a ``CmdbUser`` instance with the expected public_id."""
        result = users_manager.get_user(USER_ID_FOR_GET)

        assert isinstance(result, CmdbUser)
        assert result.public_id == USER_ID_FOR_GET

    def test_returns_none_for_missing_id(self, users_manager: UsersManager) -> None:
        """A missing id returns None rather than raising."""
        assert users_manager.get_user(MISSING_USER_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateUser:
    """``UsersManager.update_user`` writes the new payload over the existing doc."""

    def test_persists_new_first_name(
        self,
        users_manager: UsersManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing user replaces the stored first_name."""
        try:
            users_manager.insert_user(_user_data(USER_ID_FOR_UPDATE))

            users_manager.update_user(USER_ID_FOR_UPDATE, _user_data(USER_ID_FOR_UPDATE, UPDATED_FIRST_NAME))

            stored = users_manager.get_user(USER_ID_FOR_UPDATE)
            assert stored is not None
            assert stored.first_name == UPDATED_FIRST_NAME
        finally:
            _delete_user_by_id(database_manager, database_name, USER_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteUser:
    """``UsersManager.delete_user`` removes a regular user and refuses to delete the admin."""

    def test_returns_true_and_removes_doc(
        self,
        users_manager: UsersManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing user returns True and a follow-up get returns None."""
        users_manager.insert_user(_user_data(USER_ID_FOR_DELETE))

        deleted = users_manager.delete_user(USER_ID_FOR_DELETE)

        assert deleted is True
        assert users_manager.get_user(USER_ID_FOR_DELETE) is None
        # belt-and-braces cleanup
        _delete_user_by_id(database_manager, database_name, USER_ID_FOR_DELETE)

    def test_admin_user_is_protected(self, users_manager: UsersManager) -> None:
        """Attempting to delete public_id=1 raises ``UsersManagerDeleteError`` (bootstrap admin)."""
        with pytest.raises(UsersManagerDeleteError):
            users_manager.delete_user(ADMIN_USER_ID)

        # The admin must still be present after the failed call.
        assert users_manager.get_user(ADMIN_USER_ID) is not None
