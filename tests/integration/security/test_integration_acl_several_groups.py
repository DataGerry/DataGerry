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
Integration tests for the type ACL of a user in several user groups, against a real MongoDB

A user holds the union of their groups' ACL entries: a type is granted when the groups between them hold every asked
permission - one group may hold READ and another CREATE. The type ACL's own frozen listing reading
(``build_denied_types_criteria``) runs against seeded types; the access engine - fed the access rules the seeded ACLs
translate to - must answer alike, both as a listing (``build_permitted_types_criteria``) and per type
(``has_type_document_access``), for every type
"""
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.builder import build_denied_types_criteria, build_permitted_types_criteria
from cmdb.security.acl.helpers import has_type_document_access
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_access_seed import SeededAccess, remove_type_access, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

# The engine reads the stored access rules through the ManagerProvider - it needs the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

GROUP_A: int = 1
GROUP_B: int = 2
GROUP_C: int = 3
USER_GROUPS: list[int] = [GROUP_A, GROUP_B]

READ: str = AccessControlPermission.READ.value
CREATE: str = AccessControlPermission.CREATE.value

ONLY_A_READS: int = 96501
ONLY_B_READS: int = 96502
ONLY_C_READS: int = 96503
A_READS_B_CREATES: int = 96504
NOBODY_LISTED: int = 96505
SWITCHED_OFF: int = 96506
A_ONLY_CREATES: int = 96507

STORED_ACLS: dict[int, dict[str, Any]] = {
    ONLY_A_READS: {'activated': True, 'groups': {'includes': {str(GROUP_A): [READ]}}},
    ONLY_B_READS: {'activated': True, 'groups': {'includes': {str(GROUP_B): [READ]}}},
    ONLY_C_READS: {'activated': True, 'groups': {'includes': {str(GROUP_C): [READ]}}},
    A_READS_B_CREATES: {'activated': True, 'groups': {'includes': {str(GROUP_A): [READ], str(GROUP_B): [CREATE]}}},
    NOBODY_LISTED: {'activated': True, 'groups': {'includes': {}}},
    SWITCHED_OFF: {'activated': False, 'groups': {'includes': {str(GROUP_C): [READ]}}},
    A_ONLY_CREATES: {'activated': True, 'groups': {'includes': {str(GROUP_A): [CREATE]}}},
}
ALL_TYPE_IDS: list[int] = sorted(STORED_ACLS)

READ_ONLY: list[AccessControlPermission] = [AccessControlPermission.READ]
READ_AND_CREATE: list[AccessControlPermission] = [AccessControlPermission.READ, AccessControlPermission.CREATE]
READ_AND_UPDATE: list[AccessControlPermission] = [AccessControlPermission.READ, AccessControlPermission.UPDATE]

# What the user in groups A + B is denied, per asked permissions
EXPECTED_DENIED: list[tuple[list[AccessControlPermission], set[int]]] = [
    (READ_ONLY, {ONLY_C_READS, NOBODY_LISTED, A_ONLY_CREATES}),
    (READ_AND_CREATE, {ONLY_A_READS, ONLY_B_READS, ONLY_C_READS, NOBODY_LISTED, A_ONLY_CREATES}),
    (READ_AND_UPDATE, {ONLY_A_READS, ONLY_B_READS, ONLY_C_READS, A_READS_B_CREATES, NOBODY_LISTED, A_ONLY_CREATES}),
]
EXPECTED_DENIED_IDS: list[str] = ['read', 'read+create', 'read+update']


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The types collection holding the seeded types and the access rules they translate to, removed again afterwards"""
    collection: Any = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    collection.insert_many([{'public_id': type_id, 'acl': acl} for type_id, acl in STORED_ACLS.items()])
    database: Any = database_manager.connector.client[database_name]
    access: SeededAccess = store_type_access(database, ALL_TYPE_IDS)

    yield collection

    remove_type_access(database, access)
    collection.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


def _matching(types: Any, criteria: dict[str, Any]) -> set[int]:
    """The seeded types a criteria selects"""
    return {document['public_id'] for document in types.find(
        {'$and': [{'public_id': {'$in': ALL_TYPE_IDS}}, criteria]}, {'public_id': 1},
    )}


@pytest.mark.parametrize('permissions, expected', EXPECTED_DENIED, ids=EXPECTED_DENIED_IDS)
def test_the_groups_combine_in_the_listing(
        types: Any, permissions: list[AccessControlPermission], expected: set[int]) -> None:
    """Denied only what no group (READ) or no combination of groups (READ + CREATE) grants"""
    assert _matching(types, build_denied_types_criteria(USER_GROUPS, permissions)) == expected


@pytest.mark.parametrize('permissions, expected', EXPECTED_DENIED, ids=EXPECTED_DENIED_IDS)
def test_the_permitted_listing_is_the_complement(
        types: Any, permissions: list[AccessControlPermission], expected: set[int]) -> None:
    """The engine's listing permits exactly what the type ACL does not deny"""
    user: SimpleNamespace = SimpleNamespace(group_ids=USER_GROUPS)

    assert _matching(types, build_permitted_types_criteria(user, permissions)) == set(ALL_TYPE_IDS) - expected


@pytest.mark.parametrize('group_ids', [[GROUP_A], [GROUP_B], [GROUP_C], USER_GROUPS, [GROUP_A, GROUP_B, GROUP_C]],
                         ids=['a', 'b', 'c', 'a+b', 'a+b+c'])
@pytest.mark.parametrize('permission', list(AccessControlPermission), ids=lambda permission: permission.value)
def test_a_single_type_read_agrees_with_the_listing(
        types: Any, group_ids: list[int], permission: AccessControlPermission) -> None:
    """The engine's decision on one type document, its listing and the type ACL's listing never disagree, for any
    group set"""
    denied_by_listing: set[int] = _matching(types, build_denied_types_criteria(group_ids, permission))
    user: SimpleNamespace = SimpleNamespace(group_ids=group_ids)
    permitted_by_engine: set[int] = _matching(types, build_permitted_types_criteria(user, permission))

    denied_by_single_read: set[int] = {
        document['public_id'] for document in types.find({'public_id': {'$in': ALL_TYPE_IDS}})
        if not has_type_document_access(document, user, permission)
    }

    assert denied_by_listing == denied_by_single_read
    assert permitted_by_engine == set(ALL_TYPE_IDS) - denied_by_listing


def test_no_groups_are_a_valid_query_denying_every_activated_acl(types: Any) -> None:
    """MongoDB accepts the criteria; only the switched-off type is granted"""
    assert _matching(types, build_denied_types_criteria([], AccessControlPermission.READ)) == \
        set(ALL_TYPE_IDS) - {SWITCHED_OFF}
