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
Functional tests for the name rule on a CmdbUser's user_name and a CmdbUserGroup's name

POST and PUT of /users and /groups refuse a name that is blank, starts or ends with whitespace, or holds a control
character - with a 400 naming the field and the reason, before anything is written. Whitespace inside a name is
allowed. The login refuses a login that is blank once stripped, so a stored blank name is not reached by typing
spaces. A stored padded name is repaired by updater_20261011 and logs in again;
one it cannot repair is refused on every save until it is renamed, because the whole user is always sent
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261011 import Update20261011
from cmdb.manager import SecurityManager
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.utils import NameShapeProblem
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'
GROUPS_URL: str = '/groups'
LOGIN_URL: str = '/auth/login'
DEFAULT_GROUP_ID: int = 2
PASSWORD: str = 'name-rule-password'
LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'

USER_NAME: str = CmdbUserKey.USER_NAME.value
GROUP_NAME: str = GroupKey.NAME.value

CLEAN_USER_NAME: str = 'name-rule-user'
INNER_SPACE_USER_NAME: str = 'name rule user'
CLEAN_GROUP_NAME: str = 'name-rule-group'
INNER_SPACE_GROUP_NAME: str = 'name rule group'
STORED_PADDED_NAME: str = ' name-rule-stored '
STORED_BLANK_NAME: str = ''
STORED_USER_ID: int = 98701

# Every refused spelling, with the reason the 400 names
REFUSED_NAMES: dict[str, tuple[str, NameShapeProblem]] = {
    'empty': ('', NameShapeProblem.BLANK),
    'blank': ('   ', NameShapeProblem.BLANK),
    'padded': (f' {CLEAN_USER_NAME} ', NameShapeProblem.PADDED),
    'trailing-tab': (f'{CLEAN_USER_NAME}\t', NameShapeProblem.PADDED),
    'no-break-space': (f'\u00a0{CLEAN_USER_NAME}', NameShapeProblem.PADDED),
    'control-inside': ('name\nrule', NameShapeProblem.CONTROL_CHARACTER),
}
REFUSED_IDS: list[str] = list(REFUSED_NAMES)
REFUSED_VALUES: list[tuple[str, NameShapeProblem]] = list(REFUSED_NAMES.values())

ALL_USER_NAMES: list[str] = [CLEAN_USER_NAME, INNER_SPACE_USER_NAME, STORED_PADDED_NAME, STORED_BLANK_NAME,
                             STORED_PADDED_NAME.strip()] + [name for name, _ in REFUSED_VALUES]
ALL_GROUP_NAMES: list[str] = [CLEAN_GROUP_NAME, INNER_SPACE_GROUP_NAME] + [name for name, _ in REFUSED_VALUES]


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Both unique indexes built; every user and group these tests name removed, before and after."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    database_manager.create_indexes(CmdbUser.COLLECTION, database_name, CmdbUser.get_index_keys())
    database_manager.create_indexes(CmdbUserGroup.COLLECTION, database_name, CmdbUserGroup.get_index_keys())

    def _purge() -> None:
        users.delete_many({'$or': [{USER_NAME: {'$in': ALL_USER_NAMES}}, {'public_id': STORED_USER_ID}]})
        groups.delete_many({GROUP_NAME: {'$in': ALL_GROUP_NAMES}})

    _purge()
    yield users, groups
    _purge()


def _user_payload(user_name: str) -> dict[str, Any]:
    """A CmdbUser body accepted by POST /users/."""
    return {USER_NAME: user_name, 'active': True, 'group_id': DEFAULT_GROUP_ID, 'password': PASSWORD}


def _group_payload(name: str) -> dict[str, Any]:
    """A CmdbUserGroup body accepted by POST /groups/ and PUT /groups/<id>."""
    return {GROUP_NAME: name, 'label': CLEAN_GROUP_NAME, 'rights': []}


def _assert_refused(response, field: str, problem: NameShapeProblem) -> None:
    """A 400 naming the field and the reason."""
    assert response.status_code == HTTPStatus.BAD_REQUEST
    message: str = response.get_json()['message']
    assert field in message and problem.value in message


def _store_user(users: Any, database_manager: MongoDatabaseManager, database_name: str, user_name: str) -> None:
    """A local user written straight into the collection, past the routes."""
    users.insert_one({
        'public_id': STORED_USER_ID, USER_NAME: user_name, 'active': True, 'group_id': DEFAULT_GROUP_ID,
        'registration_time': datetime.now(timezone.utc), 'authenticator': LOCAL_PROVIDER,
        'password': SecurityManager(database_manager, database_name).generate_hmac(PASSWORD),
    })


