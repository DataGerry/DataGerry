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
Functional tests: nobody puts a user into a user group holding more than they do (phase 8 step 7, T579)

A user manager (not an administrator) creates and edits users and deletes groups. A group holding a right the manager
lacks (STRONG), or an assignment reaching a Type the manager may not view (REACHING), is refused (403) on a user
create, on a user update adding it, and as the MOVE target of a group delete with sole members. A group within the
manager's reach (WEAK) passes; a group the user keeps, and a removal, are never judged; an administrator passes
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    MEMBERSHIP_BEYOND_MSG,
    MEMBERSHIP_GROUP_PART,
    MEMBERSHIP_RIGHTS_PART,
)
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_GROUP_ID: int = 9891
STRONG_GROUP_ID: int = 9892
REACHING_GROUP_ID: int = 9893
WEAK_GROUP_ID: int = 9894
DOOMED_GROUP_ID: int = 9895
GROUP_IDS: list[int] = [MANAGER_GROUP_ID, STRONG_GROUP_ID, REACHING_GROUP_ID, WEAK_GROUP_ID, DOOMED_GROUP_ID]
MANAGER_ID: int = 9896
MEMBER_ID: int = 9897
KEEPER_ID: int = 9898
USER_IDS: list[int] = [MANAGER_ID, MEMBER_ID, KEEPER_ID]
TYPE_ID: int = 9899
ROLE_ID: int = 9900
HELD_RIGHT: str = 'base.framework.object.view'
UNHELD_RIGHT: str = 'base.framework.type.edit'
MANAGER_RIGHTS: list[str] = [HELD_RIGHT, 'base.user-management.user.*', 'base.user-management.group.*']
NEW_USER_NAME: str = 'membership-new'
STRONG_REFUSAL: str = MEMBERSHIP_BEYOND_MSG.format(details=MEMBERSHIP_GROUP_PART.format(
    group_id=STRONG_GROUP_ID, beyond=MEMBERSHIP_RIGHTS_PART.format(names=[UNHELD_RIGHT])))


def _group(public_id: int, rights: list[str]) -> dict[str, Any]:
    """A stored group"""
    return {'public_id': public_id, 'name': f'membership-{public_id}', 'label': str(public_id), 'rights': rights}


def _user(public_id: int, group_ids: list[int]) -> dict[str, Any]:
    """A stored user"""
    return {'public_id': public_id, 'user_name': f'membership-{public_id}', 'active': True, 'group_ids': group_ids,
            'registration_time': datetime.now(timezone.utc), 'password': 'hashed-stub'}


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The manager; STRONG (an unheld right), REACHING (view on a Type the manager lacks), WEAK (a held right);
    MEMBER only in WEAK, KEEPER in WEAK and STRONG; DOOMED whose sole member is MEMBER's twin"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_many([
        _group(MANAGER_GROUP_ID, MANAGER_RIGHTS), _group(STRONG_GROUP_ID, [UNHELD_RIGHT]),
        _group(REACHING_GROUP_ID, []), _group(WEAK_GROUP_ID, [HELD_RIGHT]), _group(DOOMED_GROUP_ID, []),
    ])
    database[CmdbUser.COLLECTION].insert_many([_user(MANAGER_ID, [MANAGER_GROUP_ID]), _user(MEMBER_ID, [WEAK_GROUP_ID]),
                                               _user(KEEPER_ID, [WEAK_GROUP_ID, STRONG_GROUP_ID])])
    database[CmdbType.COLLECTION].insert_one({'public_id': TYPE_ID, 'name': 'membership-type', 'label': 'T',
                                              'fields': []})
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': ROLE_ID, 'name': 'membership-view', 'description': '',
                                                   'types': [TYPE_ID], 'operations': ['view'],
                                                   'write_regular_fields': False, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': 9901, 'group_id': REACHING_GROUP_ID,
                                                          'role_id': ROLE_ID, 'scope': '*', 'description': ''})

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': GROUP_IDS}})
    database[CmdbUser.COLLECTION].delete_many({'$or': [{'public_id': {'$in': USER_IDS}},
                                                       {'user_name': NEW_USER_NAME}]})
    database[CmdbType.COLLECTION].delete_many({'public_id': TYPE_ID})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _manager() -> dict[str, Any]:
    """The request kwargs sending the user manager"""
    return {'user': CmdbUser(public_id=MANAGER_ID, user_name=f'membership-{MANAGER_ID}', active=True,
                             group_ids=[MANAGER_GROUP_ID])}


