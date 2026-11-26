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
The reads behind the Field Rule routes

A rule is judged as it would be stored (``judged_rule``): its Types must be stored, its ``set`` resolve and cast on
them, its triggers name carried fields and stored classes, no other active rule set one of its fields on an overlapping
Type set, no stored scope compare one of them - and the caller reach every field it sets, unless an administrator.
Every problem goes into one 400. The check route answers the judged rule with its object count per Type; the list
narrowed to a user group answers the rules the group's own changes can trigger
"""
from typing import Any

from cmdb.manager import (
    AccessAssignmentsManager,
    FieldClassesManager,
    FieldRulesManager,
    ObjectsManager,
    ScopeRolesManager,
    TypesManager,
)
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import ALL_TYPES, SYSTEM_FIELD_CLASS, AccessAssignmentKey, FieldRuleKey, ScopeRoleKey
from cmdb.models.group_model import in_administrator_group
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.utils import keep_omitted_keys
from cmdb.framework.access_engine import AccessGrants, load_grants
from cmdb.framework.scope_compiler import scope_field_names
from cmdb.framework.field_rules import (
    FieldRuleMessage,
    ScopeComparison,
    TriggerKey,
    group_may_trigger,
    judge_field_rule,
    reach_problems,
)
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import FieldRuleCheckKey
from cmdb.interface.rest_api.routes.access_routes.field_protection_helper import group_grants
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'rule_create_payload',
    'rule_update_payload',
    'judged_rule',
    'rule_reach',
    'rules_of_group',
]

# The parts of a Type a rule is judged against
_TYPE_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1,
                                    TypeSchemaKey.RENDER_META.value: 1}
# The key of an object count group
_GROUP_ID: str = '_id'
_GROUP_COUNT: str = 'count'


def rule_create_payload(request_user: CmdbUser, data: dict[str, Any]) -> dict[str, Any]:
    """
    Judges a new rule: its name is free and the rule valid

    Args:
        request_user (CmdbUser): The caller
        data (dict[str, Any]): The validated body

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The document to store, ``set`` cast
    """
    rules: FieldRulesManager = ManagerProvider.get_manager(ManagerType.FIELD_RULES, request_user)
    name: str = data[FieldRuleKey.NAME.value]
    abort_on_problems([FieldRuleMessage.NAME_TAKEN.value.format(name=name) if rules.name_taken(name) else None])

    return judged_rule(request_user, dict(data))


def rule_update_payload(request_user: CmdbUser, stored: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """
    Judges a rule update: the name stays, what the body leaves out is kept, the rule as it would be stored is valid

    Args:
        request_user (CmdbUser): The caller
        stored (dict[str, Any]): The rule as stored
        data (dict[str, Any]): The validated body

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The document to store, ``set`` cast
    """
    stored_name: str = stored[FieldRuleKey.NAME.value]

    if data.get(FieldRuleKey.NAME.value, stored_name) != stored_name:
        abort_on_problems([FieldRuleMessage.NAME_FIXED.value.format(
            public_id=stored[FieldRuleKey.PUBLIC_ID.value], stored=stored_name)])

    written: dict[str, Any] = keep_omitted_keys(data, stored)

    return judged_rule(request_user, written, stored[FieldRuleKey.PUBLIC_ID.value])


def judged_rule(request_user: CmdbUser, rule: dict[str, Any], own_id: int | None = None) -> dict[str, Any]:
    """
    Judges a rule as it would be stored against the stored Types, classes, rules and scopes, and the caller's reach

    Args:
        request_user (CmdbUser): The caller
        rule (dict[str, Any]): The rule as it would be stored
        own_id (int | None): The rule's public_id on an update - left out of the overlap. Defaults to None

    Raises:
        HTTPException: 400 naming every problem
        BaseManagerGetError: When a read fails

    Returns:
        dict[str, Any]: The rule with its ``set`` cast
    """
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    documents: list[dict[str, Any]] = _type_documents(types, rule.get(FieldRuleKey.TYPES.value))
    rule_types: Any = rule.get(FieldRuleKey.TYPES.value)

    if rule_types != ALL_TYPES:
        missing: list[int] = sorted(set(rule_types) - {doc[TypeSchemaKey.PUBLIC_ID.value] for doc in documents})
        abort_on_problems([FieldRuleMessage.UNKNOWN_TYPES.value.format(ids=missing) if missing else None])

    classes: FieldClassesManager = ManagerProvider.get_manager(ManagerType.FIELD_CLASSES, request_user)
    rules: FieldRulesManager = ManagerProvider.get_manager(ManagerType.FIELD_RULES, request_user)
    others: list[dict[str, Any]] = [other for other in rules.all_rules()
                                    if other[FieldRuleKey.PUBLIC_ID.value] != own_id]
    cast, problems = judge_field_rule(rule, documents, _class_names(classes, rule), others,
                                      _scope_comparisons(request_user))
    abort_on_problems(problems)

    judged: dict[str, Any] = {**rule, FieldRuleKey.SET.value: cast}

    if not in_administrator_group(request_user.group_ids):
        abort_on_problems(reach_problems(load_grants(request_user), judged, documents))

    return judged


def rule_reach(request_user: CmdbUser, rule: dict[str, Any]) -> dict[str, Any]:
    """
    What a judged rule reaches: per Type of the rule its object count, and the total

    Args:
        request_user (CmdbUser): The caller
        rule (dict[str, Any]): The judged rule

    Raises:
        TypesManagerGetError | ObjectsManagerIterationError: When a read fails

    Returns:
        dict[str, Any]: ``{rule, types: [{type_id, objects}], objects}``
    """
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    type_ids: list[int] = sorted(document[TypeSchemaKey.PUBLIC_ID.value] for document in _type_documents(
        types, rule.get(FieldRuleKey.TYPES.value)))
    counts: dict[Any, int] = {group[_GROUP_ID]: group[_GROUP_COUNT] for group in objects.count_objects_by_type(
        match={CmdbObjectKey.TYPE_ID.value: {'$in': type_ids}})}
    per_type: list[dict[str, Any]] = [{FieldRuleCheckKey.TYPE_ID.value: type_id,
                                       FieldRuleCheckKey.OBJECTS.value: counts.get(type_id, 0)} for type_id in type_ids]

    return {FieldRuleCheckKey.RULE.value: rule, FieldRuleCheckKey.TYPES.value: per_type,
            FieldRuleCheckKey.OBJECTS.value: sum(counts.get(type_id, 0) for type_id in type_ids)}


def rules_of_group(request_user: CmdbUser, group_id: int) -> list[int]:
    """
    The rules a user group's own changes can trigger

    Args:
        request_user (CmdbUser): The caller - names the tenant
        group_id (int): The group

    Raises:
        HTTPException: 404 when the group does not exist
        BaseManagerGetError: When a read fails

    Returns:
        list[int]: The public_ids of those rules, ascending
    """
    grants: AccessGrants = group_grants(request_user, group_id)
    rules: FieldRulesManager = ManagerProvider.get_manager(ManagerType.FIELD_RULES, request_user)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    stored: list[dict[str, Any]] = rules.all_rules()
    every_type: bool = any(rule.get(FieldRuleKey.TYPES.value) == ALL_TYPES for rule in stored)
    named: list[int] = sorted({type_id for rule in stored if rule.get(FieldRuleKey.TYPES.value) != ALL_TYPES
                               for type_id in rule.get(FieldRuleKey.TYPES.value) or []})
    documents: list[dict[str, Any]] = _type_documents(types, ALL_TYPES if every_type else named)
    by_id: dict[int, dict[str, Any]] = {document[TypeSchemaKey.PUBLIC_ID.value]: document for document in documents}

    def documents_of(rule: dict[str, Any]) -> list[dict[str, Any]]:
        rule_types: Any = rule.get(FieldRuleKey.TYPES.value)

        return documents if rule_types == ALL_TYPES else [by_id[t] for t in rule_types or [] if t in by_id]

    return [rule[FieldRuleKey.PUBLIC_ID.value] for rule in stored
            if group_may_trigger(grants, rule, documents_of(rule))]


def _type_documents(types: TypesManager, rule_types: Any) -> list[dict[str, Any]]:
    """
    The documents of a rule's Types - every Type for a rule on every Type, none for an empty list

    Args:
        types (TypesManager): The Types of the request's database
        rule_types (Any): ``ALL_TYPES`` or ids

    Raises:
        TypesManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The documents (``public_id``, ``fields``, ``render_meta``)
    """
    if rule_types != ALL_TYPES and not rule_types:
        return []

    criteria: dict[str, Any] = {} if rule_types == ALL_TYPES else \
        {TypeSchemaKey.PUBLIC_ID.value: {'$in': list(rule_types)}}

    return types.find(criteria=criteria, projection=_TYPE_PROJECTION)


def _class_names(classes: FieldClassesManager, rule: dict[str, Any]) -> set[str]:
    """
    The stored field class names among those the rule's triggers name, ``system`` always

    Args:
        classes (FieldClassesManager): The field classes of the request's database
        rule (dict[str, Any]): The rule

    Raises:
        FieldClassesManagerGetError: When the read fails

    Returns:
        set[str]: The names
    """
    any_of: list[Any] = [trigger.get(TriggerKey.CHANGED_ANY.value) for trigger in (
        rule.get(FieldRuleKey.WHEN.value), rule.get(FieldRuleKey.UNLESS.value)) if isinstance(trigger, dict)]
    named: list[str] = [entry[TriggerKey.CLASS.value] for entry in any_of
                        if isinstance(entry, dict) and isinstance(entry.get(TriggerKey.CLASS.value), str)]

    return (classes.find_existing_names(named) if named else set()) | {SYSTEM_FIELD_CLASS}


def _scope_comparisons(request_user: CmdbUser) -> list[ScopeComparison]:
    """
    What the stored conditional assignments compare, with their roles' Types

    Args:
        request_user (CmdbUser): The caller

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When a read fails

    Returns:
        list[ScopeComparison]: One per conditional assignment
    """
    assignments_manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS,
                                                                                request_user)
    assignments: list[dict[str, Any]] = assignments_manager.conditional_assignments()

    if not assignments:
        return []

    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    role_types: dict[int, Any] = {role[ScopeRoleKey.PUBLIC_ID.value]: role.get(ScopeRoleKey.TYPES.value)
                                  for role in roles_manager.roles_by_ids(
                                      sorted({a[AccessAssignmentKey.ROLE_ID.value] for a in assignments}))}

    return [ScopeComparison(assignment[AccessAssignmentKey.PUBLIC_ID.value],
                            role_types.get(assignment[AccessAssignmentKey.ROLE_ID.value], []),
                            frozenset(scope_field_names(assignment))) for assignment in assignments]
