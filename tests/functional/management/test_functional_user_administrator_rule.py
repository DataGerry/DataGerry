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
Functional tests: the user rights manage users - they do not make the caller an administrator

A "delegate" holds every user-management right except membership of the administrator group. Pinned:

  - the delegate cannot create an administrator, move anyone (themselves included) into the administrator group,
    change an administrator's administrative field or password, delete an administrator, or move a deleted group's
    members into the administrator group - each a **403**, with nothing written
  - the delegate still manages ordinary users, and may still change an administrator's profile fields
  - an administrator may do all of it
  - the administrator group never loses its last active member - **400**
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.group_model import ADMIN_GROUP_ID, USER_GROUP_ID, CmdbUserGroup, GroupDeleteMode
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'
GROUPS_URL: str = '/groups'

DELEGATE_GROUP_ID: int = 93960
DELEGATE_ID: int = 93961
OTHER_ADMIN_ID: int = 93962
ORDINARY_ID: int = 93963
DOOMED_GROUP_ID: int = 93964
DOOMED_MEMBER_ID: int = 93965

# Every user a create test writes carries this name prefix, so it can be purged without knowing its id
CREATED_NAME_PREFIX: str = 'admin-rule-created-'
NEW_PASSWORD: str = 'a-new-password'

DELEGATE_RIGHTS: list[str] = [
    'base.user-management.user.view',
    'base.user-management.user.add',
    'base.user-management.user.edit',
    'base.user-management.user.delete',
    'base.user-management.group.view',
    'base.user-management.group.delete',
]
SEEDED_USER_IDS: list[int] = [DELEGATE_ID, OTHER_ADMIN_ID, ORDINARY_ID, DOOMED_MEMBER_ID]


def _user(public_id: int, group_id: int, user_name: str) -> dict[str, Any]:
    """A stored, active CmdbUser document"""
    return {'public_id': public_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
            'first_name': 'First', 'password': 'stored-digest', 'authenticator': 'LocalAuthenticationProvider',
            'registration_time': datetime.now(timezone.utc)}


@pytest.fixture(name='users', autouse=True)
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """The delegate's group and user, a second administrator, an ordinary user, and a group about to be deleted"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        users.delete_many({'$or': [{'public_id': {'$in': SEEDED_USER_IDS}},
                                   {'user_name': {'$regex': f'^{CREATED_NAME_PREFIX}'}}]})
        groups.delete_many({'public_id': {'$in': [DELEGATE_GROUP_ID, DOOMED_GROUP_ID]}})

    _purge()
    groups.insert_many([
        {'public_id': DELEGATE_GROUP_ID, 'name': 'admin-rule-delegates', 'label': 'Delegates',
         'rights': DELEGATE_RIGHTS},
        {'public_id': DOOMED_GROUP_ID, 'name': 'admin-rule-doomed', 'label': 'Doomed', 'rights': []},
    ])
    users.insert_many([
        _user(DELEGATE_ID, DELEGATE_GROUP_ID, 'admin-rule-delegate'),
        _user(OTHER_ADMIN_ID, ADMIN_GROUP_ID, 'admin-rule-other-admin'),
        _user(ORDINARY_ID, USER_GROUP_ID, 'admin-rule-ordinary'),
        _user(DOOMED_MEMBER_ID, DOOMED_GROUP_ID, 'admin-rule-doomed-member'),
    ])
    yield users
    _purge()


@pytest.fixture(name='delegate')
def fixture_delegate() -> CmdbUser:
    """The caller holding every user right, outside the administrator group"""
    return CmdbUser(public_id=DELEGATE_ID, user_name='admin-rule-delegate', active=True, group_id=DELEGATE_GROUP_ID)


def _stored(users: Any, public_id: int) -> dict[str, Any]:
    """A stored user without MongoDB's id"""
    return users.find_one({'public_id': public_id}, {'_id': 0})


def _body(rest_api, public_id: int, **changes: Any) -> dict[str, Any]:
    """The user as the API answers it - what the edit screen sends back - with the given changes"""
    body: dict[str, Any] = rest_api.get(f'{USERS_URL}/{public_id}').get_json()['result']

    return {**body, **changes}


def _new_user(group_id: int, suffix: str) -> dict[str, Any]:
    """A create body"""
    return {'user_name': f'{CREATED_NAME_PREFIX}{suffix}', 'password': NEW_PASSWORD, 'group_id': group_id,
            'active': True}


