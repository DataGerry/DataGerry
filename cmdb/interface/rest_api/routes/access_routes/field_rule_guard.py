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
Keeps the stored Field Rules valid, and the fields they set apart from the scopes

* **A Type change** (the Type update, the type import, a global section template update copied into the Types carrying
  it) may not leave an active rule covering the Type unable to set one of its fields there
  (``type_change_rule_problems``).
* **A scope** may not compare a field an active rule sets on an overlapping Type set - judged on the assignment writes
  and checks, and on a scope role's change of Types (the rule side is judged when a rule is saved)

Each reads the stored rules once, and nothing more while there is none
"""
from typing import Any

from flask import abort

from cmdb.manager import AccessAssignmentsManager, FieldRulesManager, ScopeRolesManager, SectionTemplatesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import UNCONDITIONAL_SCOPE, AccessAssignmentKey, ScopeRoleKey
from cmdb.models.section_template_model import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType, FieldKey, SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler import ScopeField, field_views, scope_field_names
from cmdb.framework.field_rules import FieldRuleMessage, rule_set_fields, type_change_rule_problems
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'rule_field_change_blocker',
    'guard_rule_field_change',
    'guard_template_rule_change',
    'scope_rule_problems',
    'guard_scope_rule_fields',
    'guard_role_rule_change',
]


def _stored_rules(request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    The stored Field Rules

    Args:
        request_user (CmdbUser): The caller - names the database

    Raises:
        FieldRulesManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The rules as stored
    """
    manager: FieldRulesManager = ManagerProvider.get_manager(ManagerType.FIELD_RULES, request_user)

    return manager.all_rules()


