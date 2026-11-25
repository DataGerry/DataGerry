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
Unit tests: the access engine fed by the translated type ACLs decides exactly as the type ACLs do

For generated scenarios (see tests/utils/type_acl_scenarios.py), every membership of up to three existing groups and
every permission list: each Type's answer of the type ACL (its own frozen reading ``acl_grants_access`` on the
stored ``acl``, every permission held - not the access helpers, which now ask the engine) equals the engine's
(``denied_types_of``), an object of a gone Type passes both, and the single-object decision (``decide``) for each
operation equals the type ACL's - an edit changing a field included. A user still carrying a deleted group
is the one intended difference (E7): the engine answers as the type ACL does for the user without that group
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    PERMISSION_OPERATIONS,
    AccessGrants,
    assignment_documents,
    build_grants,
    decide,
    denied_types_of,
    permission_operations,
    role_documents,
    translate_type_acls,
)
from cmdb.models.access_model import ScopeOperation
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.helpers import acl_grants_access
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_acl_scenarios import (
    EXISTING_GROUP_IDS,
    GONE_GROUP_ID,
    OPERATOR_GROUP_ID,
    PERMISSION_LISTS,
    USER_GROUP_SETS,
    scenario,
)
# -------------------------------------------------------------------------------------------------------------------- #

SCENARIO_COUNT: int = 150
TYPE_IDS: list[int] = [9901, 9902, 9903, 9904, 9905, 9906]
GONE_TYPE_ID: int = 9999
FIRST_ROLE_ID: int = 1
FIRST_ASSIGNMENT_ID: int = 1
MAX_REPORTED: int = 10


def _user(group_ids: tuple[int, ...]) -> CmdbUser:
    """A user in the given groups"""
    return CmdbUser(public_id=9941, user_name='equivalence', active=True, group_ids=list(group_ids))


def _engine_documents(types: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The scenario's type ACLs translated and numbered: (roles, assignments)"""
    roles = translate_type_acls(types, EXISTING_GROUP_IDS, ADMIN_GROUP_ID)

    return (role_documents(roles, FIRST_ROLE_ID),
            assignment_documents(roles, FIRST_ROLE_ID, FIRST_ASSIGNMENT_ID))


def _acl_allows(type_document: dict[str, Any], user: CmdbUser, permissions: list[AccessControlPermission]) -> bool:
    """
    The type ACL's answer, read by its own frozen rule - not through the access helpers, which ask the engine

    Args:
        type_document (dict[str, Any]): The CmdbType document; a missing ``acl`` grants everything
        user (CmdbUser): The user whose groups are judged
        permissions (list[AccessControlPermission]): Every permission that must be held

    Returns:
        bool: True when the type ACL grants every permission
    """
    acl: AccessControlList = AccessControlList.from_data(type_document.get(TypeSchemaKey.ACL.value) or {})

    return all(acl_grants_access(acl, user.group_ids, permission) for permission in permissions)


def _object_states(operation: ScopeOperation, type_id: int) -> dict[str, Any]:
    """The before / after an operation is judged on - an edit changes a field"""
    before: dict[str, Any] = {'public_id': 9951, 'type_id': type_id,
                              'fields': [{'name': 'hostname', 'value': 'old', 'type': 'text'}]}
    after: dict[str, Any] = {**before, 'fields': [{'name': 'hostname', 'value': 'new', 'type': 'text'}]}

    return {ScopeOperation.VIEW: {'before': before}, ScopeOperation.DELETE: {'before': before},
            ScopeOperation.CREATE: {'after': after}, ScopeOperation.EDIT: {'before': before, 'after': after}}[operation]


def _mismatches(types: list[dict[str, Any]], grants: AccessGrants, user: CmdbUser) -> list[str]:
    """Every answer of the engine that differs from the type ACL's, for one user"""
    found: list[str] = []

    for permissions in PERMISSION_LISTS:
        denied = denied_types_of(grants, permission_operations(permissions))
        names: list[str] = [permission.value for permission in permissions]

        for type_document in types:
            if _acl_allows(type_document, user, permissions) == denied.denies(type_document['public_id']):
                found.append(f"type {type_document['public_id']} {names} groups {user.group_ids}")

        if denied.denies(GONE_TYPE_ID):
            found.append(f'gone type {names} groups {user.group_ids}')

    for type_document in types:
        for permission, operation in PERMISSION_OPERATIONS.items():
            decided: bool = decide(grants, operation, **_object_states(operation, type_document['public_id'])).allowed

            if decided != _acl_allows(type_document, user, [permission]):
                found.append(f"decide {operation.value} type {type_document['public_id']} groups {user.group_ids}")

    return found


@pytest.mark.parametrize('number', range(SCENARIO_COUNT))
def test_the_engine_decides_as_the_type_acl(number: int) -> None:
    """Every membership, every permission list, every Type"""
    types: list[dict[str, Any]] = scenario(number, TYPE_IDS)
    roles, assignments = _engine_documents(types)
    found: list[str] = []

    for group_ids in USER_GROUP_SETS:
        found += _mismatches(types, build_grants(assignments, roles, group_ids), _user(group_ids))

    assert not found, f'scenario {number}: {found[:MAX_REPORTED]}'


def test_a_deleted_group_is_the_one_difference() -> None:
    """A user still carrying a gone group: the engine answers as the type ACL for the user without it - and the two
    differ somewhere, so the case is really exercised"""
    with_gone: tuple[int, ...] = (OPERATOR_GROUP_ID, GONE_GROUP_ID)
    differs: int = 0

    for number in range(SCENARIO_COUNT):
        types: list[dict[str, Any]] = scenario(number, TYPE_IDS)
        roles, assignments = _engine_documents(types)
        grants: AccessGrants = build_grants(assignments, roles, with_gone)

        assert not _mismatches(types, grants, _user((OPERATOR_GROUP_ID,))), f'scenario {number}'
        differs += len(_mismatches(types, grants, _user(with_gone)))

    assert differs
