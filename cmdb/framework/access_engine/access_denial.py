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
Which CmdbTypes a user's grants deny for some operations, and the filters that keep them out - pure, no reads

A Type is denied an operation when it is restricted and not granted it. When every Type is restricted (a role on
every Type is assigned) and the user is not granted every Type, the denial is the complement of the granted Types:
the filters then admit the granted Types (``$in``) instead of excluding the denied ones (``$nin``), so an object whose
Type is gone is denied too. Several operations asked at once must all be granted - a Type denied any one is denied
"""
from collections.abc import Iterable
from dataclasses import dataclass

from cmdb.models.access_model import ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.access_engine.access_engine_constants import PERMISSION_OPERATIONS
from cmdb.framework.access_engine.access_grants import AccessGrants
from cmdb.framework.access_engine.access_type_set import TypeSet
# -------------------------------------------------------------------------------------------------------------------- #

# The message of an empty operation list - it would deny every restricted Type rather than restrict nothing
NO_OPERATION_MESSAGE: str = 'At least one operation is required to decide access!'


@dataclass(frozen=True)
class DeniedTypes:
    """
    The Types denied: the listed ones, or every Type but the admitted ones

    Attributes:
        ids (frozenset[int]): The denied Types, when ``admitted`` is None
        admitted (frozenset[int] | None): When not None, every Type is denied except these - ``ids`` is then empty
    """
    ids: frozenset[int] = frozenset()
    admitted: frozenset[int] | None = None

    def denies(self, type_id: int) -> bool:
        """
        Whether a Type is denied

        Args:
            type_id (int): The Type's public_id

        Returns:
            bool: True when it is
        """
        if self.admitted is not None:
            return type_id not in self.admitted

        return type_id in self.ids

    def denies_nothing(self) -> bool:
        """
        Whether no Type is denied

        Returns:
            bool: True when nothing is listed and not every Type is denied
        """
        return self.admitted is None and not self.ids

    def union(self, other: 'DeniedTypes') -> 'DeniedTypes':
        """
        What both deny

        Args:
            other (DeniedTypes): The other denial

        Returns:
            DeniedTypes: The listed ids of both; with a complement, the Types admitted by it and denied by neither
        """
        if self.admitted is not None and other.admitted is not None:
            return DeniedTypes(admitted=self.admitted & other.admitted)

        if self.admitted is not None:
            return DeniedTypes(admitted=self.admitted - other.ids)

        if other.admitted is not None:
            return DeniedTypes(admitted=other.admitted - self.ids)

        return DeniedTypes(ids=self.ids | other.ids)


def operation_list(operations: ScopeOperation | Iterable[ScopeOperation]) -> list[ScopeOperation]:
    """
    One operation or several as a list, in the given order, each once

    Args:
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held

    Raises:
        ValueError: When no operation is given - nothing asked would deny every restricted Type

    Returns:
        list[ScopeOperation]: The operations
    """
    listed: list[ScopeOperation] = [operations] if isinstance(operations, ScopeOperation) else list(operations)

    if not listed:
        raise ValueError(NO_OPERATION_MESSAGE)

    return list(dict.fromkeys(listed))


def permission_operations(permissions: AccessControlPermission | Iterable[AccessControlPermission]
                          ) -> list[ScopeOperation]:
    """
    Reads type ACL permissions as the scope operations they are - what a caller asking in ACL terms hands the engine

    Args:
        permissions (AccessControlPermission | Iterable[AccessControlPermission]): One permission or several

    Raises:
        ValueError: When no permission is given

    Returns:
        list[ScopeOperation]: The operations, in the given order, each once
    """
    listed: list[AccessControlPermission] = (
        [permissions] if isinstance(permissions, AccessControlPermission) else list(permissions)
    )

    return operation_list(PERMISSION_OPERATIONS[permission] for permission in listed)


def denied_for(grants: AccessGrants, operation: ScopeOperation, reachable: bool = False) -> DeniedTypes:
    """
    The Types the grants deny one operation on: restricted and not granted

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The operation
        reachable (bool): Whether a Type granted only conditionally counts as granted - the Type-level "on some
            objects" answer (R23); by default it is denied (fail closed, R25)

    Returns:
        DeniedTypes: The denial
    """
    granted: TypeSet = grants.reachable.get(operation, grants.granted[operation]) if reachable \
        else grants.granted[operation]

    if granted.every_type:
        return DeniedTypes()

    if grants.restricted.every_type:
        return DeniedTypes(admitted=granted.ids)

    return DeniedTypes(ids=grants.restricted.ids - granted.ids)


def denied_types_of(grants: AccessGrants, operations: ScopeOperation | Iterable[ScopeOperation],
                    reachable: bool = False) -> DeniedTypes:
    """
    The Types the grants deny some of the operations on - every operation must be granted

    Args:
        grants (AccessGrants): The user's grants
        operations (ScopeOperation | Iterable[ScopeOperation]): The operation, or every operation that must be held
        reachable (bool): Whether a conditionally granted Type counts as granted (``denied_for``)

    Raises:
        ValueError: When no operation is given

    Returns:
        DeniedTypes: The union of the denials
    """
    denied: DeniedTypes = DeniedTypes()

    for operation in operation_list(operations):
        denied = denied.union(denied_for(grants, operation, reachable))

    return denied


def object_criteria(denied: DeniedTypes) -> dict[str, dict[str, list[int]]]:
    """
    The CmdbObject filter keeping the denied Types out

    Args:
        denied (DeniedTypes): The denial

    Returns:
        dict[str, dict[str, list[int]]]: Empty when nothing is denied; ``type_id $in`` the admitted Types for a
            complement (an object of a gone Type is out); else ``type_id $nin`` the denied ones
    """
    return id_criteria(CmdbObjectKey.TYPE_ID.value, denied)


def type_criteria(denied: DeniedTypes) -> dict[str, dict[str, list[int]]]:
    """
    The CmdbType filter keeping the denied Types out - for a query of ``framework.types`` itself

    Args:
        denied (DeniedTypes): The denial

    Returns:
        dict[str, dict[str, list[int]]]: Empty when nothing is denied, else ``public_id $in`` / ``$nin``
    """
    return id_criteria(TypeSchemaKey.PUBLIC_ID.value, denied)


def id_criteria(key: str, denied: DeniedTypes) -> dict[str, dict[str, list[int]]]:
    """
    The filter on a Type id key keeping the denied Types out - any key holding a Type id, a stamped one included (a
    relation log's two sides). With a complement a document without the key, or with null, is kept out too - the
    reading of ``DeniedTypes.denies(None)``

    Args:
        key (str): The key holding the Type id
        denied (DeniedTypes): The denial

    Returns:
        dict[str, dict[str, list[int]]]: The filter, ids ascending; empty when nothing is denied
    """
    if denied.admitted is not None:
        return {key: {'$in': sorted(denied.admitted)}}

    if denied.ids:
        return {key: {'$nin': sorted(denied.ids)}}

    return {}


def no_object_criteria() -> dict[str, dict[str, list[int]]]:
    """
    A CmdbObject filter no object matches - the answer for a Type that is denied

    Returns:
        dict[str, dict[str, list[int]]]: ``type_id $in []``
    """
    return {CmdbObjectKey.TYPE_ID.value: {'$in': []}}


def operations_allowed(grants: AccessGrants, type_ids: Iterable[int]) -> dict[int, list[ScopeOperation]]:
    """
    The operations the grants allow on each Type - on at least some of its objects (R23): a conditional grant counts

    Args:
        grants (AccessGrants): The user's grants
        type_ids (Iterable[int]): The Types' public_ids

    Returns:
        dict[int, list[ScopeOperation]]: Per Type, the allowed operations in ScopeOperation order
    """
    return {
        type_id: [operation for operation in ScopeOperation if grants.may(operation, type_id)]
        for type_id in type_ids
    }