def rule_field_change_blocker(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> str | None:
    """
    Reports why a Type change would leave a stored rule unable to set its fields on the Type

    Args:
        request_user (CmdbUser): The caller
        old_type (CmdbType): The stored Type
        new_type (CmdbType): The Type the change would store

    Raises:
        FieldRulesManagerGetError: When the rules could not be read

    Returns:
        str | None: The problems joined, or None when every rule stays valid
    """
    rules: list[dict[str, Any]] = _stored_rules(request_user)

    if not rules:
        return None

    before: dict[str, ScopeField] = field_views(old_type.get_fields(), old_type.get_all_mds_fields())
    after: dict[str, ScopeField] = field_views(new_type.get_fields(), new_type.get_all_mds_fields())

    return ' '.join(type_change_rule_problems(new_type.public_id, rules, before, after)) or None


def guard_rule_field_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts a Type update that would leave a stored rule unable to set its fields on the Type

    Args:
        request_user (CmdbUser): The caller
        old_type (CmdbType): The stored Type
        new_type (CmdbType): The Type the update would store

    Raises:
        HTTPException: 400 naming the rules and fields
    """
    if blocker := rule_field_change_blocker(request_user, old_type, new_type):
        abort(400, blocker)


def guard_template_rule_change(request_user: CmdbUser, section_templates_manager: SectionTemplatesManager,
                               current_template: CmdbSectionTemplate, params: dict[str, Any]) -> None:
    """
    Aborts a global section template update that would leave a stored rule unable to set its fields on a Type
    carrying the section - the update is copied into those Types past the Type routes' guard

    Args:
        request_user (CmdbUser): The caller
        section_templates_manager (SectionTemplatesManager): Reads the Types using the template
        current_template (CmdbSectionTemplate): The stored template
        params (dict[str, Any]): The validated update payload, its ``fields`` parsed

    Raises:
        HTTPException: 400 naming the rules and fields
    """
    if not current_template.is_global:
        return

    rules: list[dict[str, Any]] = _stored_rules(request_user)

    if not rules:
        return

    name: str = params[SectionTemplateKey.NAME]
    in_rows: bool = current_template.type == SectionType.MDS_SECTION.value
    old_names: set[Any] = {field.get(FieldKey.NAME.value) for field in current_template.fields
                           if isinstance(field, dict)}
    new_fields: list[Any] = params.get(SectionTemplateKey.FIELDS) or []
    new_names: list[Any] = [field.get(FieldKey.NAME.value) for field in new_fields if isinstance(field, dict)]
    problems: list[str] = []

    for a_type in section_templates_manager.get_types_using_template(name):
        if a_type.get_section(name) is None:
            continue

        kept: list[Any] = [field for field in a_type.get_fields() if field.get(FieldKey.NAME.value) not in old_names]
        mds_names: list[str] = [field for field in a_type.get_all_mds_fields() if field not in old_names]
        after: dict[str, ScopeField] = field_views([*kept, *new_fields],
                                                   [*mds_names, *(new_names if in_rows else [])])
        before: dict[str, ScopeField] = field_views(a_type.get_fields(), a_type.get_all_mds_fields())
        problems += type_change_rule_problems(a_type.public_id, rules, before, after)

    abort_on_problems(problems)


def scope_rule_problems(request_user: CmdbUser, role_types: Any, scope: Any) -> list[str]:
    """
    Refuses a scope comparing a field an active rule sets on an overlapping Type set

    Args:
        request_user (CmdbUser): The caller
        role_types (Any): The scope role's Types - ``ALL_TYPES`` or ids
        scope (Any): The scope as it would be stored

    Raises:
        FieldRulesManagerGetError: When the rules could not be read

    Returns:
        list[str]: A problem per compared field a rule sets
    """
    if scope == UNCONDITIONAL_SCOPE or not isinstance(scope, list):
        return []

    return _compared_rule_fields(_stored_rules(request_user), role_types, scope)


def _compared_rule_fields(rules: list[dict[str, Any]], role_types: Any, scope: Any) -> list[str]:
    """
    The fields a scope compares that an active rule sets on an overlapping Type set

    Args:
        rules (list[dict[str, Any]]): The stored rules
        role_types (Any): The scope role's Types
        scope (Any): A condition list

    Returns:
        list[str]: A problem per such field
    """
    if scope == UNCONDITIONAL_SCOPE or not isinstance(scope, list):
        return []

    setters: dict[str, list[int]] = rule_set_fields(rules, role_types)

    return [FieldRuleMessage.RULE_FIELD.value.format(field=name, rule_ids=setters[name])
            for name in scope_field_names({AccessAssignmentKey.SCOPE.value: scope}) if name in setters]


def guard_scope_rule_fields(request_user: CmdbUser, roles: ScopeRolesManager, role_id: int, scope: Any) -> None:
    """
    Aborts an assignment write or check whose scope compares a field an active rule sets on the role's Types -
    nothing is read for an unconditional scope

    Args:
        request_user (CmdbUser): The caller
        roles (ScopeRolesManager): The scope roles of the request's database
        role_id (int): The scope role the assignment grants
        scope (Any): The scope as it would be stored

    Raises:
        HTTPException: 400 naming the fields and rules
    """
    if scope == UNCONDITIONAL_SCOPE or not isinstance(scope, list):
        return

    role: dict[str, Any] = roles.get_item(role_id, as_dict=True) or {}
    abort_on_problems(scope_rule_problems(request_user, role.get(ScopeRoleKey.TYPES.value), scope))


def guard_role_rule_change(request_user: CmdbUser, role_id: int, written_role: dict[str, Any]) -> None:
    """
    Aborts a scope role update whose new Types would let a scope of its assignments compare a field a rule sets

    Args:
        request_user (CmdbUser): The caller
        role_id (int): The role's public_id
        written_role (dict[str, Any]): The role as it would be stored

    Raises:
        HTTPException: 400 naming the fields and rules
    """
    manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    scopes: list[Any] = [assignment[AccessAssignmentKey.SCOPE.value] for assignment in manager.conditional_assignments()
                         if assignment[AccessAssignmentKey.ROLE_ID.value] == role_id]

    if not scopes:
        return

    rules: list[dict[str, Any]] = _stored_rules(request_user)
    abort_on_problems([problem for scope in scopes for problem in _compared_rule_fields(
        rules, written_role.get(ScopeRoleKey.TYPES.value), scope)])
