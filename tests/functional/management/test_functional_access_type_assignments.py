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
Functional tests: ``GET /access/types/<id>/assignments`` - the assignments whose role covers a Type, each with its
role, through the real REST app

A role listing the Type and a role on every Type count; a role on another Type does not; ascending by assignment;
404 for a Type that does not exist; ``base.access.view`` needed
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.access_routes.type_assignment_routes import assignments_with_roles
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 97701
OTHER_TYPE_ID: int = 97702
MISSING_TYPE_ID: int = 97709
GROUP_ID: int = 97703
USER_ID: int = 97704
NAMING_ROLE: int = 97711
EVERY_TYPE_ROLE: int = 97712
OTHER_ROLE: int = 97713
URL: str = '/access/types/{type_id}/assignments'


def _role(public_id: int, types: Any) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'type-assignments-{public_id}', 'description': '', 'types': types,
            'operations': ['view'], 'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, role_id: int) -> dict[str, Any]:
    """A stored assignment of the group"""
    return {'public_id': public_id, 'group_id': GROUP_ID, 'role_id': role_id, 'scope': '*', 'description': ''}


ROLES: list[dict[str, Any]] = [_role(NAMING_ROLE, [TYPE_ID]), _role(EVERY_TYPE_ROLE, '*'),
                               _role(OTHER_ROLE, [OTHER_TYPE_ID])]
# Stored out of order: the answer is ascending
ASSIGNMENTS: list[dict[str, Any]] = [_assignment(97723, EVERY_TYPE_ROLE), _assignment(97721, NAMING_ROLE),
                                     _assignment(97722, OTHER_ROLE)]


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two Types, three roles, three assignments of one group, a user without the access view right"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_many([{'public_id': type_id, 'name': f'type-assignments-{type_id}',
                                                'label': 'T', 'fields': []} for type_id in (TYPE_ID, OTHER_TYPE_ID)])
    database[CmdbScopeRole.COLLECTION].insert_many([dict(role) for role in ROLES])
    database[CmdbAccessAssignment.COLLECTION].insert_many([dict(assignment) for assignment in ASSIGNMENTS])
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': GROUP_ID, 'name': 'type-assignments', 'label': 'G',
                                                   'rights': []})
    database[CmdbUser.COLLECTION].insert_one({'public_id': USER_ID, 'user_name': 'type-assignments', 'active': True,
                                              'group_ids': [GROUP_ID],
                                              'registration_time': datetime.now(timezone.utc)})

    yield database

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, OTHER_TYPE_ID]}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbUserGroup.COLLECTION].delete_one({'public_id': GROUP_ID})
    database[CmdbUser.COLLECTION].delete_one({'public_id': USER_ID})


def test_the_assignments_covering_the_type_with_their_roles(rest_api) -> None:
    """The naming role and the every-Type role; ascending; the role embedded"""
    response = rest_api.get(URL.format(type_id=TYPE_ID))
    result: dict[str, Any] = response.get_json()['result']

    assert response.status_code == HTTPStatus.OK
    assert result['type_id'] == TYPE_ID
    assert [(item['public_id'], item['role']['public_id']) for item in result['assignments']] == [
        (97721, NAMING_ROLE), (97723, EVERY_TYPE_ROLE)]
    assert result['assignments'][0] == {**ASSIGNMENTS[1], 'role': ROLES[0]}


def test_another_type_sees_its_own_and_the_every_type_role(rest_api) -> None:
    """The other Type"""
    result: dict[str, Any] = rest_api.get(URL.format(type_id=OTHER_TYPE_ID)).get_json()['result']

    assert [item['public_id'] for item in result['assignments']] == [97722, 97723]


def test_a_missing_type_is_a_404(rest_api) -> None:
    """Nothing to answer for"""
    assert rest_api.get(URL.format(type_id=MISSING_TYPE_ID)).status_code == HTTPStatus.NOT_FOUND


def test_the_access_view_right_is_needed(rest_api) -> None:
    """403 naming it"""
    caller = CmdbUser(public_id=USER_ID, user_name='type-assignments', active=True, group_ids=[GROUP_ID])
    response = rest_api.get(URL.format(type_id=TYPE_ID), user=caller)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert 'base.access.view' in response.get_json()['message']


def test_an_assignment_of_a_role_not_read_is_left_out() -> None:
    """assignments_with_roles - pure"""
    assert assignments_with_roles([_assignment(2, 99), _assignment(1, NAMING_ROLE)], [ROLES[0]]) == [
        {**_assignment(1, NAMING_ROLE), 'role': ROLES[0]}]