class TestTheDelegateCannotMakeAnAdministrator:
    """Every way into the administrator group is closed to a non-administrator."""

    def test_creating_an_administrator_is_refused(self, rest_api, users, delegate: CmdbUser) -> None:
        """403, and no user stored"""
        response = rest_api.post(f'{USERS_URL}/', json=_new_user(ADMIN_GROUP_ID, 'admin'), user=delegate)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == 'Only an administrator may assign the administrator group!'
        assert users.count_documents({'user_name': f'{CREATED_NAME_PREFIX}admin'}) == 0

    @pytest.mark.parametrize('target_id', [DELEGATE_ID, ORDINARY_ID], ids=['self', 'another user'])
    def test_moving_a_user_into_the_administrator_group_is_refused(self, rest_api, users, delegate: CmdbUser,
                                                                   target_id: int) -> None:
        """Self-promotion and promoting someone else: 403, the stored user unchanged"""
        before = _stored(users, target_id)

        response = rest_api.put(f'{USERS_URL}/{target_id}', json=_body(rest_api, target_id, group_id=ADMIN_GROUP_ID),
                                user=delegate)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(users, target_id) == before

    def test_moving_a_deleted_groups_members_into_the_administrator_group_is_refused(
            self, rest_api, users, delegate: CmdbUser) -> None:
        """The group delete's MOVE: 403 before anything is written - the group and its member are as they were"""
        response = rest_api.delete(f'{GROUPS_URL}/{DOOMED_GROUP_ID}', user=delegate,
                                   query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': ADMIN_GROUP_ID})

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(users, DOOMED_MEMBER_ID)['group_id'] == DOOMED_GROUP_ID


class TestTheDelegateCannotChangeAnAdministrator:
    """An administrator's administrative fields, password and existence are an administrator's business."""

    @pytest.mark.parametrize('changes', [
        {'active': False}, {'group_id': USER_GROUP_ID}, {'user_name': 'admin-rule-renamed'},
    ], ids=['deactivate', 'demote', 'rename'])
    def test_an_administrative_field_change_is_refused(self, rest_api, users, delegate: CmdbUser,
                                                       changes: dict[str, Any]) -> None:
        """403 naming the field, the stored administrator unchanged"""
        before = _stored(users, OTHER_ADMIN_ID)

        response = rest_api.put(f'{USERS_URL}/{OTHER_ADMIN_ID}', json=_body(rest_api, OTHER_ADMIN_ID, **changes),
                                user=delegate)

        (field,) = changes
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == (
            f"Only an administrator may change the field '{field}' of an administrator!")
        assert _stored(users, OTHER_ADMIN_ID) == before

    def test_a_profile_change_of_an_administrator_still_passes(self, rest_api, users, delegate: CmdbUser) -> None:
        """The name, email and image are not what makes an administrator"""
        response = rest_api.put(f'{USERS_URL}/{OTHER_ADMIN_ID}',
                                json=_body(rest_api, OTHER_ADMIN_ID, first_name='Renamed'), user=delegate)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, OTHER_ADMIN_ID)['first_name'] == 'Renamed'

    @pytest.mark.parametrize('admin_id', [CmdbUser.ADMIN_PUBLIC_ID, OTHER_ADMIN_ID], ids=['bootstrap', 'other'])
    def test_setting_an_administrators_password_is_refused(self, rest_api, users, delegate: CmdbUser,
                                                           admin_id: int) -> None:
        """403, the stored digest unchanged"""
        before: str = _stored(users, admin_id)['password']

        response = rest_api.patch(f'{USERS_URL}/{admin_id}/password', json={'password': NEW_PASSWORD}, user=delegate)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == 'Only an administrator may change the password of an administrator!'
        assert _stored(users, admin_id)['password'] == before

    def test_deleting_an_administrator_is_refused(self, rest_api, users, delegate: CmdbUser) -> None:
        """403, the administrator still stored"""
        response = rest_api.delete(f'{USERS_URL}/{OTHER_ADMIN_ID}', user=delegate)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(users, OTHER_ADMIN_ID) is not None


class TestTheDelegateStillManagesOrdinaryUsers:
    """The rule takes nothing from the user rights below the administrator group."""

    def test_creates_an_ordinary_user(self, rest_api, users, delegate: CmdbUser) -> None:
        """Into any group but the administrators'"""
        response = rest_api.post(f'{USERS_URL}/', json=_new_user(USER_GROUP_ID, 'ordinary'), user=delegate)

        assert response.status_code == HTTPStatus.CREATED
        assert users.count_documents({'user_name': f'{CREATED_NAME_PREFIX}ordinary'}) == 1

    def test_deactivates_and_regroups_an_ordinary_user(self, rest_api, users, delegate: CmdbUser) -> None:
        """Administrative fields of a non-administrator stay the right's business"""
        response = rest_api.put(f'{USERS_URL}/{ORDINARY_ID}',
                                json=_body(rest_api, ORDINARY_ID, active=False, group_id=DELEGATE_GROUP_ID),
                                user=delegate)

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = _stored(users, ORDINARY_ID)
        assert (stored['active'], stored['group_id']) == (False, DELEGATE_GROUP_ID)

    def test_sets_an_ordinary_users_password(self, rest_api, users, delegate: CmdbUser) -> None:
        """The digest changes"""
        before: str = _stored(users, ORDINARY_ID)['password']

        response = rest_api.patch(f'{USERS_URL}/{ORDINARY_ID}/password', json={'password': NEW_PASSWORD},
                                  user=delegate)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, ORDINARY_ID)['password'] != before

    def test_deletes_an_ordinary_user(self, rest_api, users, delegate: CmdbUser) -> None:
        """Gone"""
        response = rest_api.delete(f'{USERS_URL}/{ORDINARY_ID}', user=delegate)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, ORDINARY_ID) is None


