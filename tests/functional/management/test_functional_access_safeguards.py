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
Functional tests: the safeguards of the access rules and the user groups, through the real REST app

Nobody gives a user group they are in more than they hold (403) - by an assignment or by changing a role assigned to
it; for another group, or within reach, the write passes. Nobody grants a user group a right they do not hold (400);
a right the group holds already may stay. A scope role naming a Type the caller may not read is refused like one
naming a missing Type (no oracle) - the hidden Type's ACL also stored as the access rules it translates to
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_rules import AccessRuleMessage, ReachPart
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_ADD_RIGHT,
    GROUP_EDIT_RIGHT,
    GROUP_RIGHTS_NOT_HELD_MSG,
    GROUP_VIEW_RIGHT,
)
from tests.utils.type_access_seed import SeededAccess, remove_type_access, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

CALLER_GROUP_ID: int = 9861
OTHER_GROUP_ID: int = 9862
TARGET_GROUP_ID: int = 9863
GROUP_IDS: list[int] = [CALLER_GROUP_ID, OTHER_GROUP_ID, TARGET_GROUP_ID]
CALLER_ID: int = 9864
CALLER_NAME: str = 'safeguard-caller'
SERVER_TYPE_ID: int = 9865
HIDDEN_TYPE_ID: int = 9866
TYPE_IDS: list[int] = [SERVER_TYPE_ID, HIDDEN_TYPE_ID]
VIEW_ROLE_ID: int = 9867
EDIT_ROLE_ID: int = 9868
ACCESS_RIGHTS: list[str] = ['base.access.*']
TYPE_EDIT_RIGHT: str = 'base.framework.type.edit'
TYPE_VIEW_RIGHT: str = 'base.framework.type.view'
MASTER_RIGHT: str = 'base.*'
ROLES_URL: str = '/access/scope_roles'
ASSIGNMENTS_URL: str = '/access/assignments'
GROUPS_URL: str = '/groups/'
CREATED_GROUP_NAME: str = 'safeguard-created'


def _role(public_id: int, operations: list[str]) -> dict[str, Any]:
    """A stored role on the server Type"""
    return {'public_id': public_id, 'name': f'safeguard-{public_id}', 'description': '', 'types': [SERVER_TYPE_ID],
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The caller's group may manage access and groups; it views servers (VIEW_ROLE); EDIT_ROLE is unassigned"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': CALLER_GROUP_ID, 'name': 'safeguard-caller', 'label': 'Caller',
         'rights': ACCESS_RIGHTS + [GROUP_ADD_RIGHT, GROUP_EDIT_RIGHT, GROUP_VIEW_RIGHT]},
        {'public_id': OTHER_GROUP_ID, 'name': 'safeguard-other', 'label': 'Other', 'rights': []},
        {'public_id': TARGET_GROUP_ID, 'name': 'safeguard-target', 'label': 'Target', 'rights': [TYPE_EDIT_RIGHT]},
    ])
    database[CmdbUser.COLLECTION].insert_one({'public_id': CALLER_ID, 'user_name': CALLER_NAME, 'active': True,
                                              'group_ids': [CALLER_GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbType.COLLECTION].insert_many([
        {'public_id': SERVER_TYPE_ID, 'name': 'safeguard-server', 'label': 'Server', 'fields': []},
        {'public_id': HIDDEN_TYPE_ID, 'name': 'safeguard-hidden', 'label': 'Hidden', 'fields': [],
         'acl': {'activated': True, 'groups': {'includes': {}}}},
    ])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(VIEW_ROLE_ID, ['view']),
                                                    _role(EDIT_ROLE_ID, ['view', 'edit'])])
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': 9869, 'group_id': CALLER_GROUP_ID,
                                                          'role_id': VIEW_ROLE_ID, 'scope': '*', 'description': ''})
    access: SeededAccess = store_type_access(database, TYPE_IDS)

    yield database

    remove_type_access(database, access)
    database[CmdbUserGroup.COLLECTION].delete_many({'$or': [{'public_id': {'$in': GROUP_IDS}},
                                                            {'name': CREATED_GROUP_NAME}]})
    database[CmdbUser.COLLECTION].delete_many({'public_id': CALLER_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _caller() -> CmdbUser:
    """The caller"""
    return CmdbUser(public_id=CALLER_ID, user_name=CALLER_NAME, active=True, group_ids=[CALLER_GROUP_ID])


def _beyond(role_id: int, *parts: str) -> str:
    """The 403 message"""
    beyond: str = ReachPart.SEPARATOR.value.join(parts)

    return AccessRuleMessage.BEYOND_OWN_REACH.value.format(role_id=role_id, beyond=beyond)


class TestOwnReach:
    """Nobody gives their own group more than they hold"""

    def test_assigning_more_to_the_own_group_is_refused(self, rest_api) -> None:
        """Edit on servers is not held, nor writing their fields"""
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': CALLER_GROUP_ID, 'role_id': EDIT_ROLE_ID,
                                                        'scope': '*'}, user=_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _beyond(EDIT_ROLE_ID, 'edit on Types [9865]',
                                                         'writing fields on Types [9865]')

    def test_assigning_it_to_another_group_passes(self, rest_api) -> None:
        """Not the caller's group"""
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': OTHER_GROUP_ID, 'role_id': EDIT_ROLE_ID,
                                                        'scope': '*'}, user=_caller())

        assert response.status_code == HTTPStatus.CREATED

    def test_moving_an_assignment_to_the_own_group_is_refused(self, rest_api, database: Any) -> None:
        """An update judges the group it ends with"""
        database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': 9870, 'group_id': OTHER_GROUP_ID,
                                                              'role_id': EDIT_ROLE_ID, 'scope': '*',
                                                              'description': ''})

        response = rest_api.put(f'{ASSIGNMENTS_URL}/9870', json={'group_id': CALLER_GROUP_ID}, user=_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_widening_a_role_of_the_own_group_is_refused(self, rest_api) -> None:
        """The view role is assigned to the caller's group"""
        response = rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}', json={'operations': ['view', 'delete']},
                                user=_caller())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _beyond(VIEW_ROLE_ID, 'delete on Types [9865]')

    def test_a_change_within_reach_passes(self, rest_api) -> None:
        """Only the description"""
        response = rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}', json={'description': 'servers'}, user=_caller())

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_the_administrator_reaches_everything(self, rest_api) -> None:
        """No restriction on the administrators' side: within reach"""
        assert rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}',
                            json={'operations': ['view', 'delete']}).status_code == HTTPStatus.ACCEPTED