def _create(rest_api: Any, group_ids: list[int], **kwargs: Any) -> Any:
    """POST /users/"""
    return rest_api.post('/users/', json={'user_name': NEW_USER_NAME, 'password': 'pw', 'active': True,
                                          'group_ids': group_ids}, **kwargs)


def _put_groups(rest_api: Any, user_id: int, group_ids: list[int], **kwargs: Any) -> Any:
    """PUT /users/<id> with the stored user and new groups"""
    stored: dict[str, Any] = rest_api.get(f'/users/{user_id}').get_json()['result']
    body: dict[str, Any] = {key: value for key, value in stored.items()
                            if key not in ('password', 'registration_time', 'sync_pending')}

    return rest_api.put(f'/users/{user_id}', json={**body, 'group_ids': group_ids}, **kwargs)


class TestUserCreate:
    """POST /users"""

    def test_a_group_holding_an_unheld_right_is_refused(self, rest_api, database: Any) -> None:
        """Named with the right; nothing stored"""
        response = _create(rest_api, [WEAK_GROUP_ID, STRONG_GROUP_ID], **_manager())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == STRONG_REFUSAL
        assert database[CmdbUser.COLLECTION].count_documents({'user_name': NEW_USER_NAME}) == 0

    def test_a_group_reaching_beyond_is_refused(self, rest_api) -> None:
        """Its assignment views a Type the manager may not"""
        response = _create(rest_api, [REACHING_GROUP_ID], **_manager())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == MEMBERSHIP_BEYOND_MSG.format(
            details=MEMBERSHIP_GROUP_PART.format(group_id=REACHING_GROUP_ID, beyond=f'view on Types [{TYPE_ID}]'))

    def test_a_group_within_reach_passes(self, rest_api) -> None:
        """WEAK holds only what the manager holds"""
        assert _create(rest_api, [WEAK_GROUP_ID], **_manager()).status_code == HTTPStatus.CREATED

    def test_an_administrator_passes(self, rest_api) -> None:
        """Exempt"""
        assert _create(rest_api, [STRONG_GROUP_ID, REACHING_GROUP_ID]).status_code == HTTPStatus.CREATED


class TestUserUpdate:
    """PUT /users/<id>"""

    def test_adding_a_strong_group_is_refused(self, rest_api, database: Any) -> None:
        """Nothing written"""
        response = _put_groups(rest_api, MEMBER_ID, [WEAK_GROUP_ID, STRONG_GROUP_ID], **_manager())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == STRONG_REFUSAL
        assert database[CmdbUser.COLLECTION].find_one({'public_id': MEMBER_ID})['group_ids'] == [WEAK_GROUP_ID]

    @pytest.mark.parametrize('group_ids', [[WEAK_GROUP_ID, STRONG_GROUP_ID], [STRONG_GROUP_ID]],
                             ids=['kept', 'weak-removed'])
    def test_a_kept_group_and_a_removal_are_not_judged(self, rest_api, group_ids: list[int]) -> None:
        """KEEPER is in STRONG already"""
        assert _put_groups(rest_api, KEEPER_ID, group_ids, **_manager()).status_code == HTTPStatus.ACCEPTED


class TestGroupDeleteMove:
    """DELETE /groups/<id>?action=MOVE"""

    def test_moving_sole_members_into_a_strong_group_is_refused(self, rest_api, database: Any) -> None:
        """The group stays"""
        database[CmdbUser.COLLECTION].update_one({'public_id': MEMBER_ID}, {'$set': {'group_ids': [DOOMED_GROUP_ID]}})

        response = rest_api.delete(f'/groups/{DOOMED_GROUP_ID}', query_string={
            'action': GroupDeleteMode.MOVE.value, 'group_id': STRONG_GROUP_ID}, **_manager())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == STRONG_REFUSAL
        assert database[CmdbUserGroup.COLLECTION].count_documents({'public_id': DOOMED_GROUP_ID}) == 1

    def test_a_move_adding_nobody_passes(self, rest_api, database: Any) -> None:
        """A member keeping another group is no sole member - nothing is added"""
        database[CmdbUser.COLLECTION].update_one({'public_id': MEMBER_ID},
                                                 {'$set': {'group_ids': [WEAK_GROUP_ID, DOOMED_GROUP_ID]}})

        response = rest_api.delete(f'/groups/{DOOMED_GROUP_ID}', query_string={
            'action': GroupDeleteMode.MOVE.value, 'group_id': STRONG_GROUP_ID}, **_manager())

        assert response.status_code == HTTPStatus.ACCEPTED
