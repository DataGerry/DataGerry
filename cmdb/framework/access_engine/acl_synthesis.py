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
A Type's ``acl`` block as the access rules decide it - what every answer carrying ``acl`` shows instead of the stored
block, which decides nothing since the engine does. Pure, no reads

A Type no assigned role names is unrestricted: the default block, switched off. A restricted one is switched on, and
lists each user group holding an operation on it through an unconditional assignment, with the permissions those
operations were in the type ACL (view READ, create CREATE, edit UPDATE, delete DELETE). A role on every Type counts
for each Type. A group holding nothing on the Type is not listed
"""
from collections.abc import Iterable, Mapping
from typing import Any

from cmdb.models.access_model import AccessAssignmentKey, ScopeOperation, ScopeRoleKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
from cmdb.framework.access_engine.access_engine_constants import OPERATION_PERMISSIONS
from cmdb.framework.access_engine.access_grants import GrantEntry, grant_entries, restricted_types
from cmdb.framework.access_engine.access_type_set import TypeSet
# -------------------------------------------------------------------------------------------------------------------- #


def group_entries(assignments: Iterable[Mapping[str, Any]], assigned_roles: Iterable[Mapping[str, Any]]
                  ) -> dict[int, tuple[GrantEntry, ...]]:
    """
    Every group's granting assignments, read with their roles - the engine's own reading per group

    Args:
        assignments (Iterable[Mapping[str, Any]]): Every stored assignment
        assigned_roles (Iterable[Mapping[str, Any]]): The roles those assignments grant

    Returns:
        dict[int, tuple[GrantEntry, ...]]: Per group id, ascending, its grant entries
    """
    listed: list[Mapping[str, Any]] = list(assignments)
    roles_by_id: dict[int, Mapping[str, Any]] = {role[ScopeRoleKey.PUBLIC_ID.value]: role for role in assigned_roles}
    group_ids: list[int] = sorted({assignment[AccessAssignmentKey.GROUP_ID.value] for assignment in listed})

    return {group_id: grant_entries(listed, roles_by_id, [group_id]) for group_id in group_ids}


def held_permission_values(entries: Iterable[GrantEntry], type_id: int) -> list[str]:
    """
    The type ACL permission values a group's entries grant on a Type, in operation order

    Args:
        entries (Iterable[GrantEntry]): One group's grant entries
        type_id (int): The Type

    Returns:
        list[str]: E.g. ``['READ', 'UPDATE']``; empty when the group holds nothing on it
    """
    listed: list[GrantEntry] = list(entries)

    return [OPERATION_PERMISSIONS[operation].value for operation in ScopeOperation
            if any(entry.grants(operation, type_id) for entry in listed)]


def synthesised_acls(type_ids: Iterable[int], assignments: Iterable[Mapping[str, Any]],
                     assigned_roles: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    The ``acl`` block of each Type as the stored assignments and roles decide it

    Args:
        type_ids (Iterable[int]): The Types
        assignments (Iterable[Mapping[str, Any]]): Every stored assignment
        assigned_roles (Iterable[Mapping[str, Any]]): The roles those assignments grant

    Returns:
        dict[int, dict[str, Any]]: Per Type its block - ``{'activated': ..., 'groups': {'includes': {...}}}``
    """
    roles: list[Mapping[str, Any]] = list(assigned_roles)
    restricted: TypeSet = restricted_types(roles)
    entries: dict[int, tuple[GrantEntry, ...]] = group_entries(assignments, roles)
    blocks: dict[int, dict[str, Any]] = {}

    for type_id in type_ids:
        if not restricted.contains(type_id):
            blocks[type_id] = AccessControlList.default_json()
            continue

        includes: dict[str, list[str]] = {}

        for group_id, group_grants in entries.items():
            values: list[str] = held_permission_values(group_grants, type_id)

            if values:
                includes[str(group_id)] = values

        blocks[type_id] = {AclKey.ACTIVATED.value: True, AclKey.GROUPS.value: {AclKey.INCLUDES.value: includes}}

    return blocks
