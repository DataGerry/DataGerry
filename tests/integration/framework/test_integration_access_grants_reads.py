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
Integration tests for the reads behind the access grants, against the test MongoDB

Every assignment and the assignments of several groups in one read, ascending; the role ids of every assignment once
each, ascending; the roles by id, a missing one left out; no groups / no ids read nothing; and read_grants on the
stored documents: another group's role restricts, the user's grants
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import AccessGrants, TypeSet, read_grants
from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole, ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_GROUP_ID: int = 9621
SECOND_GROUP_ID: int = 9622
OTHER_GROUP_ID: int = 9623
VIEW_ROLE_ID: int = 9631
EDIT_ROLE_ID: int = 9632
OTHER_ROLE_ID: int = 9633
MISSING_ROLE_ID: int = 9639
SERVER_TYPE_ID: int = 9641
ROUTER_TYPE_ID: int = 9642
SWITCH_TYPE_ID: int = 9643


def _assignment(public_id: int, group_id: int, role_id: int) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': '*', 'description': ''}


def _role(public_id: int, types: list[int], operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'role-{public_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


@pytest.fixture(name='managers', autouse=True)
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """Four assignments - two groups of the user, one other group twice - and three roles"""
    database = database_manager.connector.client[database_name]
    assignments = database[CmdbAccessAssignment.COLLECTION]
    roles = database[CmdbScopeRole.COLLECTION]
    assignments.insert_many([
        _assignment(9654, OTHER_GROUP_ID, OTHER_ROLE_ID),
        _assignment(9651, FIRST_GROUP_ID, VIEW_ROLE_ID),
        _assignment(9652, SECOND_GROUP_ID, EDIT_ROLE_ID),
        _assignment(9653, OTHER_GROUP_ID, VIEW_ROLE_ID),
    ])
    roles.insert_many([
        _role(VIEW_ROLE_ID, [SERVER_TYPE_ID], ['view']),
        _role(EDIT_ROLE_ID, [ROUTER_TYPE_ID], ['view', 'edit']),
        _role(OTHER_ROLE_ID, [SWITCH_TYPE_ID], ['view']),
    ])

    yield {'assignments': AccessAssignmentsManager(database_manager),
           'roles': ScopeRolesManager(database_manager)}

    assignments.delete_many({})
    roles.delete_many({})


class TestManagerReads:
    """The three reads"""

    def test_the_assignments_of_several_groups(self, managers: dict[str, Any]) -> None:
        """Both groups' assignments, ascending; the other group's left out"""
        stored = managers['assignments'].assignments_of_groups([SECOND_GROUP_ID, FIRST_GROUP_ID])

        assert [assignment['public_id'] for assignment in stored] == [9651, 9652]
        assert '_id' not in stored[0]

    def test_no_groups_read_nothing(self, managers: dict[str, Any]) -> None:
        """An empty $in is never sent"""
        assert managers['assignments'].assignments_of_groups([]) == []

    def test_every_assignment(self, managers: dict[str, Any]) -> None:
        """All four, ascending, without _id"""
        stored = managers['assignments'].all_assignments()

        assert [assignment['public_id'] for assignment in stored] == [9651, 9652, 9653, 9654]
        assert '_id' not in stored[0]

    def test_every_assigned_role_once(self, managers: dict[str, Any]) -> None:
        """The view role is assigned twice"""
        assert managers['assignments'].assigned_role_ids() == [VIEW_ROLE_ID, EDIT_ROLE_ID, OTHER_ROLE_ID]

    def test_the_roles_by_id(self, managers: dict[str, Any]) -> None:
        """Ascending, a missing id left out, no _id"""
        stored = managers['roles'].roles_by_ids([OTHER_ROLE_ID, MISSING_ROLE_ID, VIEW_ROLE_ID])

        assert [role['public_id'] for role in stored] == [VIEW_ROLE_ID, OTHER_ROLE_ID]
        assert '_id' not in stored[0]

    def test_no_role_ids_read_nothing(self, managers: dict[str, Any]) -> None:
        """An empty $in is never sent"""
        assert managers['roles'].roles_by_ids([]) == []


class TestReadGrants:
    """read_grants on the stored documents"""

    def test_the_grants_of_a_user_in_two_groups(self, managers: dict[str, Any]) -> None:
        """View on servers and routers, edit on routers; switches restricted by the other group's role"""
        grants: AccessGrants = read_grants(managers['assignments'], managers['roles'],
                                           [FIRST_GROUP_ID, SECOND_GROUP_ID])

        assert grants.restricted == TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID, SWITCH_TYPE_ID])
        assert grants.allows(ScopeOperation.VIEW, SERVER_TYPE_ID)
        assert grants.allows(ScopeOperation.EDIT, ROUTER_TYPE_ID)
        assert not grants.allows(ScopeOperation.EDIT, SERVER_TYPE_ID)
        assert not grants.allows(ScopeOperation.VIEW, SWITCH_TYPE_ID)
        assert grants.granting_assignment_ids(ScopeOperation.VIEW, ROUTER_TYPE_ID) == [9652]
