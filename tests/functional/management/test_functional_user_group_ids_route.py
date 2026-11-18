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
Functional coverage of a user's group list on the ``/users`` routes

Pinned through the administrator's client: a user is created and updated in several groups, stored sorted and each
once; an empty list, a repeated group, a single int and an unknown group are refused (400) before anything is
written, and so is a list over ``MAX_GROUPS_PER_USER``; an update that leaves the list out keeps the stored one; the
answer carries ``group_ids`` and no ``group_id``. The user list and its ``HEAD`` count filter by group on the list
(``?filter={"group_ids": <id>}``): a user is found by any of its groups, wherever the group sits in the list
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.class_schema.user_model.cmdb_user_schema import DEFAULT_GROUP, MAX_GROUPS_PER_USER
from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    RETIRED_GROUP_ID_KEY,
    RETIRED_GROUP_ID_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/users'
KEY: str = CmdbUserKey.GROUP_IDS.value

FIRST_GROUP_ID: int = 9951
SECOND_GROUP_ID: int = 9952
UNKNOWN_GROUP_ID: int = 9959
ALL_GROUP_IDS: list[int] = [FIRST_GROUP_ID, SECOND_GROUP_ID]

USER_NAME: str = 'group-list-user'
OTHER_USER_NAME: str = 'group-list-other-user'
TOTAL_COUNT_HEADER: str = 'X-Total-Count'
# A list one over the cap - ids that need not exist: the schema refuses the length before any group is read
OVER_CAP_GROUP_IDS: list[int] = list(range(1, MAX_GROUPS_PER_USER + 2))
FIRST_NAME: str = 'Listed'


def _group_doc(public_id: int) -> dict[str, Any]:
    """A plain user group"""
    return {'public_id': public_id, 'name': f'group-list-{public_id}', 'label': 'Group list', 'rights': []}


