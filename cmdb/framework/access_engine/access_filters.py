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
held. With only the
unconditional scope there is, the filters work on Type ids; a scope condition will add object criteria here
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
    The CmdbObject filter for the objects the user may perform the operations on

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        type_id (int | None): The one Type the query reads, when it reads one; None for a query over every Type

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[str, Any]: The filter - empty when nothing is denied (or the one Type is allowed), one no object
            matches when the one Type is denied
    """
    denied: DeniedTypes = denied_types(user, operations)

    if type_id is None:
        return object_criteria(denied)

    return no_object_criteria() if denied.denies(type_id) else {}


def permitted_types_criteria(user: CmdbUser, operations: ScopeOperation | Iterable[ScopeOperation]
                             ) -> dict[str, Any]:
    """
    The CmdbType filter for the Types the user may perform the operations on - for a query of ``framework.types``

    Args:
        user (CmdbUser): The user the request is made for
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held

    Raises:
        ValueError: When no operation is given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read

    Returns:
        dict[str, Any]: The filter; empty when nothing is denied
    """
    return type_criteria(denied_types(user, operations))


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
