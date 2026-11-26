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
Integration tests for access_routes.access_delegation against the test MongoDB

The real reads: the delegate's right (its group), the roles, the delegate's grants. A role beyond the delegate is
refused, one within passes; the roles the delegate may hand out are the ones within
"""
from http import HTTPStatus
from typing import Iterator

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.access_routes.access_delegation import (
    abort_unless_delegable,
    delegable_role_ids,
)
from cmdb.manager import ScopeRolesManager
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

DELEGATE_GROUP_ID: int = 9951
TYPE_IDS: list[int] = [9952, 9953]
WITHIN_ROLE_ID: int = 9954
BEYOND_ROLE_ID: int = 9955
DELEGATE: CmdbUser = CmdbUser(public_id=9956, user_name='delegation-int', active=True, group_ids=[DELEGATE_GROUP_ID])


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The delegate views the first Type; another group edits the second Type"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_one({'public_id': DELEGATE_GROUP_ID, 'name': 'delegation-int',
                                                   'label': 'D', 'rights': ['base.access.assignment.delegate']})
    database[CmdbType.COLLECTION].insert_many([{'public_id': type_id, 'name': f'delegation-int-{type_id}',
                                                'label': 'T', 'fields': []} for type_id in TYPE_IDS])
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': WITHIN_ROLE_ID, 'name': 'delegation-int-view', 'description': '', 'types': [TYPE_IDS[0]],
         'operations': ['view'], 'write_regular_fields': False, 'field_classes': []},
        {'public_id': BEYOND_ROLE_ID, 'name': 'delegation-int-edit', 'description': '', 'types': [TYPE_IDS[1]],
         'operations': ['edit'], 'write_regular_fields': False, 'field_classes': []},
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': 9957, 'group_id': DELEGATE_GROUP_ID, 'role_id': WITHIN_ROLE_ID, 'scope': '*', 'description': ''},
        # Another group holds the edit role, so the second Type is restricted - beyond the delegate
        {'public_id': 9958, 'group_id': 9959, 'role_id': BEYOND_ROLE_ID, 'scope': '*', 'description': ''},
    ])

    yield

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': DELEGATE_GROUP_ID})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def test_a_role_beyond_is_refused_and_one_within_passes() -> None:
    """Judged on the stored roles and the delegate's stored grants"""
    abort_unless_delegable(DELEGATE, [WITHIN_ROLE_ID])

    with pytest.raises(HTTPException) as raised:
        abort_unless_delegable(DELEGATE, [WITHIN_ROLE_ID, BEYOND_ROLE_ID])

    assert raised.value.code == HTTPStatus.FORBIDDEN


def test_the_delegable_roles(database_manager: MongoDatabaseManager) -> None:
    """Only the role within"""
    assert delegable_role_ids(DELEGATE, ScopeRolesManager(database_manager).all_roles()) == [WITHIN_ROLE_ID]
