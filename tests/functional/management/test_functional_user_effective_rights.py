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
Functional tests: the rights of a user in several groups, as the login answer and `GET /users/<id>/rights` give them

A user in two groups holds the union of their rights. Pinned through the real app:

  - `POST /auth/login` answers `effective_rights` - every right of both groups, each once, in a group's right shape
  - `GET /users/<id>/rights` answers the same union with the groups it came from: for a holder of
    `base.user-management.user.view`, and for the user's own record without that right; another user's record
    without the right is a **403**, an unknown user a **404**, a group that is gone adds nothing, a group read that
    fails is a **500**
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.responses.login_response import EFFECTIVE_RIGHTS_KEY
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    USER_GROUPS_NOT_READABLE_MESSAGE,
    UserRightsKey,
)
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
USERS_URL: str = '/users'

VIEWER_GROUP_ID: int = 94471
EDITOR_GROUP_ID: int = 94472
GONE_GROUP_ID: int = 94479
GROUP_IDS: list[int] = [VIEWER_GROUP_ID, EDITOR_GROUP_ID]
UNKNOWN_USER_ID: int = 94489

USER_NAME: str = 'effective-rights-user'
OTHER_USER_NAME: str = 'effective-rights-other'
PASSWORD: str = 'effective-secret'

VIEWER_RIGHTS: list[str] = [TypeRight.VIEW.value, ObjectRightName.VIEW.value]
EDITOR_RIGHTS: list[str] = [ObjectRightName.VIEW.value, ObjectRightName.EDIT.value]
UNION: list[str] = sorted(set(VIEWER_RIGHTS) | set(EDITOR_RIGHTS))


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str) -> Any:
    """The two groups (neither holds user.view); the test users removed before and after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': GROUP_IDS}})
        users.delete_many({'user_name': {'$in': [USER_NAME, OTHER_USER_NAME]}})

    _purge()
    groups.insert_many([
        {'public_id': VIEWER_GROUP_ID, 'name': 'effective-viewers', 'label': 'Viewers', 'rights': VIEWER_RIGHTS},
        {'public_id': EDITOR_GROUP_ID, 'name': 'effective-editors', 'label': 'Editors', 'rights': EDITOR_RIGHTS},
    ])

    yield users

    _purge()


def _create(rest_api: Any, user_name: str, group_ids: list[int]) -> CmdbUser:
    """Creates a local user through the route - so the password is stored as the login checks it"""
    body: dict[str, Any] = {'user_name': user_name, 'password': PASSWORD, 'active': True, 'group_ids': group_ids}
    response = rest_api.post(f'{USERS_URL}/', json=body)
    assert response.status_code == HTTPStatus.CREATED

    return CmdbUser(public_id=response.get_json()['result_id'], user_name=user_name, active=True, group_ids=group_ids)


def _names(rights: list[dict[str, Any]]) -> list[str]:
    """The right names of an answered right list"""
    return [right['name'] for right in rights]


def _rights(rest_api: Any, public_id: int, **user: Any) -> Any:
    """GET /users/<id>/rights"""
    return rest_api.get(f'{USERS_URL}/{public_id}/rights', **user)


class TestTheLoginAnswer:
    """POST /auth/login"""

    def test_a_user_in_two_groups_gets_their_union(self, rest_api, users) -> None:
        """Each right once, sorted by name, in a group's right shape"""
        del users  # the fixture only has to have run
        _create(rest_api, USER_NAME, GROUP_IDS)

        response = rest_api.post(LOGIN_URL, json={'user_name': USER_NAME, 'password': PASSWORD}, unauthorized=True)

        assert response.status_code == HTTPStatus.OK
        rights: list[dict[str, Any]] = response.get_json()[EFFECTIVE_RIGHTS_KEY]
        assert _names(rights) == UNION
        assert set(rights[0]) == {'name', 'label', 'description', 'is_master'}

    def test_the_administrator_gets_the_wildcard(self, rest_api) -> None:
        """A wildcard right stays a wildcard - the client widens it"""
        response = rest_api.post(LOGIN_URL, json={'user_name': 'admin', 'password': 'admin'}, unauthorized=True)

        assert 'base.*' in _names(response.get_json()[EFFECTIVE_RIGHTS_KEY])


class TestTheRightsRoute:
    """GET /users/<id>/rights"""

    def test_a_user_view_holder_reads_another_users_union(self, rest_api, users) -> None:
        """The administrator's client: the union and the groups it came from"""
        del users
        user: CmdbUser = _create(rest_api, USER_NAME, GROUP_IDS)

        response = _rights(rest_api, user.public_id)

        assert response.status_code == HTTPStatus.OK
        result: dict[str, Any] = response.get_json()['result']
        assert result[UserRightsKey.PUBLIC_ID.value] == user.public_id
        assert result[UserRightsKey.GROUP_IDS.value] == GROUP_IDS
        assert _names(result[UserRightsKey.RIGHTS.value]) == UNION

    def test_a_user_reads_their_own_rights_without_the_right(self, rest_api, users) -> None:
        """The own-record carve-out, as on GET /users/<id>"""
        del users
        user: CmdbUser = _create(rest_api, USER_NAME, GROUP_IDS)

        assert _rights(rest_api, user.public_id, user=user).status_code == HTTPStatus.OK

    def test_another_users_rights_need_the_right(self, rest_api, users) -> None:
        """403 for a caller without base.user-management.user.view"""
        del users
        user: CmdbUser = _create(rest_api, USER_NAME, GROUP_IDS)
        other: CmdbUser = _create(rest_api, OTHER_USER_NAME, [VIEWER_GROUP_ID])

        assert _rights(rest_api, other.public_id, user=user).status_code == HTTPStatus.FORBIDDEN

    def test_an_unknown_user_is_a_404(self, rest_api) -> None:
        """Nothing to read the groups of"""
        assert _rights(rest_api, UNKNOWN_USER_ID).status_code == HTTPStatus.NOT_FOUND

    def test_a_group_that_is_gone_adds_nothing(self, rest_api, users) -> None:
        """A stored list naming a deleted group: the rights of the others, the gone id not among the groups"""
        user: CmdbUser = _create(rest_api, USER_NAME, [VIEWER_GROUP_ID])
        users.update_one({'public_id': user.public_id}, {'$set': {'group_ids': [VIEWER_GROUP_ID, GONE_GROUP_ID]}})

        result: dict[str, Any] = _rights(rest_api, user.public_id).get_json()['result']

        assert result[UserRightsKey.GROUP_IDS.value] == [VIEWER_GROUP_ID]
        assert _names(result[UserRightsKey.RIGHTS.value]) == sorted(VIEWER_RIGHTS)

    def test_a_group_read_that_fails_is_a_500(self, rest_api, users, monkeypatch: pytest.MonkeyPatch) -> None:
        """The server's fault, with its message - asked after the caller's own groups were read"""
        del users
        user: CmdbUser = _create(rest_api, USER_NAME, GROUP_IDS)
        real_get_groups = GroupsManager.get_groups

        def _get_groups(manager: GroupsManager, public_ids: list[int]) -> list[CmdbUserGroup]:
            if public_ids == GROUP_IDS:
                raise GroupsManagerGetError('unreadable')

            return real_get_groups(manager, public_ids)

        monkeypatch.setattr(GroupsManager, 'get_groups', _get_groups)

        response = _rights(rest_api, user.public_id)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == USER_GROUPS_NOT_READABLE_MESSAGE.format(public_id=user.public_id)
