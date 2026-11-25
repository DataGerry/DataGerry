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
What a user may do on which CmdbTypes, worked out from the stored assignments and scope roles - pure, no reads

A Type is **restricted** when the role of some assignment - any group's - names it; a role naming every Type restricts
every Type. A restricted Type allows an operation only through an assignment of one of the user's groups whose role
names the Type and lists the operation; the assignments add up and never deny. An unrestricted Type allows everything
to everyone. Admins are not exempt
"""
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from cmdb.models.access_model import AccessAssignmentKey, ScopeOperation, ScopeRoleKey, UNCONDITIONAL_SCOPE
from cmdb.framework.access_engine.access_type_set import TypeSet
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GrantEntry:
    """
    One assignment of the user's groups, read together with its scope role

    Attributes:
        assignment_id (int): The assignment's public_id
        role_id (int): Its scope role's public_id
        types (TypeSet): The Types the role names
        operations (frozenset[ScopeOperation]): The operations the role lists
        write_regular_fields (bool): Whether the role may write the fields carrying no field class
    """
    assignment_id: int
    role_id: int
    types: TypeSet
    operations: frozenset[ScopeOperation]
    write_regular_fields: bool

    def grants(self, operation: ScopeOperation, type_id: int) -> bool:
        """
        Whether this assignment grants an operation on a Type

        Args:
            operation (ScopeOperation): The operation
            type_id (int): The Type's public_id

        Returns:
            bool: True when the role lists the operation and names the Type
        """
        return operation in self.operations and self.types.contains(type_id)


@dataclass(frozen=True)
class AccessGrants:
    """
    The Types restricted by any assignment and what the user's own assignments grant on them

    Attributes:
        restricted (TypeSet): The Types some assignment restricts
        granted (Mapping[ScopeOperation, TypeSet]): Per operation, the Types the user's assignments grant it on
        regular_write (Mapping[ScopeOperation, TypeSet]): Per operation, the Types where a role granting it may also
            write the fields carrying no field class
        entries (tuple[GrantEntry, ...]): The user's assignments with their roles, ascending by assignment id
    """
    restricted: TypeSet
    granted: Mapping[ScopeOperation, TypeSet]
    regular_write: Mapping[ScopeOperation, TypeSet]
    entries: tuple[GrantEntry, ...]

    def is_restricted(self, type_id: int) -> bool:
        """
        Whether some assignment restricts a Type

        Args:
            type_id (int): The Type's public_id

        Returns:
            bool: True when a role of some assignment names it
        """
        return self.restricted.contains(type_id)

    def allows(self, operation: ScopeOperation, type_id: int) -> bool:
        """
        Whether the user may perform an operation on the objects of a Type

        Args:
            operation (ScopeOperation): The operation
            type_id (int): The Type's public_id

        Returns:
            bool: True for an unrestricted Type, else when one of the user's assignments grants the operation
        """
        return not self.is_restricted(type_id) or self.granted[operation].contains(type_id)

    def writes_regular_fields(self, operation: ScopeOperation, type_id: int) -> bool:
        """
        Whether the user, performing an operation on a Type, may write the fields carrying no field class

        Only a role granting that very operation counts - a role that lists view alone writes no field, whatever its
        ``write_regular_fields`` says

        Args:
            operation (ScopeOperation): The operation
            type_id (int): The Type's public_id

        Returns:
            bool: True for an unrestricted Type, else when a role granting the operation on it writes regular fields
        """
        return not self.is_restricted(type_id) or self.regular_write[operation].contains(type_id)

    def granting_assignment_ids(self, operation: ScopeOperation, type_id: int) -> list[int]:
        """
        The user's assignments granting an operation on a Type - what a trace names

        Args:
            operation (ScopeOperation): The operation
            type_id (int): The Type's public_id

        Returns:
            list[int]: Their public_ids, ascending; empty when none grants it
        """
        return [entry.assignment_id for entry in self.entries if entry.grants(operation, type_id)]


def role_operations(role: Mapping[str, Any]) -> frozenset[ScopeOperation]:
    """
    Reads a stored scope role's operations; a value that is no operation is passed over (it grants nothing)

    Args:
        role (Mapping[str, Any]): The stored scope role

    Returns:
        frozenset[ScopeOperation]: The operations it lists
    """
    stored: Any = role.get(ScopeRoleKey.OPERATIONS.value)

    if not isinstance(stored, list):
        return frozenset()

    return frozenset(operation for operation in ScopeOperation if operation.value in stored)


def restricted_types(assigned_roles: Iterable[Mapping[str, Any]]) -> TypeSet:
    """
    The Types the assigned scope roles restrict

    Args:
        assigned_roles (Iterable[Mapping[str, Any]]): Every scope role some assignment grants - any group's

    Returns:
        TypeSet: Every Type when one of them names every Type, else the Types they name together
    """
    return TypeSet.union_of(TypeSet.from_role_types(role.get(ScopeRoleKey.TYPES.value)) for role in assigned_roles)


def grant_entries(user_assignments: Iterable[Mapping[str, Any]],
                  roles_by_id: Mapping[int, Mapping[str, Any]],
                  group_ids: Collection[int]) -> tuple[GrantEntry, ...]:
    """
    Reads the assignments of the user's groups together with their scope roles

    An assignment of another group, one whose role is not among the roles read, or one whose scope is not the
    unconditional scope (the only one there is yet) grants nothing and is passed over - fail closed

    Args:
        user_assignments (Iterable[Mapping[str, Any]]): The stored assignments of the user's groups
        roles_by_id (Mapping[int, Mapping[str, Any]]): The assigned scope roles by public_id
        group_ids (Collection[int]): The user's group ids

    Returns:
        tuple[GrantEntry, ...]: The granting assignments, ascending by public_id
    """
    groups: set[int] = set(group_ids)
    entries: list[GrantEntry] = []

    for assignment in user_assignments:
        role: Mapping[str, Any] | None = roles_by_id.get(assignment.get(AccessAssignmentKey.ROLE_ID.value))

        if (assignment.get(AccessAssignmentKey.GROUP_ID.value) not in groups or role is None
                or assignment.get(AccessAssignmentKey.SCOPE.value) != UNCONDITIONAL_SCOPE):
            continue

        entries.append(GrantEntry(
            assignment_id=assignment[AccessAssignmentKey.PUBLIC_ID.value],
            role_id=role[ScopeRoleKey.PUBLIC_ID.value],
            types=TypeSet.from_role_types(role.get(ScopeRoleKey.TYPES.value)),
            operations=role_operations(role),
            write_regular_fields=role.get(ScopeRoleKey.WRITE_REGULAR_FIELDS.value) is True,
        ))

    return tuple(sorted(entries, key=lambda entry: entry.assignment_id))


def build_grants(user_assignments: Iterable[Mapping[str, Any]],
                 assigned_roles: Iterable[Mapping[str, Any]],
                 group_ids: Collection[int]) -> AccessGrants:
    """
    Works out what a user may do from the stored assignments and scope roles

    Args:
        user_assignments (Iterable[Mapping[str, Any]]): The stored assignments of the user's groups
        assigned_roles (Iterable[Mapping[str, Any]]): Every scope role some assignment grants - any group's, since
            each of them restricts its Types for everyone
        group_ids (Collection[int]): The user's group ids - no groups grant nothing

    Returns:
        AccessGrants: The restricted Types and the user's grants on them
    """
    roles: list[Mapping[str, Any]] = list(assigned_roles)
    roles_by_id: dict[int, Mapping[str, Any]] = {role[ScopeRoleKey.PUBLIC_ID.value]: role for role in roles}
    entries: tuple[GrantEntry, ...] = grant_entries(user_assignments, roles_by_id, group_ids)

    granted: dict[ScopeOperation, TypeSet] = {}
    regular_write: dict[ScopeOperation, TypeSet] = {}

    for operation in ScopeOperation:
        granting: list[GrantEntry] = [entry for entry in entries if operation in entry.operations]
        granted[operation] = TypeSet.union_of(entry.types for entry in granting)
        regular_write[operation] = TypeSet.union_of(entry.types for entry in granting if entry.write_regular_fields)

    return AccessGrants(
        restricted=restricted_types(roles),
        granted=MappingProxyType(granted),
        regular_write=MappingProxyType(regular_write),
        entries=entries,
    )
