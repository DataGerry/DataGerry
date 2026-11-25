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
The write rules of a scope role: its name is unique, its Types are stored ones the caller may read, its field
classes stored ones
"""
from typing import Any

from cmdb.manager.field_classes_manager import FieldClassesManager
from cmdb.manager.scope_roles_manager import ScopeRolesManager
from cmdb.manager.types_manager import TypesManager
from cmdb.models.access_model import ALL_TYPES, ScopeRoleKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
from cmdb.framework.access_rules.access_rule_reads import clashes
# -------------------------------------------------------------------------------------------------------------------- #


def unknown_type_ids(types: str | list[int], existing: set[int]) -> list[int]:
    """
    The Type ids a role names that are not stored - none for a role covering every Type

    Args:
        types (str | list[int]): The role's Types, ``ALL_TYPES`` or ids
        existing (set[int]): The ids among them that are stored (and readable by the caller)

    Returns:
        list[int]: The unknown ids, ascending
    """
    if types == ALL_TYPES:
        return []

    return sorted(set(types) - existing)


def unknown_field_classes(classes: list[str], existing: set[str]) -> list[str]:
    """
    The field class names a role grants that are not stored

    Args:
        classes (list[str]): The role's field classes
        existing (set[str]): The names among them that are stored

    Returns:
        list[str]: The unknown names, sorted
    """
    return sorted(set(classes) - existing)


def scope_role_reference_problems(role: dict[str, Any], types_manager: TypesManager,
                                  field_classes_manager: FieldClassesManager, request_user: CmdbUser) -> list[str]:
    """
    Judges what a role names: every listed Type must be stored and readable by the caller, every granted field class
    stored. A Type the caller may not read is refused as one that does not exist - the answer tells them apart
    nowhere. Two reads for the Types (the existing ids, the caller's denied ones), one for the classes, and none for
    a role covering every Type, granting no class, or a body leaving the key out - an update judges only the
    references it sends, so a stored reference gone stale does not block an unrelated change

    Args:
        role (dict[str, Any]): The references to judge - a create's whole body, an update's sent keys
        types_manager (TypesManager): The Types of the request's database
        field_classes_manager (FieldClassesManager): The field classes of the request's database
        request_user (CmdbUser): The caller - whose readable Types a role may name

    Raises:
        TypesManagerGetError: When a Type read fails
        FieldClassesManagerGetError: When the field class read fails

    Returns:
        list[str]: The problems, empty when the role names only stored documents the caller may read
    """
    problems: list[str] = []
    types: str | list[int] = role.get(ScopeRoleKey.TYPES.value, ALL_TYPES)
    classes: list[str] = role.get(ScopeRoleKey.FIELD_CLASSES.value) or []

    if types != ALL_TYPES and types:
        readable: set[int] = (types_manager.get_existing_type_ids(list(types))
                              - set(types_manager.get_denied_type_ids(request_user, AccessControlPermission.READ)))
        missing_types: list[int] = unknown_type_ids(types, readable)

        if missing_types:
            problems.append(AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=missing_types))

    if classes:
        missing_classes: list[str] = unknown_field_classes(classes, field_classes_manager.find_existing_names(classes))

        if missing_classes:
            problems.append(AccessRuleMessage.UNKNOWN_FIELD_CLASSES.value.format(names=missing_classes))

    return problems


def scope_role_name_taken(manager: ScopeRolesManager, name: str, own_id: int | None = None) -> str | None:
    """
    Refuses a role name another role carries - one count

    Args:
        manager (ScopeRolesManager): The scope roles of the request's database
        name (str): The name the role would carry
        own_id (int | None): The role being updated; None for a create

    Raises:
        BaseManagerGetError: When the count fails

    Returns:
        str | None: The problem, or None when the name is free
    """
    if clashes(manager, {ScopeRoleKey.NAME.value: name}, own_id):
        return AccessRuleMessage.SCOPE_ROLE_NAME_TAKEN.value.format(name=name)

    return None
