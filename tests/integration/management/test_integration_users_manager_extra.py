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
Integration tests for the query + group-membership surface of UsersManager

Complements test_integration_users_crud.py by pinning the read helpers (``get_user_by``,
``get_many_users``, ``get_user_lookup``) and the group-delete redistribution
(``handle_users_on_group_delete``: MOVE reassigns members, a MOVE with no target raises an update
error, DELETE removes members, an admin member refuses deletion, an empty group is a no-op) against a
real MongoDB. Also covers the manager's error-wrapping (every CRUD path maps an underlying failure to
its typed UsersManager error) by patching the BaseManager primitives to raise.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerUpdateError,
    UsersManagerDeleteError,
    UsersManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_USER_ID: int = 1

SRC_GROUP_ID: int = 9910
DST_GROUP_ID: int = 9911
EMPTY_GROUP_ID: int = 9912

USER_A: int = 9901
USER_B: int = 9902
USER_C: int = 9903
MISSING_USER_ID: int = 9999

USER_A_EMAIL: str = 'user-a@example.com'

ALL_USER_IDS: list[int] = [USER_A, USER_B, USER_C]


def _user_data(public_id: int, group_id: int, email: str | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbUser payload acceptable to ``UsersManager.insert_user``."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'active': True,
        'group_id': group_id,
        'api_level': 0,
        'registration_time': datetime.now(timezone.utc),
        'email': email,
    }


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager) -> UsersManager:
    """Provides a UsersManager wired to the test database."""
    return UsersManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any test users seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_USER_IDS}})

    _purge()
    yield
    _purge()


def _seed(users_manager: UsersManager, public_id: int, group_id: int, email: str | None = None) -> None:
    """Inserts a user directly through the manager."""
    users_manager.insert_user(_user_data(public_id, group_id, email))


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestReadHelpers:
    """get_user_by / get_many_users / get_user_lookup resolve the seeded users."""

    def test_get_user_by_returns_match(self, users_manager: UsersManager) -> None:
        """get_user_by resolves a user through a non-id query field."""
        _seed(users_manager, USER_A, SRC_GROUP_ID, USER_A_EMAIL)

        result = users_manager.get_user_by({'email': USER_A_EMAIL})

        assert isinstance(result, CmdbUser)
        assert result.public_id == USER_A

    def test_get_user_by_returns_none_when_absent(self, users_manager: UsersManager) -> None:
        """get_user_by returns None when nothing matches."""
        assert users_manager.get_user_by({'email': 'nobody@example.com'}) is None

    def test_get_many_users_filters_by_group(self, users_manager: UsersManager) -> None:
        """get_many_users returns every user matching the query."""
        _seed(users_manager, USER_A, SRC_GROUP_ID)
        _seed(users_manager, USER_B, SRC_GROUP_ID)
        _seed(users_manager, USER_C, DST_GROUP_ID)

        result = users_manager.get_many_users({'group_id': SRC_GROUP_ID})

        assert {user.public_id for user in result} == {USER_A, USER_B}

    def test_get_user_lookup_maps_id_to_user(self, users_manager: UsersManager) -> None:
        """get_user_lookup returns a public_id -> CmdbUser mapping for the requested ids."""
        _seed(users_manager, USER_A, SRC_GROUP_ID)
        _seed(users_manager, USER_B, SRC_GROUP_ID)

        lookup = users_manager.get_user_lookup([USER_A, USER_B])

        assert set(lookup) == {USER_A, USER_B}
        assert all(isinstance(user, CmdbUser) for user in lookup.values())


