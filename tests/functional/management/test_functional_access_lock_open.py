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
Functional tests: no change of the access rules silently locks or opens a Type, through the real REST app

A Type some group may view (or nobody restricts) is never left readable by no group - an assignment create / update /
delete, a role update or a group delete doing so is a 400 naming the Type, whatever ``unrestrict`` says. A Type that
was restricted is opened to everybody only with ``unrestrict=true``. ``GET /access/assignments/<id>/usage`` and
``GET /groups/<id>/usage`` answer what the delete would do
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.framework.access_rules import AccessRuleMessage
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9881
GROUP_ID: int = 9882
OTHER_GROUP_ID: int = 9883
VIEW_ROLE_ID: int = 9884
EDIT_ROLE_ID: int = 9885
EVERY_TYPE_ROLE_ID: int = 9886
ASSIGNMENTS_URL: str = '/access/assignments'
ROLES_URL: str = '/access/scope_roles'
UNRESTRICT: dict[str, str] = {'unrestrict': 'true'}
LOCKED: str = AccessRuleMessage.TYPES_LOCKED.value.format(ids=[TYPE_ID])
OPENED: str = AccessRuleMessage.TYPES_OPENED.value.format(ids=[TYPE_ID])


def _role(public_id: int, types: Any, operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'lock-open-{public_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """A Type, two groups without members, a view role, an edit-only role and a role on every Type"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_one({'public_id': TYPE_ID, 'name': 'lock-open', 'label': 'L', 'fields': []})
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': GROUP_ID, 'name': 'lock-open-a', 'label': 'A', 'rights': []},
        {'public_id': OTHER_GROUP_ID, 'name': 'lock-open-b', 'label': 'B', 'rights': []},
    ])
    database[CmdbScopeRole.COLLECTION].insert_many([
        _role(VIEW_ROLE_ID, [TYPE_ID], ['view']), _role(EDIT_ROLE_ID, [TYPE_ID], ['edit']),
        _role(EVERY_TYPE_ROLE_ID, '*', ['view']),
    ])

    yield database

    database[CmdbType.COLLECTION].delete_one({'public_id': TYPE_ID})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [GROUP_ID, OTHER_GROUP_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _assign(database: Any, public_id: int, group_id: int, role_id: int) -> None:
    """A stored assignment"""
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': public_id, 'group_id': group_id,
                                                          'role_id': role_id, 'scope': '*', 'description': ''})


def _refusal(response: Any) -> tuple[int, str]:
    """Status and message"""
    return response.status_code, response.get_json()['message']


class TestAssignmentWrites:
    """Create, update, delete"""

    def test_a_first_assignment_without_view_locks_the_type(self, rest_api) -> None:
        """Nobody restricted it; now nobody may view it"""
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': GROUP_ID, 'role_id': EDIT_ROLE_ID, 'scope': '*'})

        assert _refusal(response) == (HTTPStatus.BAD_REQUEST, LOCKED)

    def test_a_first_assignment_with_view_passes(self, rest_api) -> None:
        """Restricted, and the group views it"""
        response = rest_api.post(ASSIGNMENTS_URL, json={'group_id': GROUP_ID, 'role_id': VIEW_ROLE_ID, 'scope': '*'})

        assert response.status_code == HTTPStatus.CREATED

    def test_deleting_the_only_restriction_needs_the_confirmation(self, rest_api, database: Any) -> None:
        """400 naming the Type, then 202 with unrestrict=true"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert _refusal(rest_api.delete(f'{ASSIGNMENTS_URL}/9891')) == (HTTPStatus.BAD_REQUEST, OPENED)
        assert rest_api.delete(f'{ASSIGNMENTS_URL}/9891', query_string=UNRESTRICT).status_code == HTTPStatus.ACCEPTED

    def test_deleting_the_only_view_locks_whatever_the_confirmation(self, rest_api, database: Any) -> None:
        """The edit-only assignment keeps the Type restricted - nobody would view it"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)
        _assign(database, 9892, OTHER_GROUP_ID, EDIT_ROLE_ID)

        response = rest_api.delete(f'{ASSIGNMENTS_URL}/9891', query_string=UNRESTRICT)

        assert _refusal(response) == (HTTPStatus.BAD_REQUEST, LOCKED)

    def test_switching_the_role_to_one_without_view_locks(self, rest_api, database: Any) -> None:
        """An update judges the assignment it ends with"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert _refusal(rest_api.put(f'{ASSIGNMENTS_URL}/9891', json={'role_id': EDIT_ROLE_ID})) == (
            HTTPStatus.BAD_REQUEST, LOCKED)

    def test_another_viewer_keeps_the_delete_free(self, rest_api, database: Any) -> None:
        """Two groups view the Type; one may go"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)
        _assign(database, 9892, OTHER_GROUP_ID, VIEW_ROLE_ID)

        assert rest_api.delete(f'{ASSIGNMENTS_URL}/9891').status_code == HTTPStatus.ACCEPTED

    def test_an_unreadable_confirmation_is_refused(self, rest_api, database: Any) -> None:
        """The API's one rule for flags"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        response = rest_api.delete(f'{ASSIGNMENTS_URL}/9891', query_string={'unrestrict': 'yes'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'unrestrict' in response.get_json()['message']

    def test_a_role_on_every_type_opens_every_type(self, rest_api, database: Any) -> None:
        """Its delete names the Types read from the database - ours among them"""
        _assign(database, 9891, GROUP_ID, EVERY_TYPE_ROLE_ID)

        usage = rest_api.get(f'{ASSIGNMENTS_URL}/9891/usage').get_json()['result']

        assert TYPE_ID in usage['opened_type_ids'] and not usage['locked_type_ids']
        assert rest_api.delete(f'{ASSIGNMENTS_URL}/9891').status_code == HTTPStatus.BAD_REQUEST


class TestUsage:
    """GET /access/assignments/<id>/usage"""

    def test_what_the_delete_would_do(self, rest_api, database: Any) -> None:
        """Opens the Type; locks nothing"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert rest_api.get(f'{ASSIGNMENTS_URL}/9891/usage').get_json()['result'] == {
            'locked_type_ids': [], 'opened_type_ids': [TYPE_ID]}

    def test_a_missing_assignment_is_a_404(self, rest_api) -> None:
        """Nothing to judge"""
        assert rest_api.get(f'{ASSIGNMENTS_URL}/9899/usage').status_code == HTTPStatus.NOT_FOUND


