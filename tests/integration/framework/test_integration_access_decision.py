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
Integration tests for can(), against the test MongoDB through ManagerProvider

Stored roles and assignments: the user views and edits the Type but writes no regular field - an unchanged edit
passes, a changed one is refused with the field; another group's Type is denied; a trace names the stored assignment
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import AccessDecision, AccessDecisionStep, can
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole, ScopeOperation
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

OWN_TYPE_ID: int = 9801
OTHER_TYPE_ID: int = 9802
USER_GROUP_ID: int = 9811
OTHER_GROUP_ID: int = 9812
OWN_ASSIGNMENT_ID: int = 9831
USER: CmdbUser = CmdbUser(public_id=9841, user_name='access-can', active=True, group_ids=[USER_GROUP_ID])


@pytest.fixture(autouse=True)
def fixture_access(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The user's role views and edits its Type without writing fields; another group's role restricts the other"""
    database = database_manager.connector.client[database_name]
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': 9821, 'name': 'own', 'types': [OWN_TYPE_ID], 'operations': ['view', 'edit'],
         'write_regular_fields': False, 'field_classes': []},
        {'public_id': 9822, 'name': 'other', 'types': [OTHER_TYPE_ID], 'operations': ['view'],
         'write_regular_fields': True, 'field_classes': []},
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': OWN_ASSIGNMENT_ID, 'group_id': USER_GROUP_ID, 'role_id': 9821, 'scope': '*'},
        {'public_id': 9832, 'group_id': OTHER_GROUP_ID, 'role_id': 9822, 'scope': '*'},
    ])

    yield

    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _object(type_id: int, hostname: str) -> dict[str, Any]:
    """An object with one field"""
    return {'public_id': 9851, 'type_id': type_id, 'fields': [{'name': 'hostname', 'value': hostname,
                                                               'type': 'text'}]}


def test_view_on_the_own_type_and_not_on_the_other() -> None:
    """The other group's role restricts the other Type"""
    assert can(USER, ScopeOperation.VIEW, before=_object(OWN_TYPE_ID, 'a')).allowed
    assert not can(USER, ScopeOperation.VIEW, before=_object(OTHER_TYPE_ID, 'a')).allowed


def test_an_edit_passes_unchanged_and_is_refused_changed() -> None:
    """No regular field may be written"""
    assert can(USER, ScopeOperation.EDIT, _object(OWN_TYPE_ID, 'a'), _object(OWN_TYPE_ID, 'a')).allowed

    decision: AccessDecision = can(USER, ScopeOperation.EDIT, _object(OWN_TYPE_ID, 'a'), _object(OWN_TYPE_ID, 'b'))

    assert (decision.allowed, decision.step, decision.refused_fields) == (
        False, AccessDecisionStep.FIELD_CLASS, ('hostname',))


def test_a_trace_names_the_stored_assignment() -> None:
    """The one granting view"""
    decision: AccessDecision = can(USER, ScopeOperation.VIEW, before=_object(OWN_TYPE_ID, 'a'), trace=True)

    assert decision.assignment_ids == (OWN_ASSIGNMENT_ID,)
