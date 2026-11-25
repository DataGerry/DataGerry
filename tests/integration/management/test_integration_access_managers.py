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
Integration tests for the managers of the permission data model, against the test MongoDB

The CRUD of all three through GenericManager (a document stored, read back as the model, updated, deleted); the usage
reads find exactly the documents naming the class, Type, role or group, whole and in public_id order - a role
covering every Type names none; the Type pull leaves an emptied role in place and a second pull changes nothing; the
delete by ids removes exactly those and is re-run safe
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import AccessAssignmentsManager, FieldClassesManager, ScopeRolesManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbFieldClass, CmdbScopeRole
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9301
OTHER_TYPE_ID: int = 9302
GROUP_ID: int = 9311
OTHER_GROUP_ID: int = 9312
CLASS_NAME: str = 'it-compliance'
OTHER_CLASS_NAME: str = 'it-audit'

ROLE_BOTH_TYPES: int = 9321
ROLE_ONE_TYPE: int = 9322
ROLE_ALL_TYPES: int = 9323
ASSIGNMENT_A: int = 9331
ASSIGNMENT_B: int = 9332
ASSIGNMENT_OTHER: int = 9333
CLASS_ID: int = 9341
OTHER_CLASS_ID: int = 9342
NEW_ID: int = 9349


def _role(public_id: int, types: Any, classes: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'it-role-{public_id}', 'description': '', 'types': types,
            'operations': ['view'], 'write_regular_fields': False, 'field_classes': classes}


def _assignment(public_id: int, group_id: int, role_id: int) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': '*', 'description': ''}


