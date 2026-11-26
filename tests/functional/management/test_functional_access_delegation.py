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
Functional tests: delegated assignments (phase 8 step 8) through the real REST app

A delegate (``base.access.view`` + ``base.access.assignment.delegate``, no edit right) views servers. They create,
change and delete assignments only whose scope role stays within that - before and after the write; a role editing
routers is beyond them, whichever group it is for. An administrator (an editor) is not judged. ``?within_reach=true``
lists only the roles the caller may hand out. Without either right an assignment write is refused naming both
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
from cmdb.framework.access_rules import AccessRuleMessage
# -------------------------------------------------------------------------------------------------------------------- #

DELEGATE_GROUP_ID: int = 9921
OTHER_GROUP_ID: int = 9922
PLAIN_GROUP_ID: int = 9923
DELEGATE_ID: int = 9924
PLAIN_ID: int = 9925
SERVER_TYPE_ID: int = 9926
ROUTER_TYPE_ID: int = 9927
VIEW_SERVERS_ROLE: int = 9931
EDIT_ROUTERS_ROLE: int = 9932
DELEGATE_ASSIGNMENT: int = 9941
OTHER_ROUTERS_ASSIGNMENT: int = 9942
DELEGATE_RIGHTS: list[str] = ['base.access.view', 'base.access.assignment.delegate']
ASSIGNMENTS_URL: str = '/access/assignments'
ROLES_URL: str = '/access/scope_roles'
BEYOND: str = AccessRuleMessage.BEYOND_DELEGATION.value.format(
    role_id=EDIT_ROUTERS_ROLE, beyond=f'view on Types [{ROUTER_TYPE_ID}]; edit on Types [{ROUTER_TYPE_ID}]')


def _role(public_id: int, types: list[int], operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'delegation-{public_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': False, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': '*', 'description': ''}


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The delegate views servers; the other group edits routers"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': DELEGATE_GROUP_ID, 'name': 'delegation-delegates', 'label': 'D', 'rights': DELEGATE_RIGHTS},
        {'public_id': OTHER_GROUP_ID, 'name': 'delegation-other', 'label': 'O', 'rights': []},
        {'public_id': PLAIN_GROUP_ID, 'name': 'delegation-plain', 'label': 'P', 'rights': ['base.access.view']},
    ])
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': user_id, 'user_name': f'delegation-{user_id}', 'active': True, 'group_ids': [group_id],
         'registration_time': datetime.now(timezone.utc)}
        for user_id, group_id in ((DELEGATE_ID, DELEGATE_GROUP_ID), (PLAIN_ID, PLAIN_GROUP_ID))
    ])
    database[CmdbType.COLLECTION].insert_many([{'public_id': type_id, 'name': f'delegation-{type_id}', 'label': 'T',
                                                'fields': []} for type_id in (SERVER_TYPE_ID, ROUTER_TYPE_ID)])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(VIEW_SERVERS_ROLE, [SERVER_TYPE_ID], ['view']),
                                                    _role(EDIT_ROUTERS_ROLE, [ROUTER_TYPE_ID], ['view', 'edit'])])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(DELEGATE_ASSIGNMENT, DELEGATE_GROUP_ID, VIEW_SERVERS_ROLE),
        _assignment(OTHER_ROUTERS_ASSIGNMENT, OTHER_GROUP_ID, EDIT_ROUTERS_ROLE),
    ])

    yield database

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [DELEGATE_GROUP_ID, OTHER_GROUP_ID,
                                                                          PLAIN_GROUP_ID]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [DELEGATE_ID, PLAIN_ID]}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVER_TYPE_ID, ROUTER_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _as(user_id: int, group_id: int) -> dict[str, Any]:
    """The request kwargs sending that user"""
    return {'user': CmdbUser(public_id=user_id, user_name=f'delegation-{user_id}', active=True, group_ids=[group_id])}


def _delegate() -> dict[str, Any]:
    """The delegate"""
    return _as(DELEGATE_ID, DELEGATE_GROUP_ID)


def _assign(rest_api: Any, role_id: int, **kwargs: Any) -> Any:
    """POST an assignment of the role to the plain group (which holds none yet)"""
    return rest_api.post(ASSIGNMENTS_URL, json={'group_id': PLAIN_GROUP_ID, 'role_id': role_id, 'scope': '*'},
                         **kwargs)


