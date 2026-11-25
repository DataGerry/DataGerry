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
Integration tests: on the test MongoDB, the access engine fed by the translated type ACLs filters exactly as the type
ACL does

Per generated scenario the Types, an object of each and an object of a gone Type are stored, and the translated
roles and assignments with them. For every membership and permission list, the type ACL's query (the denied Types read
with ``build_denied_types_criteria``, the objects excluded by ``build_denied_types_condition``) and the engine's
(``scope_filter``, ``denied_type_ids``) answer the same objects and the same denied Types
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import (
    assignment_documents,
    denied_type_ids,
    permission_operations,
    role_documents,
    scope_filter,
    translate_type_acls,
)
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import build_denied_types_condition, build_denied_types_criteria
from tests.utils.type_acl_scenarios import EXISTING_GROUP_IDS, PERMISSION_LISTS, USER_GROUP_SETS, scenario
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

SCENARIO_COUNT: int = 20
TYPE_IDS: list[int] = [9961, 9962, 9963, 9964]
GONE_TYPE_ID: int = 9969
OBJECT_IDS: dict[int, int] = {9971: 9961, 9972: 9962, 9973: 9963, 9974: 9964, 9979: GONE_TYPE_ID}
FIRST_ROLE_ID: int = 1
FIRST_ASSIGNMENT_ID: int = 1
MAX_REPORTED: int = 10


@pytest.fixture(name='database')
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The test database; everything a scenario stored is removed afterwards"""
    database = database_manager.connector.client[database_name]

    yield database

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': list(OBJECT_IDS)}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _store(database: Any, number: int) -> None:
    """A scenario's Types, the objects and the translated roles and assignments"""
    types: list[dict[str, Any]] = scenario(number, TYPE_IDS)
    roles = translate_type_acls(types, EXISTING_GROUP_IDS, ADMIN_GROUP_ID)
    database[CmdbType.COLLECTION].insert_many(types)
    objects: list[dict[str, Any]] = [{'public_id': object_id, 'type_id': type_id, 'fields': []}
                                     for object_id, type_id in OBJECT_IDS.items()]
    database[CmdbObject.COLLECTION].insert_many(objects)

    if roles:
        database[CmdbScopeRole.COLLECTION].insert_many(role_documents(roles, FIRST_ROLE_ID))
        database[CmdbAccessAssignment.COLLECTION].insert_many(
            assignment_documents(roles, FIRST_ROLE_ID, FIRST_ASSIGNMENT_ID))


def _object_ids(database: Any, criteria: dict[str, Any]) -> list[int]:
    """The scenario's objects the criteria let through"""
    found = database[CmdbObject.COLLECTION].find({'$and': [{'public_id': {'$in': list(OBJECT_IDS)}}, criteria]})

    return sorted(document['public_id'] for document in found)


def _acl_denied_type_ids(database: Any, user: CmdbUser, permissions: list[Any]) -> list[int]:
    """The scenario's Types the type ACL denies, read as the type ACL reads them"""
    criteria: dict[str, Any] = {'$and': [build_denied_types_criteria(user.group_ids, permissions),
                                         {'public_id': {'$in': TYPE_IDS}}]}

    return sorted(document['public_id'] for document in database[CmdbType.COLLECTION].find(criteria))


@pytest.mark.parametrize('number', range(SCENARIO_COUNT))
def test_the_engine_filters_as_the_type_acl(database: Any, number: int) -> None:
    """Same objects, same denied Types - for every membership and permission list"""
    _store(database, number)
    found: list[str] = []

    for group_ids in USER_GROUP_SETS:
        user: CmdbUser = CmdbUser(public_id=9981, user_name='equivalence', active=True, group_ids=list(group_ids))

        for permissions in PERMISSION_LISTS:
            operations = permission_operations(permissions)
            acl_denied: list[int] = _acl_denied_type_ids(database, user, permissions)
            engine_denied: list[int] = [type_id for type_id in denied_type_ids(user, operations)
                                        if type_id in TYPE_IDS]
            acl_objects: list[int] = _object_ids(database, build_denied_types_condition(acl_denied))
            engine_objects: list[int] = _object_ids(database, scope_filter(user, operations))

            if (acl_denied, acl_objects) != (engine_denied, engine_objects):
                found.append(f'groups {list(group_ids)} {[permission.value for permission in permissions]}: '
                             f'acl {acl_denied} {acl_objects} engine {engine_denied} {engine_objects}')

    assert not found, f'scenario {number}: {found[:MAX_REPORTED]}'