class TestHandleUsersOnGroupDelete:
    """handle_users_on_group_delete redistributes or removes a deleted group's members."""

    def test_move_reassigns_members(self, users_manager: UsersManager) -> None:
        """MOVE reassigns every member of the source group to the target group."""
        _seed(users_manager, USER_A, SRC_GROUP_ID)
        _seed(users_manager, USER_B, SRC_GROUP_ID)

        users_manager.handle_users_on_group_delete(SRC_GROUP_ID, GroupDeleteMode.MOVE, DST_GROUP_ID)

        assert users_manager.get_user(USER_A).group_id == DST_GROUP_ID
        assert users_manager.get_user(USER_B).group_id == DST_GROUP_ID

    def test_move_without_target_raises_update_error(self, users_manager: UsersManager) -> None:
        """A MOVE with no target group raises UsersManagerUpdateError (not a delete error)."""
        _seed(users_manager, USER_A, SRC_GROUP_ID)

        with pytest.raises(UsersManagerUpdateError):
            users_manager.handle_users_on_group_delete(SRC_GROUP_ID, GroupDeleteMode.MOVE, None)

    def test_delete_removes_members(self, users_manager: UsersManager) -> None:
        """DELETE removes every member of the group."""
        _seed(users_manager, USER_A, SRC_GROUP_ID)
        _seed(users_manager, USER_B, SRC_GROUP_ID)

        users_manager.handle_users_on_group_delete(SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

        assert users_manager.get_user(USER_A) is None
        assert users_manager.get_user(USER_B) is None

    def test_delete_refused_when_admin_is_member(
        self,
        users_manager: UsersManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """DELETE refuses (and deletes nothing) when the bootstrap admin is a member of the group."""
        collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        original_admin = collection.find_one({'public_id': ADMIN_USER_ID})
        original_group_id = original_admin['group_id']

        _seed(users_manager, USER_A, SRC_GROUP_ID)
        collection.update_one({'public_id': ADMIN_USER_ID}, {'$set': {'group_id': SRC_GROUP_ID}})
        try:
            with pytest.raises(UsersManagerDeleteError):
                users_manager.handle_users_on_group_delete(SRC_GROUP_ID, GroupDeleteMode.DELETE, None)

            # the guard fires before any deletion, so the member is untouched
            assert users_manager.get_user(USER_A) is not None
        finally:
            collection.update_one({'public_id': ADMIN_USER_ID}, {'$set': {'group_id': original_group_id}})

    def test_empty_group_is_noop(self, users_manager: UsersManager) -> None:
        """A group with no members returns without error."""
        assert users_manager.handle_users_on_group_delete(EMPTY_GROUP_ID, GroupDeleteMode.MOVE, DST_GROUP_ID) is None

    def test_member_lookup_failure_wraps_as_get_error(self, users_manager: UsersManager, monkeypatch) -> None:
        """A failure fetching the group's members surfaces as UsersManagerGetError."""
        monkeypatch.setattr(users_manager, 'get_many_users', _raiser(UsersManagerGetError('boom')))

        with pytest.raises(UsersManagerGetError):
            users_manager.handle_users_on_group_delete(SRC_GROUP_ID, GroupDeleteMode.DELETE, None)


class TestErrorWrapping:
    """Every CRUD path maps an underlying BaseManager failure to its typed UsersManager error."""

    def test_insert_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """insert_user wraps a failure as UsersManagerInsertError."""
        monkeypatch.setattr(users_manager, 'insert', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerInsertError):
            users_manager.insert_user(_user_data(USER_A, SRC_GROUP_ID))

    def test_get_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """get_user wraps a failure as UsersManagerGetError."""
        monkeypatch.setattr(users_manager, 'get_one', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerGetError):
            users_manager.get_user(USER_A)

    def test_get_by_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """get_user_by wraps a failure as UsersManagerGetError."""
        monkeypatch.setattr(users_manager, 'get', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerGetError):
            users_manager.get_user_by({'email': USER_A_EMAIL})

    def test_get_many_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """get_many_users wraps a failure as UsersManagerGetError."""
        monkeypatch.setattr(users_manager, 'get', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerGetError):
            users_manager.get_many_users({'group_id': SRC_GROUP_ID})

    def test_iterate_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """iterate wraps a failure as UsersManagerIterationError."""
        monkeypatch.setattr(users_manager, 'iterate_query',
                            _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerIterationError):
            users_manager.iterate(None)

    def test_update_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """update_user wraps a failure as UsersManagerUpdateError."""
        monkeypatch.setattr(users_manager, 'update', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerUpdateError):
            users_manager.update_user(USER_A, _user_data(USER_A, SRC_GROUP_ID))

    def test_delete_wraps(self, users_manager: UsersManager, monkeypatch) -> None:
        """delete_user wraps a failure as UsersManagerDeleteError."""
        monkeypatch.setattr(users_manager, 'delete', _raiser(RuntimeError('x')))

        with pytest.raises(UsersManagerDeleteError):
            users_manager.delete_user(USER_A)