def _login(rest_api, user_name: str):
    """POST /auth/login without the test client's own token."""
    return rest_api.post(LOGIN_URL, json={USER_NAME: user_name, 'password': PASSWORD}, unauthorized=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       USERS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUserNameRule:
    """POST /users/ and PUT /users/<id>"""

    @pytest.mark.parametrize('name, problem', REFUSED_VALUES, ids=REFUSED_IDS)
    def test_a_create_with_a_refused_name_is_a_400_and_stores_nothing(self, rest_api, collections, name: str,
                                                                       problem: NameShapeProblem) -> None:
        """Before the pre-check and the write"""
        _assert_refused(rest_api.post(f'{USERS_URL}/', json=_user_payload(name)), USER_NAME, problem)
        assert collections[0].count_documents({USER_NAME: name}) == 0

    @pytest.mark.parametrize('name, problem', REFUSED_VALUES, ids=REFUSED_IDS)
    def test_a_rename_to_a_refused_name_is_a_400_and_keeps_the_name(self, rest_api, collections, name: str,
                                                                     problem: NameShapeProblem) -> None:
        """An administrator's rename goes through the same rule"""
        new_id: int = rest_api.post(f'{USERS_URL}/', json=_user_payload(CLEAN_USER_NAME)).get_json()['result_id']
        stored: dict[str, Any] = rest_api.get(f'{USERS_URL}/{new_id}').get_json()['result']
        body: dict[str, Any] = {key: value for key, value in stored.items() if key != 'password'}

        _assert_refused(rest_api.put(f'{USERS_URL}/{new_id}', json={**body, USER_NAME: name}), USER_NAME, problem)
        assert collections[0].find_one({'public_id': new_id})[USER_NAME] == CLEAN_USER_NAME

    def test_whitespace_inside_a_name_is_allowed(self, rest_api, collections) -> None:
        """Only the surroundings are refused"""
        response = rest_api.post(f'{USERS_URL}/', json=_user_payload(INNER_SPACE_USER_NAME))

        assert response.status_code == HTTPStatus.CREATED
        assert collections[0].count_documents({USER_NAME: INNER_SPACE_USER_NAME}) == 1

    def test_a_stored_name_the_rule_refuses_cannot_be_saved_unchanged(self, rest_api, collections,
                                                                      database_manager, database_name) -> None:
        """The whole user is always sent, so an administrator has to rename it first"""
        _store_user(collections[0], database_manager, database_name, STORED_BLANK_NAME)
        stored: dict[str, Any] = rest_api.get(f'{USERS_URL}/{STORED_USER_ID}').get_json()['result']
        body: dict[str, Any] = {key: value for key, value in stored.items() if key != 'password'}

        _assert_refused(rest_api.put(f'{USERS_URL}/{STORED_USER_ID}', json=body), USER_NAME, NameShapeProblem.BLANK)

        renamed = rest_api.put(f'{USERS_URL}/{STORED_USER_ID}', json={**body, USER_NAME: CLEAN_USER_NAME})
        assert renamed.status_code == HTTPStatus.ACCEPTED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      GROUPS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupNameRule:
    """POST /groups/ and PUT /groups/<id>"""

    @pytest.mark.parametrize('name, problem', REFUSED_VALUES, ids=REFUSED_IDS)
    def test_a_create_with_a_refused_name_is_a_400_and_stores_nothing(self, rest_api, collections, name: str,
                                                                       problem: NameShapeProblem) -> None:
        """The rule user_name follows"""
        _assert_refused(rest_api.post(f'{GROUPS_URL}/', json=_group_payload(name)), GROUP_NAME, problem)
        assert collections[1].count_documents({GROUP_NAME: name}) == 0

    @pytest.mark.parametrize('name, problem', REFUSED_VALUES, ids=REFUSED_IDS)
    def test_a_rename_to_a_refused_name_is_a_400_and_keeps_the_name(self, rest_api, collections, name: str,
                                                                     problem: NameShapeProblem) -> None:
        """The update route too"""
        group_id: int = rest_api.post(f'{GROUPS_URL}/', json=_group_payload(CLEAN_GROUP_NAME)).get_json()['result_id']

        _assert_refused(rest_api.put(f'{GROUPS_URL}/{group_id}', json=_group_payload(name)), GROUP_NAME, problem)
        assert collections[1].find_one({'public_id': group_id})[GROUP_NAME] == CLEAN_GROUP_NAME

    def test_whitespace_inside_a_name_is_allowed(self, rest_api, collections) -> None:
        """Only the surroundings are refused"""
        response = rest_api.post(f'{GROUPS_URL}/', json=_group_payload(INNER_SPACE_GROUP_NAME))

        assert response.status_code == HTTPStatus.CREATED
        assert collections[1].count_documents({GROUP_NAME: INNER_SPACE_GROUP_NAME}) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      LOGIN                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLoginAndStoredNames:
    """POST /auth/login against stored names the rule refuses"""

    @pytest.mark.parametrize('login', [' ', '   ', '\t'], ids=['space', 'spaces', 'tab'])
    def test_spaces_do_not_reach_a_user_stored_with_a_blank_name(self, rest_api, collections, database_manager,
                                                                 database_name, login: str) -> None:
        """It used to log in as that user - the one 401 of every refused login now"""
        _store_user(collections[0], database_manager, database_name, STORED_BLANK_NAME)

        assert _login(rest_api, login).status_code == HTTPStatus.UNAUTHORIZED

    def test_a_padded_user_logs_in_again_once_the_update_strips_it(self, rest_api, collections, database_manager,
                                                                   database_name) -> None:
        """Locked out under every spelling before; the update repairs the stored name"""
        _store_user(collections[0], database_manager, database_name, STORED_PADDED_NAME)
        assert _login(rest_api, STORED_PADDED_NAME.strip()).status_code == HTTPStatus.UNAUTHORIZED
        assert _login(rest_api, STORED_PADDED_NAME).status_code == HTTPStatus.UNAUTHORIZED

        Update20261011(database_manager, database_name).start_update()

        response = _login(rest_api, STORED_PADDED_NAME)
        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['user'][USER_NAME] == STORED_PADDED_NAME.strip()
