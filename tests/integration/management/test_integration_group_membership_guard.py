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
Integration tests for group_membership_guard.abort_if_adding_groups_beyond against the test MongoDB

The real reads: the added groups, their assignments and roles, the caller's rights and grants. A group whose
assignment views a Type the caller may not is refused with that reach; one holding an unheld right with it; a group
whose assignment the caller holds itself passes; an administrator passes
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
from cmdb.interface.rest_api.routes.user_management_routes.group_membership_guard import (
    abort_if_adding_groups_beyond,
)
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    MEMBERSHIP_BEYOND_MSG,
    MEMBERSHIP_GROUP_PART,
    MEMBERSHIP_PART_SEPARATOR,
    MEMBERSHIP_RIGHTS_PART,
)
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

CALLER_GROUP_ID: int = 9911
REACHING_GROUP_ID: int = 9912
SHARED_GROUP_ID: int = 9913
GROUP_IDS: list[int] = [CALLER_GROUP_ID, REACHING_GROUP_ID, SHARED_GROUP_ID]
TYPE_ID: int = 9914
VIEW_ROLE_ID: int = 9915
UNHELD_RIGHT: str = 'base.framework.type.edit'
CALLER: CmdbUser = CmdbUser(public_id=9916, user_name='guard-caller', active=True, group_ids=[CALLER_GROUP_ID])
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=9917, user_name='guard-admin', active=True, group_ids=[1])


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """One view role on a Type: REACHING holds it (plus an unheld right), the caller does not; SHARED and the caller
    hold nothing beyond each other"""
    database = database_manager.connector.client[database_name]
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': CALLER_GROUP_ID, 'name': 'guard-caller', 'label': 'C', 'rights': []},
        {'public_id': REACHING_GROUP_ID, 'name': 'guard-reaching', 'label': 'R', 'rights': [UNHELD_RIGHT]},
        {'public_id': SHARED_GROUP_ID, 'name': 'guard-shared', 'label': 'S', 'rights': []},
    ])
    database[CmdbType.COLLECTION].insert_one({'public_id': TYPE_ID, 'name': 'guard-type', 'label': 'T', 'fields': []})
    database[CmdbScopeRole.COLLECTION].insert_one({'public_id': VIEW_ROLE_ID, 'name': 'guard-view', 'description': '',
                                                   'types': [TYPE_ID], 'operations': ['view'],
                                                   'write_regular_fields': False, 'field_classes': []})
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': 9918, 'group_id': REACHING_GROUP_ID,
                                                          'role_id': VIEW_ROLE_ID, 'scope': '*', 'description': ''})

    yield

    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': GROUP_IDS}})
    database[CmdbType.COLLECTION].delete_many({'public_id': TYPE_ID})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def test_a_reaching_group_is_refused_with_both_parts() -> None:
    """The unheld right, then the view the caller lacks"""
    with pytest.raises(HTTPException) as raised:
        abort_if_adding_groups_beyond(CALLER, [SHARED_GROUP_ID, REACHING_GROUP_ID])

    beyond: str = MEMBERSHIP_PART_SEPARATOR.join([MEMBERSHIP_RIGHTS_PART.format(names=[UNHELD_RIGHT]),
                                                  f'view on Types [{TYPE_ID}]'])
    assert raised.value.code == HTTPStatus.FORBIDDEN
    assert raised.value.description == MEMBERSHIP_BEYOND_MSG.format(
        details=MEMBERSHIP_GROUP_PART.format(group_id=REACHING_GROUP_ID, beyond=beyond))


@pytest.mark.parametrize('caller, group_ids', [(CALLER, [SHARED_GROUP_ID]), (ADMINISTRATOR, [REACHING_GROUP_ID])],
                         ids=['within-reach', 'administrator'])
def test_passes(caller: CmdbUser, group_ids: list[int]) -> None:
    """Nothing beyond, or an administrator"""
    abort_if_adding_groups_beyond(caller, group_ids)


def test_a_caller_holding_the_view_passes_the_reach(database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
    """The caller's group gains the same assignment - only the unheld right is left"""
    database = database_manager.connector.client[database_name]
    database[CmdbAccessAssignment.COLLECTION].insert_one({'public_id': 9919, 'group_id': CALLER_GROUP_ID,
                                                          'role_id': VIEW_ROLE_ID, 'scope': '*', 'description': ''})

    with pytest.raises(HTTPException) as raised:
        abort_if_adding_groups_beyond(CALLER, [REACHING_GROUP_ID])

    assert raised.value.description == MEMBERSHIP_BEYOND_MSG.format(details=MEMBERSHIP_GROUP_PART.format(
        group_id=REACHING_GROUP_ID, beyond=MEMBERSHIP_RIGHTS_PART.format(names=[UNHELD_RIGHT])))
