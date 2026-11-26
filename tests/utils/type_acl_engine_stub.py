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
Lets a unit test's in-memory Types decide access through their type ACLs - the engine stubbed

A unit test of a caller (a filter, a refusal) that hands Type documents carrying an ``acl`` around without a database
calls ``decide_by_type_acls(monkeypatch, documents)``: the access engine's ``type_allows``, ``type_reachable``,
``denied_type_ids``, ``scope_filter``, ``permitted_types_criteria`` and ``can`` (each state judged by its Type) then
answer from those ACLs, read by the type ACL's own frozen rule
(``acl_grants_access``). The engine itself is proven to decide alike (``test_type_acl_equivalence``); here only the
caller is under test. A Type not registered is unrestricted.

``decide_without_assignments(monkeypatch)`` lets the engine's own reads - ``can()`` (the object write check) and
``allowed_operation_values`` (a Type answer's ``allowed_operations``) - run without a database: no assignment exists, so
every Type is unrestricted, every operation allowed and every field writable. For unit tests whose subject is not
access (the write funnels, the importer, the render, the Type routes)
"""
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.framework import access_engine
from cmdb.framework.access_engine import (
    OPERATION_PERMISSIONS,
    AccessGrants,
    access_decision,
    access_filters,
    build_grants,
    operation_list,
)
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.helpers import acl_grants_access
from cmdb.interface.rest_api.routes.access_routes import access_scope_guard
# -------------------------------------------------------------------------------------------------------------------- #


def decide_by_type_acls(monkeypatch: pytest.MonkeyPatch, type_documents: Iterable[Mapping[str, Any]]) -> None:
    """
    Makes the access engine answer from the given Types' ACLs for the rest of the test

    Args:
        monkeypatch (pytest.MonkeyPatch): The test's monkeypatch
        type_documents (Iterable[Mapping[str, Any]]): The Types (``public_id`` and ``acl`` are read)
    """
    acls: dict[Any, Any] = {document.get(TypeSchemaKey.PUBLIC_ID.value): document.get(TypeSchemaKey.ACL.value)
                            for document in type_documents}

    def type_allows(user: Any, operations: Any, type_id: Any) -> bool:
        """The ACL's answer, every operation held"""
        acl: AccessControlList = AccessControlList.from_data(acls.get(type_id) or {})

        return all(acl_grants_access(acl, user.group_ids, OPERATION_PERMISSIONS[operation])
                   for operation in operation_list(operations))

    def denied_type_ids(user: Any, operations: Any) -> list[int]:
        """The registered Types denied"""
        return sorted(type_id for type_id in acls if not type_allows(user, operations, type_id))

    def scope_filter(user: Any, operations: Any, type_id: Any = None) -> dict[str, Any]:
        """An exclusion of the denied Types; for one Type none or one matching nothing"""
        if type_id is not None:
            return {} if type_allows(user, operations, type_id) else {CmdbObjectKey.TYPE_ID.value: {'$in': []}}

        denied: list[int] = denied_type_ids(user, operations)

        return {CmdbObjectKey.TYPE_ID.value: {'$nin': denied}} if denied else {}

    def permitted_types_criteria(user: Any, operations: Any) -> dict[str, Any]:
        """The same exclusion on the Types' own key"""
        denied: list[int] = denied_type_ids(user, operations)

        return {TypeSchemaKey.PUBLIC_ID.value: {'$nin': denied}} if denied else {}

    def can(user: Any, operation: Any, before: Any = None, after: Any = None) -> SimpleNamespace:
        """Every state's Type must allow the operation"""
        states: list[Any] = [state for state in (before, after) if state is not None]

        return SimpleNamespace(allowed=all(type_allows(user, operation, state.get(CmdbObjectKey.TYPE_ID.value))
                                           for state in states))

    monkeypatch.setattr(access_engine, 'type_allows', type_allows)
    monkeypatch.setattr(access_engine, 'type_reachable', type_allows)
    monkeypatch.setattr(access_engine, 'can', can)
    monkeypatch.setattr(access_engine, 'denied_type_ids', denied_type_ids)
    monkeypatch.setattr(access_engine, 'scope_filter', scope_filter)
    monkeypatch.setattr(access_engine, 'permitted_types_criteria', permitted_types_criteria)
    no_conditional_assignments(monkeypatch)


def decide_without_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Makes ``can()``, the operations answer and the synthesised ``acl`` answer read grants without any assignment for the
    rest of the test - every Type unrestricted

    Args:
        monkeypatch (pytest.MonkeyPatch): The test's monkeypatch
    """
    no_assignments: AccessGrants = build_grants([], [], [])
    monkeypatch.setattr(access_decision, 'load_grants', lambda _user: no_assignments)
    monkeypatch.setattr(access_filters, 'load_grants', lambda _user: no_assignments)
    monkeypatch.setattr(access_filters, 'load_access_rules', lambda _user: ([], []))
    no_conditional_assignments(monkeypatch)


def no_conditional_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Makes the stale-scope guards (``access_scope_guard``) read no conditional assignment - nothing to judge, nothing
    more read

    Args:
        monkeypatch (pytest.MonkeyPatch): The test's monkeypatch
    """
    monkeypatch.setattr(access_scope_guard, '_conditional_assignments', lambda _user: [])

