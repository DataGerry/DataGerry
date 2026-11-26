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
The central filter functions of the access engine: which objects and Types a user may view, create, edit or delete,
from the user's grants read once per request

Each answers one shape a caller needs - the denied Type ids, a CmdbObject filter, a CmdbType filter, a yes / no for
one Type, the allowed operations per Type, the ``acl`` block per Type. Several operations asked at once must all be
held.

**Conditional assignments** (phase 9, R21-R26): ``scope_filter`` - the filter of the object lists - adds one clause per
conditional assignment (its Types AND its compiled scope) beside the Types granted in full. Everything Type-level stays
on the full grants - ``denied_types`` / ``denied_type_ids`` / ``type_allows`` / ``record_scope_filter`` treat a Type
held only conditionally as denied (fail closed: the id-list paths, history and the other collections, R25, R26) -
except the "on some objects" answers of R23: ``permitted_types_criteria`` (the Type lists), ``type_reachable`` and
``operations_on_types`` (``allowed_operations``)
"""
from collections.abc import Iterable
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine.access_denial import (
    DeniedTypes,
    denied_types_of,
    no_object_criteria,
    object_criteria,
    operations_allowed,
    type_criteria,
)
from cmdb.framework.access_engine.access_grants_reads import load_access_rules, load_grants
from cmdb.framework.access_engine.acl_synthesis import synthesised_acls
from cmdb.framework.access_engine.access_decision import can
from cmdb.framework.access_engine.access_denial import denied_for, operation_list
from cmdb.framework.access_engine.access_grants import AccessGrants
from cmdb.framework.access_engine.scope_evaluation import ScopeEvaluation, load_scope_evaluation
# -------------------------------------------------------------------------------------------------------------------- #


def denied_types(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation]) -> DeniedTypes:
    """
    The Types the user is denied some of the operations on

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        DeniedTypes: The denial
    """
    return denied_types_of(load_grants(user), operations)


def denied_type_ids(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation]) -> list[int]:
    """
    The ids of the Types the user is denied some of the operations on

    When every Type is restricted and the user is not granted every Type, the denial is "every Type but the granted
    ones", which a list can only spell by naming them: the existing Types are read (one distinct read) and so are the
    Type ids the objects carry (one distinct read on the ``type_id`` index) - an object whose Type is gone carries an id
    no Type has, and it is listed as denied too. So an exclusion by these ids, or a mask testing ``type_id in`` them,
    keeps such an object out like ``scope_filter`` does

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        TypesManagerGetError: When the Types could not be read
        BaseManagerGetError: When the objects' Type ids could not be read

    Returns:
        list[int]: The denied Type ids, ascending - gone Types' among them when every Type is restricted; empty when
            nothing is denied
    """
    denied: DeniedTypes = denied_types(user, operations)

    if denied.admitted is None:
        return sorted(denied.ids)

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, user)
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    known: set[int] = set(types_manager.get_all_type_ids()) | {
        type_id for type_id in objects_manager.get_distinct(CmdbObjectKey.TYPE_ID.value, {})
        if isinstance(type_id, int) and not isinstance(type_id, bool)}

    return sorted(type_id for type_id in known if denied.denies(type_id))


def scope_filter(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation],
                 type_id: int | None = None) -> dict[str, Any]:
    """
    The CmdbObject filter for the objects the user may perform the operations on - conditional assignments included

    Per operation: the objects of the Types granted in full (or unrestricted), or of a conditional assignment's Types
    where its condition matches; several operations must all hold (an ``$and`` of the per-operation filters)

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        type_id (int | None): The one Type the query reads, when it reads one; None for a query over every Type

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        dict[str, Any]: The filter - empty when nothing is denied (or the one Type is allowed), one no object
            matches when the one Type is denied outright
    """
    grants: AccessGrants = load_grants(user)
    listed: list[ScopeOperation] = operation_list(operations)

    if not any(grants.conditional_entries(operation, type_id) for operation in listed):
        return record_scope_filter(user, listed, type_id)

    evaluation: ScopeEvaluation = load_scope_evaluation(user, grants)
    parts: list[dict[str, Any]] = [part for part in (_operation_filter(grants, evaluation, operation, type_id)
                                                     for operation in listed) if part]

    if not parts:
        return {}

    return parts[0] if len(parts) == 1 else {'$and': parts}


def _operation_filter(grants: AccessGrants, evaluation: ScopeEvaluation, operation: ScopeOperation,
                      type_id: int | None) -> dict[str, Any]:
    """
    The object filter of one operation: the full grants, or a conditional assignment's Types and condition

    Args:
        grants (AccessGrants): The user's grants
        evaluation (ScopeEvaluation): The user's conditional assignments, compiled
        operation (ScopeOperation): The operation
        type_id (int | None): The one Type the query reads, or None

    Returns:
        dict[str, Any]: The filter; empty when the operation is allowed on every object read
    """
    denied: DeniedTypes = denied_for(grants, operation)

    if type_id is None:
        full: dict[str, Any] = object_criteria(denied)
    else:
        full = {} if not denied.denies(type_id) else no_object_criteria()

    if not full:
        return {}

    clauses: list[dict[str, Any]] = [full]

    for grant in evaluation.granting(operation, type_id):
        if type_id is not None or grant.entry.types.every_type:
            clauses.append(grant.criteria)
        else:
            clauses.append({'$and': [{CmdbObjectKey.TYPE_ID.value: {'$in': sorted(grant.entry.types.ids)}},
                                     grant.criteria]})

    return clauses[0] if len(clauses) == 1 else {'$or': clauses}


def record_scope_filter(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation],
                        type_id: int | None = None) -> dict[str, Any]:
    """
    The Type-only filter on a record's ``type_id`` - for what is no object (history, other collections): a Type held
    only conditionally is denied (fail closed, R26), since a record carries no object state to judge a condition on

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        type_id (int | None): The one Type the query reads, when it reads one; None for a query over every Type

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[str, Any]: The filter - empty when nothing is denied (or the one Type is allowed), one no record
            matches when the one Type is denied
    """
    denied: DeniedTypes = denied_types(user, operations)

    if type_id is None:
        return object_criteria(denied)

    return no_object_criteria() if denied.denies(type_id) else {}


def permitted_types_criteria(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation]
                             ) -> dict[str, Any]:
    """
    The CmdbType filter for the Types the user may perform the operations on - on at least some of their objects
    (R23) - for a query of ``framework.types``

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[str, Any]: The filter; empty when nothing is denied
    """
    return type_criteria(denied_types_of(load_grants(user), operations, reachable=True))


def type_allows(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation], type_id: int) -> bool:
    """
    Whether the user may perform the operations on the objects of a Type - and, with view, read its definition

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        type_id (int): The Type's public_id

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        bool: True when every operation is allowed
    """
    return not denied_types(user, operations).denies(type_id)


def type_reachable(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation], type_id: int) -> bool:
    """
    Whether the user may perform the operations on at least some objects of a Type - and read its definition (R23)

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        type_id (int): The Type's public_id

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        bool: True when every operation is granted on the Type in full or by a conditional assignment
    """
    return not denied_types_of(load_grants(user), operations, reachable=True).denies(type_id)


def operations_on_types(user: CmdbUser, type_ids: Iterable[int]) -> dict[int, list[ScopeOperation]]:
    """
    The operations the user may perform on each Type - what a screen shows or hides its buttons by

    Args:
        user (CmdbUser): The user the request is made for
        type_ids (Iterable[int]): The Types' public_ids

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[int, list[ScopeOperation]]: Per Type, the allowed operations in ScopeOperation order
    """
    return operations_allowed(load_grants(user), type_ids)


def allowed_operation_values(user: CmdbUser, type_ids: Iterable[int]) -> dict[int, list[str]]:
    """
    The operation values the user may perform on each Type - the answer form of ``operations_on_types``

    Args:
        user (CmdbUser): The user the request is made for
        type_ids (Iterable[int]): The Types' public_ids

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[int, list[str]]: Per Type, ``view`` / ``create`` / ``edit`` / ``delete`` as allowed, in that order
    """
    return {type_id: [operation.value for operation in operations]
            for type_id, operations in operations_on_types(user, type_ids).items()}


def synthesised_acl_values(user: CmdbUser, type_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """
    The ``acl`` block each Type answers with - as the access rules decide it, not as stored

    Args:
        user (CmdbUser): The user the request is made for - it names the tenant
        type_ids (Iterable[int]): The Types' public_ids

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the access rules could not be read

    Returns:
        dict[int, dict[str, Any]]: Per Type its block (``acl_synthesis.synthesised_acls``)
    """
    assignments, roles = load_access_rules(user)

    return synthesised_acls(type_ids, assignments, roles)


def object_operation_values(user: CmdbUser, document: dict[str, Any]) -> list[str]:
    """
    The operations the user may perform on one object - the render's ``allowed_operations`` (phase 9, R23): view, edit
    and delete judged on the object (its scope conditions included, an edit as keeping the object as it is), create on
    its Type ("on some objects")

    Args:
        user (CmdbUser): The user the request is made for
        document (dict[str, Any]): The CmdbObject document (``type_id`` and ``fields`` read)

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        list[str]: ``view`` / ``create`` / ``edit`` / ``delete`` as allowed, in that order
    """
    grants: AccessGrants = load_grants(user)
    type_id: Any = document.get(CmdbObjectKey.TYPE_ID.value)
    allowed: list[str] = []

    for operation in ScopeOperation:
        if operation is ScopeOperation.CREATE:
            permitted: bool = grants.may(operation, type_id)
        else:
            permitted = can(user, operation, document,
                            document if operation is ScopeOperation.EDIT else None).allowed

        if permitted:
            allowed.append(operation.value)

    return allowed