class TestDelegateWrites:
    """Within the delegate's own access, before and after"""

    def test_a_role_within_is_assigned(self, rest_api) -> None:
        """Any group"""
        assert _assign(rest_api, VIEW_SERVERS_ROLE, **_delegate()).status_code == HTTPStatus.CREATED

    def test_a_role_beyond_is_refused(self, rest_api, database: Any) -> None:
        """Named with what it grants beyond; nothing stored"""
        response = _assign(rest_api, EDIT_ROUTERS_ROLE, **_delegate())

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.FORBIDDEN, BEYOND)
        assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 2

    def test_an_assignment_beyond_is_untouchable(self, rest_api, database: Any) -> None:
        """Neither changed to a role within nor deleted"""
        changed = rest_api.put(f'{ASSIGNMENTS_URL}/{OTHER_ROUTERS_ASSIGNMENT}', json={'role_id': VIEW_SERVERS_ROLE},
                               **_delegate())
        deleted = rest_api.delete(f'{ASSIGNMENTS_URL}/{OTHER_ROUTERS_ASSIGNMENT}', **_delegate())

        assert (changed.status_code, deleted.status_code) == (HTTPStatus.FORBIDDEN, HTTPStatus.FORBIDDEN)
        assert database[CmdbAccessAssignment.COLLECTION].find_one(
            {'public_id': OTHER_ROUTERS_ASSIGNMENT})['role_id'] == EDIT_ROUTERS_ROLE

    def test_changing_to_a_role_beyond_is_refused(self, rest_api) -> None:
        """The role after the write is judged too"""
        created: int = _assign(rest_api, VIEW_SERVERS_ROLE, **_delegate()).get_json()['result_id']

        response = rest_api.put(f'{ASSIGNMENTS_URL}/{created}', json={'role_id': EDIT_ROUTERS_ROLE}, **_delegate())

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.FORBIDDEN, BEYOND)

    def test_an_assignment_within_is_deleted(self, rest_api) -> None:
        """Its own creation, gone again"""
        created: int = _assign(rest_api, VIEW_SERVERS_ROLE, **_delegate()).get_json()['result_id']

        assert rest_api.delete(f'{ASSIGNMENTS_URL}/{created}', **_delegate()).status_code == HTTPStatus.ACCEPTED


def test_an_administrator_is_not_judged(rest_api) -> None:
    """The edit right (base.*) hands out any role"""
    assert _assign(rest_api, EDIT_ROUTERS_ROLE).status_code == HTTPStatus.CREATED


def test_without_either_right_the_write_names_both(rest_api) -> None:
    """The view right alone"""
    response = _assign(rest_api, VIEW_SERVERS_ROLE, **_as(PLAIN_ID, PLAIN_GROUP_ID))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == ('User has not the required right base.access.assignment.edit or '
                                              'base.access.assignment.delegate')


class TestWithinReach:
    """GET /access/scope_roles?within_reach=true"""

    def test_the_delegate_gets_the_roles_within(self, rest_api) -> None:
        """Ahead of the paging - the total counts them"""
        response = rest_api.get(ROLES_URL, query_string={'within_reach': 'true'}, **_delegate())

        assert [role['public_id'] for role in response.get_json()['results']] == [VIEW_SERVERS_ROLE]
        assert response.get_json()['total'] == 1

    def test_an_administrator_gets_every_role(self, rest_api) -> None:
        """Exempt"""
        response = rest_api.get(ROLES_URL, query_string={'within_reach': 'true'})

        assert {VIEW_SERVERS_ROLE, EDIT_ROUTERS_ROLE} <= {role['public_id'] for role in response.get_json()['results']}

    @pytest.mark.parametrize('value, expected', [('false', 2), ('maybe', None)], ids=['off', 'not-a-flag'])
    def test_the_flag(self, rest_api, value: str, expected: int | None) -> None:
        """Off lists every role; anything but true / false is a 400"""
        response = rest_api.get(ROLES_URL, query_string={'within_reach': value}, **_delegate())

        if expected is None:
            assert response.status_code == HTTPStatus.BAD_REQUEST
        else:
            assert response.get_json()['total'] == expected
