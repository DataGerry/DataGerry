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
A type write may carry its ``acl`` only unchanged - access is managed through the access rules; and its fields' class
and audit flag only as stored - the Field Protection routes set them (phase 12, ``guard_field_protection``)

The stored ``acl`` decides nothing since the access engine does, and every answer shows the block the access rules
decide (``types_operations_helper.with_synthesised_acl``). A client sending a Type back (the type builder sends the
whole document) is accepted when its ``acl`` means what that answer meant: on a create the default block, on an update
the synthesised one. Any other ``acl`` is refused (400) - it would change nothing and say otherwise. What is stored is
the server's: a new Type stores the default block, an updated one keeps its stored block (written back as the model
normalises it)

Two blocks mean the same when both are switched off, or both are switched on and each group holds the same
permissions - the order of the permissions, a group listed with none, and the groups of a switched-off block do not
count
"""
from typing import Any

from flask import abort

from cmdb.framework.access_engine import synthesised_acl_values
from cmdb.framework.access_rules.field_protection_rules import protection_problems, template_owned_field_names
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.acl_groups import group_permissions
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['acl_meaning', 'guard_created_acl', 'guard_updated_acl', 'guard_field_protection']

AclMeaning = tuple[bool, dict[int, frozenset[str]]]


def acl_meaning(acl: Any) -> AclMeaning:
    """
    What an ``acl`` block means: whether it is switched on and, when it is, what each group holds

    Args:
        acl (Any): The block as sent or answered

    Returns:
        AclMeaning: ``(activated, {group: permissions})`` - only groups holding a permission, nothing when switched off
    """
    if not isinstance(acl, dict) or acl.get(AclKey.ACTIVATED.value) is not True:
        return False, {}

    return True, {group_id: frozenset(values) for group_id, values in group_permissions(acl).items() if values}


def abort_if_acl_changed(data: dict[str, Any], answered: dict[str, Any]) -> None:
    """
    Refuses a payload whose ``acl`` means something else than the block its Type answers with

    Args:
        data (dict[str, Any]): The type payload; no ``acl`` sends nothing to judge
        answered (dict[str, Any]): The block the Type answers with

    Raises:
        HTTPException: 400 when the meanings differ
    """
    if TypeSchemaKey.ACL.value in data and acl_meaning(data[TypeSchemaKey.ACL.value]) != acl_meaning(answered):
        abort(400, TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE)


def guard_created_acl(data: dict[str, Any]) -> None:
    """
    Accepts a new Type's ``acl`` only when it means the default, then stores the default block

    Args:
        data (dict[str, Any]): The create payload, changed in place

    Raises:
        HTTPException: 400 when the payload's ``acl`` means something else
    """
    default: dict[str, Any] = AccessControlList.default_json()
    abort_if_acl_changed(data, default)
    data[TypeSchemaKey.ACL.value] = default


def guard_updated_acl(data: dict[str, Any], old_type: CmdbType, request_user: CmdbUser) -> None:
    """
    Accepts an update's ``acl`` only when it means the block the Type answers with, then keeps the stored block

    Args:
        data (dict[str, Any]): The update payload, changed in place
        old_type (CmdbType): The stored Type
        request_user (CmdbUser): The caller - it names the tenant whose access rules decide

    Raises:
        HTTPException: 400 when the payload's ``acl`` means something else
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the access rules could not be read
    """
    if TypeSchemaKey.ACL.value in data:
        answered: dict[str, Any] = synthesised_acl_values(request_user, [old_type.public_id])[old_type.public_id]
        abort_if_acl_changed(data, answered)

    data[TypeSchemaKey.ACL.value] = AccessControlList.to_json(old_type.acl)


def guard_field_protection(data: dict[str, Any], old_type: CmdbType | None = None) -> None:
    """
    Accepts the field classes and audit flags of a type write only as stored, then keeps the stored ones (phase 12)

    Args:
        data (dict[str, Any]): The type payload after the template reconciliation, changed in place
        old_type (CmdbType | None): The stored Type; None for a create

    Raises:
        HTTPException: 400 naming each field sending another class or flag than stored
    """
    problems: list[str] = protection_problems(data.get(TypeSchemaKey.FIELDS.value) or [],
                                              old_type.get_fields() if old_type is not None else [],
                                              template_owned_field_names(data))

    if problems:
        abort(400, ' '.join(problems))