class TestAnAdministratorMayDoAllOfIt:
    """The seeded administrator - the test client's default caller."""

    def test_promotes_and_demotes(self, rest_api, users) -> None:
        """Into the administrator group and out again"""
        promoted = rest_api.put(f'{USERS_URL}/{ORDINARY_ID}', json=_body(rest_api, ORDINARY_ID,
                                                                          group_id=ADMIN_GROUP_ID))
        demoted = rest_api.put(f'{USERS_URL}/{ORDINARY_ID}', json=_body(rest_api, ORDINARY_ID,
                                                                         group_id=USER_GROUP_ID))

        assert (promoted.status_code, demoted.status_code) == (HTTPStatus.ACCEPTED, HTTPStatus.ACCEPTED)
        assert _stored(users, ORDINARY_ID)['group_id'] == USER_GROUP_ID

    def test_sets_another_administrators_password_and_deletes_them(self, rest_api, users) -> None:
        """Another administrator remains, so neither is the last one"""
        password = rest_api.patch(f'{USERS_URL}/{OTHER_ADMIN_ID}/password', json={'password': NEW_PASSWORD})
        deleted = rest_api.delete(f'{USERS_URL}/{OTHER_ADMIN_ID}')

        assert (password.status_code, deleted.status_code) == (HTTPStatus.ACCEPTED, HTTPStatus.ACCEPTED)
        assert _stored(users, OTHER_ADMIN_ID) is None


class TestTheLastAdministratorStays:
    """No write may leave the administrator group without an active member."""

    @pytest.fixture(name='last_administrator')
    def fixture_last_administrator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No other active administrator exists - whatever else the test database holds"""
        monkeypatch.setattr(UsersManager, 'has_other_active_member', lambda _self, _group, _user: False)

    @pytest.mark.usefixtures('last_administrator')
    @pytest.mark.parametrize('changes, change', [
        ({'active': False}, 'deactivated'),
        ({'group_id': USER_GROUP_ID}, 'moved out of the administrator group'),
    ], ids=['deactivate', 'demote'])
    def test_an_update_removing_the_last_administrator_is_refused(self, rest_api, users,
                                                                  changes: dict[str, Any], change: str) -> None:
        """400 naming the user and what would happen, the stored administrator unchanged"""
        before = _stored(users, OTHER_ADMIN_ID)

        response = rest_api.put(f'{USERS_URL}/{OTHER_ADMIN_ID}', json=_body(rest_api, OTHER_ADMIN_ID, **changes))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == (
            f'The User with ID: {OTHER_ADMIN_ID} is the last active administrator and cannot be {change}!')
        assert _stored(users, OTHER_ADMIN_ID) == before

    @pytest.mark.usefixtures('last_administrator')
    def test_deleting_the_last_administrator_is_refused(self, rest_api, users) -> None:
        """400, still stored"""
        response = rest_api.delete(f'{USERS_URL}/{OTHER_ADMIN_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, OTHER_ADMIN_ID) is not None

    @pytest.mark.usefixtures('last_administrator')
    def test_a_profile_change_of_the_last_administrator_passes_without_a_count(self, rest_api, users,
                                                                              monkeypatch) -> None:
        """Only a demotion, deactivation or delete can remove an administrator"""
        monkeypatch.setattr(UsersManager, 'has_other_active_member', None)

        response = rest_api.put(f'{USERS_URL}/{OTHER_ADMIN_ID}',
                                json=_body(rest_api, OTHER_ADMIN_ID, first_name='Still admin'))

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_with_another_active_administrator_the_demotion_passes(self, rest_api, users) -> None:
        """The real count: the seeded bootstrap administrator remains"""
        response = rest_api.put(f'{USERS_URL}/{OTHER_ADMIN_ID}',
                                json=_body(rest_api, OTHER_ADMIN_ID, group_id=USER_GROUP_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, OTHER_ADMIN_ID)['group_id'] == USER_GROUP_ID
