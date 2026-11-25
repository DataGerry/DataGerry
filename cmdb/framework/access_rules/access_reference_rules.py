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
What the access rules keep from being deleted, and what goes with a deleted user group

A field class a scope role grants, and a scope role an assignment grants, are not deleted - the refusal names who
holds them. A user group's assignments go with it, inside the group delete's ledger
"""
from typing import Any

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.access_engine import forget_grants
from cmdb.manager.access_assignments_manager import AccessAssignmentsManager
from cmdb.manager.scope_roles_manager import ScopeRolesManager
from cmdb.models.access_model import FieldClassKey
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
# -------------------------------------------------------------------------------------------------------------------- #


def _public_ids(documents: list[dict[str, Any]]) -> list[int]:
    """
    The public_ids of documents, in their order

    Args:
        documents (list[dict[str, Any]]): The documents

    Returns:
        list[int]: Their public_ids
    """
    return [document[CmdbDAO.PUBLIC_ID_KEY] for document in documents]


def field_class_in_use(roles: ScopeRolesManager, field_class: dict[str, Any]) -> str | None:
    """
    Refuses deleting a field class a scope role grants - one read

    Args:
        roles (ScopeRolesManager): The scope roles of the request's database
        field_class (dict[str, Any]): The class as stored

    Raises:
        ScopeRolesManagerGetError: When the read fails

    Returns:
        str | None: The problem naming the roles, or None when no role grants it
    """
    name: str = field_class[FieldClassKey.NAME.value]
    granting: list[int] = _public_ids(roles.roles_granting_class(name))

    if granting:
        return AccessRuleMessage.FIELD_CLASS_IN_USE.value.format(name=name, role_ids=granting)

    return None


def scope_role_in_use(assignments: AccessAssignmentsManager, role_id: int) -> str | None:
    """
    Refuses deleting a scope role an assignment grants - one read

    Args:
        assignments (AccessAssignmentsManager): The assignments of the request's database
        role_id (int): The role's public_id

    Raises:
        AccessAssignmentsManagerGetError: When the read fails

    Returns:
        str | None: The problem naming the assignments, or None when none grants it
    """
    granting: list[int] = _public_ids(assignments.assignments_of_role(role_id))

    if granting:
        return AccessRuleMessage.SCOPE_ROLE_IN_USE.value.format(role_id=role_id, assignment_ids=granting)

    return None


def delete_group_assignments(ledger: WriteLedger, assignments: AccessAssignmentsManager, group_id: int) -> int:
    """
    Deletes a user group's assignments inside the group delete's ledger: recorded first, so a failure of this write
    or a later one puts back every assignment that went. One read, one write - the delete names the ids read, so an
    assignment written in between is not deleted without its record (it is left, as any write racing a delete)

    Args:
        ledger (WriteLedger): The group delete's ledger
        assignments (AccessAssignmentsManager): The assignments of the request's database
        group_id (int): The user group being deleted

    Raises:
        AccessAssignmentsManagerGetError: When the read fails
        AccessAssignmentsManagerDeleteError: When the delete fails

    Returns:
        int: How many assignments were deleted
    """
    priors: list[dict[str, Any]] = assignments.assignments_of_group(group_id, with_mongo_id=True)

    if not priors:
        return 0

    ledger.deleted_many(assignments, priors, AccessRuleMessage.GROUP_ASSIGNMENTS_DELETED.value.format(
        group_id=group_id))
    deleted: int = assignments.delete_assignments(_public_ids(priors))
    # The request's access grants are stale now
    forget_grants()

    return deleted
