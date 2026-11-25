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
The type ACL migration's plan - its self-check and its report, pure, no reads

Before the migration writes a role, the engine is run on the translated roles and assignments in memory and asked
what the stored ACLs answer: every Type, every permission, for each existing user group alone and for a user in no
group. Both sides grant a user the union of its groups per permission, so a user in several groups is answered by
these alone. Any Type where they differ stops the migration (``acl_differences``). The report records, per Type
whose ACL was activated, the ACL as stored, the roles and assignments made from it and the groups it named that did
not exist; the planned documents themselves ride along, so a run stopped half-way finishes with exactly them
"""
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime
from typing import Any

from cmdb.models.access_model import (
    AccessAssignmentKey,
    MigrationReportKey,
    MigrationReportStatus,
    MigrationReportTypeKey,
    ScopeRoleKey,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_groups import acl_group_ids
from cmdb.security.acl.helpers import acl_grants_access
from cmdb.framework.access_engine.access_engine_constants import PERMISSION_OPERATIONS
from cmdb.framework.access_engine.access_grants import AccessGrants, build_grants
from cmdb.framework.access_engine.type_acl_translation import acl_is_activated
# -------------------------------------------------------------------------------------------------------------------- #


def type_id_of(type_document: Mapping[str, Any]) -> int | None:
    """
    A stored Type's public_id, when it is one - a Type without an int id cannot be decided by id and is passed over

    Args:
        type_document (Mapping[str, Any]): The stored Type

    Returns:
        int | None: The id, or None
    """
    type_id: Any = type_document.get(TypeSchemaKey.PUBLIC_ID.value)

    return type_id if isinstance(type_id, int) and not isinstance(type_id, bool) else None


def acl_allows(type_document: Mapping[str, Any], group_ids: Collection[int], permission: Any) -> bool:
    """
    What a Type's stored ACL answers a user in the given groups, by the ACL's own frozen reading

    Args:
        type_document (Mapping[str, Any]): The stored Type
        group_ids (Collection[int]): The user's groups
        permission (Any): An ``AccessControlPermission``

    Returns:
        bool: True when the ACL grants it
    """
    stored: Any = type_document.get(TypeSchemaKey.ACL.value)
    acl: AccessControlList = AccessControlList.from_data(stored if isinstance(stored, dict) else {})

    return acl_grants_access(acl, group_ids, permission)


def acl_differences(type_documents: Iterable[Mapping[str, Any]], existing_group_ids: Collection[int],
                    roles: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> list[int]:
    """
    The Types where the engine on the translated roles and assignments answers otherwise than the stored ACLs

    Asked for a user in no group and for each existing group alone, every permission

    Args:
        type_documents (Iterable[Mapping[str, Any]]): The stored Types (public_id and acl are read)
        existing_group_ids (Collection[int]): Every group that exists
        roles (list[dict[str, Any]]): The translated role documents - every one is assigned
        assignments (list[dict[str, Any]]): The translated assignment documents

    Returns:
        list[int]: The differing Types, ascending; empty when the translation decides alike
    """
    decided: list[tuple[int, Mapping[str, Any]]] = [
        (type_id, document) for document in type_documents if (type_id := type_id_of(document)) is not None]
    users: list[tuple[int, ...]] = [()] + [(group_id,) for group_id in sorted(existing_group_ids)]
    differing: set[int] = set()

    for group_ids in users:
        grants: AccessGrants = build_grants(assignments, roles, group_ids)

        for type_id, document in decided:
            if type_id in differing:
                continue

            for permission, operation in PERMISSION_OPERATIONS.items():
                if acl_allows(document, group_ids, permission) != grants.allows(operation, type_id):
                    differing.add(type_id)
                    break

    return sorted(differing)


def type_entries(type_documents: Iterable[Mapping[str, Any]], existing_group_ids: Collection[int],
                 roles: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The report's entry for each Type whose ACL was activated: the ACL, the roles and assignments made from it, the
    groups it named that did not exist

    Args:
        type_documents (Iterable[Mapping[str, Any]]): The stored Types
        existing_group_ids (Collection[int]): Every group that exists
        roles (list[dict[str, Any]]): The translated role documents
        assignments (list[dict[str, Any]]): The translated assignment documents

    Returns:
        list[dict[str, Any]]: One ``MigrationReportTypeKey`` entry per Type, ascending by Type
    """
    existing: set[int] = set(existing_group_ids)
    entries: list[dict[str, Any]] = []

    for document in type_documents:
        type_id: int | None = type_id_of(document)

        if type_id is None or not acl_is_activated(document):
            continue

        role_ids: list[int] = [role[ScopeRoleKey.PUBLIC_ID.value] for role in roles
                               if type_id in role[ScopeRoleKey.TYPES.value]]
        entries.append({
            MigrationReportTypeKey.TYPE_ID.value: type_id,
            MigrationReportTypeKey.ACL.value: document.get(TypeSchemaKey.ACL.value),
            MigrationReportTypeKey.ROLE_IDS.value: role_ids,
            MigrationReportTypeKey.ASSIGNMENT_IDS.value: [
                assignment[AccessAssignmentKey.PUBLIC_ID.value] for assignment in assignments
                if assignment[AccessAssignmentKey.ROLE_ID.value] in role_ids],
            MigrationReportTypeKey.DROPPED_GROUP_IDS.value: [
                group_id for group_id in acl_group_ids(document.get(TypeSchemaKey.ACL.value))
                if group_id not in existing],
        })

    return sorted(entries, key=lambda entry: entry[MigrationReportTypeKey.TYPE_ID.value])


def inactive_type_ids(type_documents: Iterable[Mapping[str, Any]]) -> list[int]:
    """
    The Types whose ACL is absent or not activated - unrestricted before and after the migration

    Args:
        type_documents (Iterable[Mapping[str, Any]]): The stored Types

    Returns:
        list[int]: Their ids, ascending
    """
    return sorted(type_id for document in type_documents
                  if (type_id := type_id_of(document)) is not None and not acl_is_activated(document))


def pending_report(type_documents: list[Mapping[str, Any]], existing_group_ids: Collection[int],
                   documents: tuple[list[dict[str, Any]], list[dict[str, Any]]], started_at: datetime
                   ) -> dict[str, Any]:
    """
    The report as it is written before any role is stored - pending, the planned documents in it

    Args:
        type_documents (list[Mapping[str, Any]]): The stored Types
        existing_group_ids (Collection[int]): Every group that exists
        documents (tuple[list[dict[str, Any]], list[dict[str, Any]]]): The planned role and assignment documents
        started_at (datetime): When the migration checked its translation (UTC)

    Returns:
        dict[str, Any]: The report, without its ``_id``
    """
    roles, assignments = documents

    return {
        MigrationReportKey.STATUS.value: MigrationReportStatus.PENDING.value,
        MigrationReportKey.STARTED_AT.value: started_at,
        MigrationReportKey.EXISTING_GROUP_IDS.value: sorted(existing_group_ids),
        MigrationReportKey.TYPES.value: type_entries(type_documents, existing_group_ids, roles, assignments),
        MigrationReportKey.INACTIVE_TYPE_IDS.value: inactive_type_ids(type_documents),
        MigrationReportKey.ROLES.value: roles,
        MigrationReportKey.ASSIGNMENTS.value: assignments,
    }