def _payload(group_ids: Any) -> dict[str, Any]:
    """A create body naming the given groups"""
    return {'user_name': USER_NAME, 'active': True, KEY: group_ids, 'password': 'secret'}


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str) -> Any:
    """Two extra groups; the test user removed before and after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        users.delete_many({'user_name': {'$in': [USER_NAME, OTHER_USER_NAME]}})

    _purge()
    groups.insert_many([_group_doc(group_id) for group_id in ALL_GROUP_IDS])

    yield users

    _purge()


def _create(rest_api: Any, group_ids: Any) -> Any:
    """POST /users/"""
    return rest_api.post(f'{ROUTE_URL}/', json=_payload(group_ids))


def _created_id(rest_api: Any, group_ids: list[int]) -> int:
    """Creates the test user and answers its public_id"""
    response = _create(rest_api, group_ids)
    assert response.status_code == HTTPStatus.CREATED

    return response.get_json()['result_id']


class TestCreate:
    """POST /users/"""

    def test_a_user_in_several_groups_is_stored_sorted(self, rest_api, users) -> None:
        """Sent unsorted, stored and answered sorted"""
        response = _create(rest_api, [SECOND_GROUP_ID, FIRST_GROUP_ID])

        assert response.status_code == HTTPStatus.CREATED
        stored = users.find_one({'user_name': USER_NAME})
        assert stored[KEY] == [FIRST_GROUP_ID, SECOND_GROUP_ID]
        assert 'group_id' not in stored
        answered = response.get_json()['raw']
        assert answered[KEY] == [FIRST_GROUP_ID, SECOND_GROUP_ID] and 'group_id' not in answered

    def test_a_user_without_groups_gets_the_default_group(self, rest_api, users) -> None:
        """The key left out: the default group"""
        payload = _payload(None)
        payload.pop(KEY)

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.CREATED
        assert users.find_one({'user_name': USER_NAME})[KEY] == [DEFAULT_GROUP]

    @pytest.mark.parametrize('group_ids', [[], [FIRST_GROUP_ID, FIRST_GROUP_ID], FIRST_GROUP_ID],
                             ids=['empty', 'repeated', 'single-int'])
    def test_a_list_that_is_no_group_list_is_refused(self, rest_api, users, group_ids: Any) -> None:
        """400, nothing stored"""
        assert _create(rest_api, group_ids).status_code == HTTPStatus.BAD_REQUEST
        assert users.find_one({'user_name': USER_NAME}) is None

    def test_a_list_over_the_cap_is_refused(self, rest_api, users) -> None:
        """400 naming the field, nothing stored"""
        response = _create(rest_api, OVER_CAP_GROUP_IDS)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert KEY in response.get_json()['message']
        assert users.find_one({'user_name': USER_NAME}) is None

    def test_an_unknown_group_is_refused(self, rest_api, users) -> None:
        """Every group must exist - one unknown among known ones is enough"""
        response = _create(rest_api, [FIRST_GROUP_ID, UNKNOWN_GROUP_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(UNKNOWN_GROUP_ID) in response.get_json()['message']
        assert users.find_one({'user_name': USER_NAME}) is None


class TestUpdate:
    """PUT / PATCH /users/<id>"""

    @pytest.mark.parametrize('method', ['put', 'patch'])
    def test_the_list_is_replaced(self, rest_api, users, method: str) -> None:
        """A sent list replaces the stored one"""
        user_id: int = _created_id(rest_api, [FIRST_GROUP_ID])

        response = getattr(rest_api, method)(f'{ROUTE_URL}/{user_id}', json={KEY: [SECOND_GROUP_ID, FIRST_GROUP_ID]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'user_name': USER_NAME})[KEY] == [FIRST_GROUP_ID, SECOND_GROUP_ID]

    @pytest.mark.parametrize('method', ['put', 'patch'])
    def test_a_left_out_list_is_kept(self, rest_api, users, method: str) -> None:
        """Not the default group: the stored list"""
        user_id: int = _created_id(rest_api, [FIRST_GROUP_ID, SECOND_GROUP_ID])

        response = getattr(rest_api, method)(f'{ROUTE_URL}/{user_id}', json={'first_name': FIRST_NAME})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'user_name': USER_NAME})[KEY] == [FIRST_GROUP_ID, SECOND_GROUP_ID]

    @pytest.mark.parametrize('group_ids', [[], [SECOND_GROUP_ID, SECOND_GROUP_ID], [UNKNOWN_GROUP_ID]],
                             ids=['empty', 'repeated', 'unknown'])
    def test_a_list_that_is_no_group_list_is_refused(self, rest_api, users, group_ids: list[int]) -> None:
        """400, the stored list kept"""
        user_id: int = _created_id(rest_api, [FIRST_GROUP_ID])

        response = rest_api.put(f'{ROUTE_URL}/{user_id}', json={KEY: group_ids})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert users.find_one({'user_name': USER_NAME})[KEY] == [FIRST_GROUP_ID]


class TestListByGroup:
    """GET / HEAD /users/ with ?filter= on the group list - what the group's user list and member count ask"""

    @staticmethod
    def _filter(group_id: int) -> dict[str, str]:
        """The query string asking for the members of one group"""
        return {'filter': json.dumps({KEY: group_id})}

    @staticmethod
    def _seed(rest_api: Any) -> None:
        """The test user in both groups, another user in the second group only"""
        _created_id(rest_api, ALL_GROUP_IDS)
        other: dict[str, Any] = {**_payload([SECOND_GROUP_ID]), 'user_name': OTHER_USER_NAME}
        assert rest_api.post(f'{ROUTE_URL}/', json=other).status_code == HTTPStatus.CREATED

    @staticmethod
    def _listed(rest_api: Any, group_id: int) -> set[str]:
        """The user names GET /users/ answers for the group"""
        response = rest_api.get(f'{ROUTE_URL}/', query_string=TestListByGroup._filter(group_id))
        assert response.status_code == HTTPStatus.OK

        return {user['user_name'] for user in response.get_json()['results']}

    @pytest.mark.usefixtures('users')
    def test_a_user_is_listed_by_its_first_group(self, rest_api) -> None:
        """The lowest group - the one the single group_id was"""
        self._seed(rest_api)

        assert self._listed(rest_api, FIRST_GROUP_ID) == {USER_NAME}

    @pytest.mark.usefixtures('users')
    def test_a_user_is_listed_by_any_later_group(self, rest_api) -> None:
        """Not only by its first group: both members of the second group"""
        self._seed(rest_api)

        assert self._listed(rest_api, SECOND_GROUP_ID) == {USER_NAME, OTHER_USER_NAME}

    @pytest.mark.usefixtures('users')
    def test_the_member_count_counts_every_member(self, rest_api) -> None:
        """HEAD answers the count in its header - each member once"""
        self._seed(rest_api)

        response = rest_api.head(f'{ROUTE_URL}/', query_string=self._filter(SECOND_GROUP_ID))

        assert response.status_code == HTTPStatus.OK
        assert int(response.headers[TOTAL_COUNT_HEADER]) == len({USER_NAME, OTHER_USER_NAME})


class TestTheRetiredSingleGroupIsRefused:
    """A client still sending `group_id` gets a 400 naming it - not a user silently in the default group"""

    REFUSAL: str = f'{RETIRED_GROUP_ID_KEY}: {RETIRED_GROUP_ID_MSG}'

    def test_a_create_sending_it_is_refused_and_stores_nothing(self, rest_api, users) -> None:
        """400, no user"""
        payload: dict[str, Any] = {**_payload(None), RETIRED_GROUP_ID_KEY: FIRST_GROUP_ID}
        payload.pop(KEY)

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert self.REFUSAL in response.get_json()['message']
        assert users.find_one({'user_name': USER_NAME}) is None

    @pytest.mark.parametrize('method', ['put', 'patch'])
    def test_an_update_sending_it_is_refused_and_changes_nothing(self, rest_api, users, method: str) -> None:
        """400, the stored list kept - also beside a valid group_ids"""
        user_id: int = _created_id(rest_api, [FIRST_GROUP_ID])

        response = getattr(rest_api, method)(
            f'{ROUTE_URL}/{user_id}', json={KEY: [SECOND_GROUP_ID], RETIRED_GROUP_ID_KEY: SECOND_GROUP_ID},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert self.REFUSAL in response.get_json()['message']
        assert users.find_one({'user_name': USER_NAME})[KEY] == [FIRST_GROUP_ID]