ROLES: list[dict[str, Any]] = [
    _role(ROLE_ALL_TYPES, '*', [CLASS_NAME]),
    _role(ROLE_BOTH_TYPES, [TYPE_ID, OTHER_TYPE_ID], [CLASS_NAME, OTHER_CLASS_NAME]),
    _role(ROLE_ONE_TYPE, [TYPE_ID], []),
]
ASSIGNMENTS: list[dict[str, Any]] = [
    _assignment(ASSIGNMENT_A, GROUP_ID, ROLE_BOTH_TYPES),
    _assignment(ASSIGNMENT_B, GROUP_ID, ROLE_ONE_TYPE),
    _assignment(ASSIGNMENT_OTHER, OTHER_GROUP_ID, ROLE_BOTH_TYPES),
]
CLASSES: list[dict[str, Any]] = [
    {'public_id': CLASS_ID, 'name': CLASS_NAME, 'label': 'Compliance', 'description': ''},
    {'public_id': OTHER_CLASS_ID, 'name': OTHER_CLASS_NAME, 'label': 'Audit', 'description': ''},
]
SEEDED: list[tuple[str, list[dict[str, Any]]]] = [
    (CmdbFieldClass.COLLECTION, CLASSES),
    (CmdbScopeRole.COLLECTION, ROLES),
    (CmdbAccessAssignment.COLLECTION, ASSIGNMENTS),
]


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The three collections seeded - inserted as copies, so a test changing them leaves the constants alone"""
    collections: dict[str, Any] = {name: database_manager.get_collection(name, database_name) for name, _ in SEEDED}

    for name, documents in SEEDED:
        collections[name].delete_many({})
        collections[name].insert_many([dict(document) for document in documents])

    yield collections

    for name, _ in SEEDED:
        collections[name].delete_many({})


@pytest.fixture(name='roles')
def fixture_roles(database_manager: MongoDatabaseManager) -> ScopeRolesManager:
    """The scope roles manager on the test database"""
    return ScopeRolesManager(database_manager)


@pytest.fixture(name='assignments')
def fixture_assignments(database_manager: MongoDatabaseManager) -> AccessAssignmentsManager:
    """The assignments manager on the test database"""
    return AccessAssignmentsManager(database_manager)


def _ids(documents: list[dict[str, Any]]) -> list[int]:
    """The public_ids, in the order answered"""
    return [document['public_id'] for document in documents]


class TestCrud:
    """The generic CRUD carries the models."""

    def test_a_role_round_trips(self, roles: ScopeRolesManager) -> None:
        """Insert, read as the model, update, delete"""
        roles.insert_item(_role(NEW_ID, [TYPE_ID], [CLASS_NAME]))
        stored: CmdbScopeRole = roles.get_item(NEW_ID)

        assert (stored.types, stored.field_classes) == ([TYPE_ID], [CLASS_NAME])

        roles.update_item(NEW_ID, {**_role(NEW_ID, '*', []), 'operations': ['view', 'edit']})
        assert roles.get_item(NEW_ID, as_dict=True)['operations'] == ['view', 'edit']

        roles.delete_item(NEW_ID)
        assert roles.get_item(NEW_ID) is None

    def test_an_assignment_and_a_class_are_read_as_their_models(self, assignments: AccessAssignmentsManager,
                                                                database_manager: MongoDatabaseManager) -> None:
        """get_item answers the model"""
        stored: CmdbAccessAssignment = assignments.get_item(ASSIGNMENT_A)
        field_class: CmdbFieldClass = FieldClassesManager(database_manager).get_item(CLASS_ID)

        assert (stored.group_id, stored.role_id, stored.scope) == (GROUP_ID, ROLE_BOTH_TYPES, '*')
        assert (field_class.name, field_class.label) == (CLASS_NAME, 'Compliance')


def test_the_stored_class_names(database_manager: MongoDatabaseManager) -> None:
    """Only the stored ones; 'system' is never stored"""
    names: set[str] = FieldClassesManager(database_manager).find_existing_names([CLASS_NAME, 'system', 'unknown'])

    assert names == {CLASS_NAME}


class TestUsageReads:
    """Exactly the documents naming the entity, whole, ascending by public_id."""

    def test_the_roles_granting_a_class(self, roles: ScopeRolesManager) -> None:
        """The '*' role and the role listing it; not the role without classes"""
        found: list[dict[str, Any]] = roles.roles_granting_class(CLASS_NAME)

        assert _ids(found) == [ROLE_BOTH_TYPES, ROLE_ALL_TYPES]
        assert '_id' not in found[0]

    def test_the_roles_naming_a_type(self, roles: ScopeRolesManager) -> None:
        """A role covering every Type names none"""
        assert _ids(roles.roles_naming_type(TYPE_ID)) == [ROLE_BOTH_TYPES, ROLE_ONE_TYPE]
        assert _ids(roles.roles_naming_type(OTHER_TYPE_ID)) == [ROLE_BOTH_TYPES]

    def test_the_assignments_of_a_role_and_of_a_group(self, assignments: AccessAssignmentsManager) -> None:
        """Every group's assignment of the role; every role's assignment of the group"""
        assert _ids(assignments.assignments_of_role(ROLE_BOTH_TYPES)) == [ASSIGNMENT_A, ASSIGNMENT_OTHER]
        assert assignments.assignments_of_group(GROUP_ID) == [ASSIGNMENTS[0], ASSIGNMENTS[1]]


class TestPullTypeFromRoles:
    """One write over every role listing the Type."""

    def test_the_type_leaves_every_role_and_an_emptied_role_stays(self, roles: ScopeRolesManager,
                                                                  collections: dict[str, Any]) -> None:
        """Two roles changed; the one-Type role keeps existing with no Type; the '*' role untouched"""
        assert roles.pull_type_from_roles(TYPE_ID) == 2

        stored: dict[int, Any] = {role['public_id']: role['types']
                                  for role in collections[CmdbScopeRole.COLLECTION].find()}
        assert stored == {ROLE_ALL_TYPES: '*', ROLE_BOTH_TYPES: [OTHER_TYPE_ID], ROLE_ONE_TYPE: []}

    def test_a_second_pull_changes_nothing(self, roles: ScopeRolesManager) -> None:
        """Re-run safe"""
        roles.pull_type_from_roles(TYPE_ID)

        assert roles.pull_type_from_roles(TYPE_ID) == 0


class TestDeleteAssignmentsOfGroup:
    """One delete of exactly the given assignments."""

    def test_only_the_groups_assignments_go(self, assignments: AccessAssignmentsManager,
                                            collections: dict[str, Any]) -> None:
        """The other group's assignment stays"""
        assert assignments.delete_assignments([ASSIGNMENT_A, ASSIGNMENT_B]) == 2
        assert _ids(list(collections[CmdbAccessAssignment.COLLECTION].find())) == [ASSIGNMENT_OTHER]

    def test_a_second_delete_deletes_nothing(self, assignments: AccessAssignmentsManager) -> None:
        """Re-run safe"""
        assignments.delete_assignments([ASSIGNMENT_A, ASSIGNMENT_B])

        assert assignments.delete_assignments([ASSIGNMENT_A, ASSIGNMENT_B]) == 0
