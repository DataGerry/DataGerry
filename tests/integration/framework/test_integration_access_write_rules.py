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
Integration tests for the write rules of the access rules, against the test MongoDB

The reads behind the rules match what they should: a taken name is found and the updated role is left out of its own
clash; a Type id, a field class name, a group and a role count as known only when stored; an assignment clashes only
with the same group, role and scope - a scope stored in its canonical spelling matches a body spelled the other way
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_rules import (
    AccessRuleMessage,
    assignment_reference_problems,
    assignment_taken,
    canonical_scope,
    field_class_name_taken,
    scope_role_name_taken,
    scope_role_reference_problems,
)
from cmdb.manager import (
    AccessAssignmentsManager,
    FieldClassesManager,
    GroupsManager,
    ScopeRolesManager,
    TypesManager,
)
from cmdb.models.access_model import CmdbAccessAssignment, CmdbFieldClass, CmdbScopeRole
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9401
MISSING_TYPE_ID: int = 9409
HIDDEN_TYPE_ID: int = 9402
READER: CmdbUser = CmdbUser(public_id=9491, user_name='wr-reader', active=True, group_ids=[ADMIN_GROUP_ID])
# In no group holding an assignment: both seeded Types are restricted for it
OUTSIDER: CmdbUser = CmdbUser(public_id=9492, user_name='wr-outsider', active=True, group_ids=[9493])
ROLE_ID: int = 9411
OTHER_ROLE_ID: int = 9412
MISSING_ROLE_ID: int = 9419
MISSING_GROUP_ID: int = 9429
CLASS_NAME: str = 'wr-compliance'
ROLE_NAME: str = 'wr-operator'
CONDITION: dict[str, Any] = {'location': {'within': 3, 'depth': 2}}
CONDITION_OTHER_SPELLING: dict[str, Any] = {'location': {'depth': 2, 'within': 3}}


def _assignment(public_id: int, role_id: int, scope: Any) -> dict[str, Any]:
    """A stored assignment of the admin group"""
    return {'public_id': public_id, 'group_id': ADMIN_GROUP_ID, 'role_id': role_id, 'scope': scope, 'description': ''}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A Type, a field class, a role and two assignments - one under a condition stored canonically"""
    database = database_manager.connector.client[database_name]
    database[CmdbType.COLLECTION].insert_many([
        {'public_id': TYPE_ID, 'name': 'wr-type', 'label': 'wr', 'fields': []},
        {'public_id': HIDDEN_TYPE_ID, 'name': 'wr-hidden', 'label': 'hidden', 'fields': [],
         'acl': {'activated': True, 'groups': {'includes': {}}}},
    ])
    field_class: dict[str, Any] = {'public_id': 1, 'name': CLASS_NAME, 'label': 'C', 'description': ''}
    database[CmdbFieldClass.COLLECTION].insert_one(field_class)
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': ROLE_ID, 'name': ROLE_NAME, 'types': [TYPE_ID], 'operations': ['view']},
        {'public_id': OTHER_ROLE_ID, 'name': 'wr-other', 'types': '*', 'operations': []},
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(1, ROLE_ID, '*'),
        _assignment(2, OTHER_ROLE_ID, canonical_scope(CONDITION_OTHER_SPELLING)),
    ])

    yield

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, HIDDEN_TYPE_ID]}})

    for model in (CmdbFieldClass, CmdbScopeRole, CmdbAccessAssignment):
        database[model.COLLECTION].delete_many({})


def test_a_taken_class_name(database_manager: MongoDatabaseManager) -> None:
    """The stored name is taken, another is free"""
    manager = FieldClassesManager(database_manager)

    assert field_class_name_taken(manager, CLASS_NAME) is not None
    assert field_class_name_taken(manager, 'wr-free') is None


def test_a_role_does_not_clash_with_itself(database_manager: MongoDatabaseManager) -> None:
    """Another role's name is taken; the updated role keeps its own"""
    manager = ScopeRolesManager(database_manager)

    assert scope_role_name_taken(manager, ROLE_NAME, own_id=OTHER_ROLE_ID) is not None
    assert scope_role_name_taken(manager, ROLE_NAME, own_id=ROLE_ID) is None


