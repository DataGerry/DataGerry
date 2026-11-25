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
Integration tests: a boot builds the three collections of the permission data model with their indexes

On a scratch database (the session database never runs the collection validator): the user-management pass creates
the field class, scope role and assignment collections, each index the models declare exists, the unique ones refuse
a second document, and a second boot changes nothing
"""
from typing import Any, Iterator

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.models.access_model import (
    ASSIGNMENT_UNIQUE_INDEX_NAME,
    AccessAssignmentKey,
    CmdbAccessAssignment,
    CmdbFieldClass,
    CmdbScopeRole,
    FieldClassKey,
    ScopeRoleKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-access-collections'
MODELS: list[Any] = [CmdbFieldClass, CmdbScopeRole, CmdbAccessAssignment]
MODEL_IDS: list[str] = ['field-class', 'scope-role', 'assignment']
CLASS: dict[str, Any] = {FieldClassKey.PUBLIC_ID.value: 1, FieldClassKey.NAME.value: 'compliance'}
ROLE: dict[str, Any] = {ScopeRoleKey.PUBLIC_ID.value: 1, ScopeRoleKey.NAME.value: 'Operator'}
ASSIGNMENT: dict[str, Any] = {AccessAssignmentKey.PUBLIC_ID.value: 1, AccessAssignmentKey.GROUP_ID.value: 4,
                              AccessAssignmentKey.ROLE_ID.value: 9, AccessAssignmentKey.SCOPE.value: '*'}
SECOND_ID: int = 2


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """An empty scratch database, booted once, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    CollectionValidator(scratch, database_manager).init_management_collections()

    yield scratch

    client.drop_database(scratch)


def _index_names(database_manager: MongoDatabaseManager, scratch: str, model: Any) -> set[str]:
    """The names of the indexes the collection carries, without '_id_'"""
    return set(database_manager.get_collection(model.COLLECTION, scratch).index_information()) - {'_id_'}


@pytest.mark.parametrize('model', MODELS, ids=MODEL_IDS)
def test_every_declared_index_is_built(database_manager: MongoDatabaseManager, scratch: str, model: Any) -> None:
    """The collection exists with exactly the declared indexes"""
    declared: set[str] = {index.document['name'] for index in model.get_index_keys()}

    assert _index_names(database_manager, scratch, model) == declared


@pytest.mark.parametrize('model', MODELS, ids=MODEL_IDS)
def test_a_second_boot_changes_nothing(database_manager: MongoDatabaseManager, scratch: str, model: Any) -> None:
    """Index reconciliation is additive and finds nothing to add"""
    before: set[str] = _index_names(database_manager, scratch, model)
    CollectionValidator(scratch, database_manager).init_management_collections()

    assert _index_names(database_manager, scratch, model) == before


@pytest.mark.parametrize('model, document', [
    (CmdbFieldClass, CLASS),
    (CmdbScopeRole, ROLE),
    (CmdbAccessAssignment, ASSIGNMENT),
], ids=['class-name', 'role-name', ASSIGNMENT_UNIQUE_INDEX_NAME])
def test_the_unique_index_refuses_a_second_document(database_manager: MongoDatabaseManager, scratch: str, model: Any,
                                                    document: dict[str, Any]) -> None:
    """Same name / same group, role and scope under another public_id"""
    collection = database_manager.get_collection(model.COLLECTION, scratch)
    collection.insert_one(dict(document))

    with pytest.raises(DuplicateKeyError):
        collection.insert_one({**document, 'public_id': SECOND_ID})


def test_another_scope_role_for_the_group_is_stored(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Only the triple is unique - the same group with another role is a second assignment"""
    collection = database_manager.get_collection(CmdbAccessAssignment.COLLECTION, scratch)
    collection.insert_one(dict(ASSIGNMENT))
    collection.insert_one({**ASSIGNMENT, 'public_id': SECOND_ID, AccessAssignmentKey.ROLE_ID.value: SECOND_ID})

    group: dict[str, Any] = {AccessAssignmentKey.GROUP_ID.value: ASSIGNMENT[AccessAssignmentKey.GROUP_ID.value]}

    assert collection.count_documents(group) == 2