class TestRoleUpdate:
    """A role some assignment grants"""

    def test_taking_view_out_locks(self, rest_api, database: Any) -> None:
        """Nobody else views the Type"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert _refusal(rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}', json={'operations': ['edit']})) == (
            HTTPStatus.BAD_REQUEST, LOCKED)

    def test_taking_the_type_out_opens_it(self, rest_api, database: Any) -> None:
        """Refused, then confirmed"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert _refusal(rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}', json={'types': []})) == (
            HTTPStatus.BAD_REQUEST, OPENED)
        assert rest_api.put(f'{ROLES_URL}/{VIEW_ROLE_ID}', json={'types': []},
                            query_string=UNRESTRICT).status_code == HTTPStatus.ACCEPTED

    def test_an_unassigned_role_changes_nothing(self, rest_api) -> None:
        """No Type depends on it"""
        assert rest_api.put(f'{ROLES_URL}/{EDIT_ROLE_ID}', json={'operations': []}).status_code == HTTPStatus.ACCEPTED


class TestGroupDelete:
    """The group's assignments go with it"""

    def test_the_only_viewer_group_needs_the_confirmation(self, rest_api, database: Any) -> None:
        """Its assignment is the Type's only restriction"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert _refusal(rest_api.delete(f'/groups/{GROUP_ID}')) == (HTTPStatus.BAD_REQUEST, OPENED)
        assert rest_api.delete(f'/groups/{GROUP_ID}', query_string=UNRESTRICT).status_code == HTTPStatus.ACCEPTED

    def test_the_only_viewer_beside_an_edit_only_group_locks(self, rest_api, database: Any) -> None:
        """Refused whatever the confirmation"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)
        _assign(database, 9892, OTHER_GROUP_ID, EDIT_ROLE_ID)

        assert _refusal(rest_api.delete(f'/groups/{GROUP_ID}', query_string=UNRESTRICT)) == (
            HTTPStatus.BAD_REQUEST, LOCKED)


class TestGroupUsage:
    """GET /groups/<id>/usage - the access half of the group delete's census"""

    @staticmethod
    def _access_usage(rest_api) -> tuple[list[int], list[int], list[int], bool]:
        """The assignments, locked and opened Types, and whether the delete is blocked"""
        result: dict[str, Any] = rest_api.get(f'/groups/{GROUP_ID}/usage').get_json()['result']

        return (result['assignment_ids'], result['locked_type_ids'], result['opened_type_ids'],
                result['blocks_delete'])

    def test_the_only_restriction_is_opened_not_blocking(self, rest_api, database: Any) -> None:
        """Confirmable - the delete then needs unrestrict=true"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)

        assert self._access_usage(rest_api) == ([9891], [], [TYPE_ID], False)

    def test_the_only_viewer_beside_an_edit_only_group_is_locked_and_blocks(self, rest_api, database: Any) -> None:
        """Refused whatever the confirmation"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)
        _assign(database, 9892, OTHER_GROUP_ID, EDIT_ROLE_ID)

        assert self._access_usage(rest_api) == ([9891], [TYPE_ID], [], True)

    def test_another_viewer_leaves_the_type_as_it_is(self, rest_api, database: Any) -> None:
        """The group's assignment is listed; no Type changes"""
        _assign(database, 9891, GROUP_ID, VIEW_ROLE_ID)
        _assign(database, 9892, OTHER_GROUP_ID, VIEW_ROLE_ID)

        assert self._access_usage(rest_api) == ([9891], [], [], False)

    def test_another_groups_assignments_are_not_listed(self, rest_api, database: Any) -> None:
        """Only the group's own"""
        _assign(database, 9892, OTHER_GROUP_ID, VIEW_ROLE_ID)

        assert self._access_usage(rest_api) == ([], [], [], False)