@pytest.mark.usefixtures('rest_api_app_context')
def test_the_role_references(database_manager: MongoDatabaseManager) -> None:
    """A stored, readable Type and a stored class pass; a missing Type, a Type the caller may not read and a missing
    class are named - the hidden Type exactly like the missing one. The administrator names every stored Type"""
    types_manager, classes_manager = TypesManager(database_manager), FieldClassesManager(database_manager)
    role: dict[str, Any] = {'types': [TYPE_ID, HIDDEN_TYPE_ID, MISSING_TYPE_ID], 'field_classes': ['wr-none']}

    assert not scope_role_reference_problems({'types': [TYPE_ID], 'field_classes': [CLASS_NAME]}, types_manager,
                                             classes_manager, READER)
    assert scope_role_reference_problems(role, types_manager, classes_manager, OUTSIDER) == [
        AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[TYPE_ID, HIDDEN_TYPE_ID, MISSING_TYPE_ID]),
        AccessRuleMessage.UNKNOWN_FIELD_CLASSES.value.format(names=['wr-none']),
    ]
    assert scope_role_reference_problems(role, types_manager, classes_manager, READER) == [
        AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[MISSING_TYPE_ID]),
        AccessRuleMessage.UNKNOWN_FIELD_CLASSES.value.format(names=['wr-none']),
    ]


def test_the_assignment_references(database_manager: MongoDatabaseManager) -> None:
    """The seeded admin group and a stored role pass; missing ones are named"""
    groups_manager, roles_manager = GroupsManager(database_manager), ScopeRolesManager(database_manager)

    assert not assignment_reference_problems({'group_id': ADMIN_GROUP_ID, 'role_id': ROLE_ID}, groups_manager,
                                             roles_manager)
    assert len(assignment_reference_problems({'group_id': MISSING_GROUP_ID, 'role_id': MISSING_ROLE_ID},
                                             groups_manager, roles_manager)) == 2


class TestAssignmentClash:
    """Only the same group, role and scope clash."""

    def test_the_same_triple_clashes(self, database_manager: MongoDatabaseManager) -> None:
        """Admin + role + '*' is stored"""
        manager = AccessAssignmentsManager(database_manager)

        assert assignment_taken(manager, {'group_id': ADMIN_GROUP_ID, 'role_id': ROLE_ID, 'scope': '*'}) is not None

    def test_the_updated_assignment_does_not_clash_with_itself(self, database_manager: MongoDatabaseManager) -> None:
        """Its own id left out"""
        manager = AccessAssignmentsManager(database_manager)
        body: dict[str, Any] = {'group_id': ADMIN_GROUP_ID, 'role_id': ROLE_ID, 'scope': '*'}

        assert assignment_taken(manager, body, own_id=1) is None

    def test_another_role_or_scope_is_free(self, database_manager: MongoDatabaseManager) -> None:
        """Another role; the same role under a condition"""
        manager = AccessAssignmentsManager(database_manager)

        assert assignment_taken(manager, {'group_id': ADMIN_GROUP_ID, 'role_id': OTHER_ROLE_ID, 'scope': '*'}) is None
        assert assignment_taken(manager, {'group_id': ADMIN_GROUP_ID, 'role_id': ROLE_ID,
                                          'scope': canonical_scope(CONDITION)}) is None

    def test_a_scope_spelled_otherwise_clashes_once_canonical(self, database_manager: MongoDatabaseManager) -> None:
        """The stored canonical condition matches the canonical form of the other spelling - and not the raw one"""
        manager = AccessAssignmentsManager(database_manager)
        body: dict[str, Any] = {'group_id': ADMIN_GROUP_ID, 'role_id': OTHER_ROLE_ID}

        assert assignment_taken(manager, {**body, 'scope': canonical_scope(CONDITION)}) is not None
        assert assignment_taken(manager, {**body, 'scope': CONDITION}) is None