class TestGrantingRights:
    """Nobody grants a right they do not hold"""

    def test_a_right_not_held_is_refused(self, rest_api) -> None:
        """The master right"""
        response = rest_api.post(GROUPS_URL, json={'name': CREATED_GROUP_NAME, 'label': 'Created',
                                                   'rights': [GROUP_VIEW_RIGHT, MASTER_RIGHT]}, user=_caller())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_RIGHTS_NOT_HELD_MSG.format(names=[MASTER_RIGHT])

    def test_held_rights_are_granted(self, rest_api) -> None:
        """A right held through the access wildcard, one held directly"""
        response = rest_api.post(GROUPS_URL, json={'name': CREATED_GROUP_NAME, 'label': 'Created',
                                                   'rights': ['base.access.view', GROUP_VIEW_RIGHT]}, user=_caller())

        assert response.status_code == HTTPStatus.CREATED

    def test_a_right_the_group_holds_already_may_stay(self, rest_api) -> None:
        """The target group's type edit right is not the caller's - kept, not granted"""
        response = rest_api.put(f'{GROUPS_URL}{TARGET_GROUP_ID}', json={
            'name': 'safeguard-target', 'label': 'Target', 'rights': [TYPE_EDIT_RIGHT, GROUP_VIEW_RIGHT]},
            user=_caller())

        assert response.status_code == HTTPStatus.ACCEPTED

    def test_adding_a_right_not_held_is_refused(self, rest_api) -> None:
        """Type view is new and not held"""
        response = rest_api.put(f'{GROUPS_URL}{TARGET_GROUP_ID}', json={
            'name': 'safeguard-target', 'label': 'Target', 'rights': [TYPE_EDIT_RIGHT, TYPE_VIEW_RIGHT]},
            user=_caller())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_RIGHTS_NOT_HELD_MSG.format(names=[TYPE_VIEW_RIGHT])


def test_a_type_the_caller_may_not_read_is_refused_like_a_missing_one(rest_api) -> None:
    """The hidden Type's ACL grants nobody; the message is the missing Type's"""
    response = rest_api.post(ROLES_URL, json={'name': 'safeguard-hidden-role', 'types': [HIDDEN_TYPE_ID, 9899],
                                              'operations': ['view']}, user=_caller())

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[HIDDEN_TYPE_ID, 9899])
