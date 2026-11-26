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
The reads behind the explain routes: why a user may (not) do each operation on an object, and what each user group
may do on it

Both start from the object as the caller may read it (403 otherwise - a condition marked met tells something about
the object's values) and its Type. A user is explained with the engine's own reads for that user (``load_grants``,
``load_scope_evaluation``) - its tokens resolved, cached under its own key. The groups are explained from one read of
every assignment and role and one of the groups; a condition naming the member is not evaluated for a group
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from flask import abort

from cmdb.manager import (
    AccessAssignmentsManager,
    GroupsManager,
    ObjectsManager,
    TypesManager,
    UsersManager,
)
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey, FieldRuleKey
from cmdb.models.group_model import CmdbUserGroup, EffectiveRights
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectScopeKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import (
    EXPLAINED_OPERATIONS,
    AccessGrants,
    ExplainKey,
    ExplainSubject,
    GrantEntry,
    build_grants,
    classes_of_fields,
    condition_marks,
    explain_assignment,
    explain_operation,
    explain_operations,
    field_rows,
    group_verdict,
    load_grants,
    names_member,
    object_field_access,
)
from cmdb.framework.access_engine.access_grants_reads import load_access_rules
from cmdb.framework.access_engine.scope_evaluation import (
    ScopeEvaluation,
    build_scope_evaluation,
    load_scope_evaluation,
    reads_scope_block,
)
from cmdb.framework.field_rules import load_active_rules, rules_on_type
from cmdb.framework.scope_compiler import (
    ScopeContext,
    ScopeField,
    ScopeResolver,
    field_views_of_document,
    resolve_scope_fields,
    scope_field_names,
    scope_references,
)
from cmdb.interface.route_utils import abort_if_query_too_slow
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_access_helper import read_object_or_abort
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.scope_compiler import ScopeResolutionError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ExplainAnswerKey',
    'explain_user_access',
    'explain_group_access',
]

OBJECT_DENIED_MESSAGE: str = "You may not view the Object with ID: {object_id} - so you may not have it explained!"
OBJECT_MISSING_MESSAGE: str = "There is no Object with ID: {object_id}!"
USER_MISSING_MESSAGE: str = "There is no user with ID: {user_id}!"
TYPE_MISSING_MESSAGE: str = "The Type of the Object with ID: {object_id} does not exist!"
_TYPE_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1,
                                    TypeSchemaKey.RENDER_META.value: 1}


class ExplainAnswerKey:
    """The keys of the explain answers"""
    USER = 'user'
    PUBLIC_ID = 'public_id'
    USER_NAME = 'user_name'
    ACTIVE = 'active'
    GROUP_IDS = 'group_ids'
    OBJECT = 'object'
    TYPE_ID = 'type_id'
    TYPE_ACTIVE = 'type_active'
    RESTRICTED = 'restricted'
    OPERATIONS = 'operations'
    ASSIGNMENTS = 'assignments'
    FIELDS = 'fields'
    GROUPS = 'groups'
    GROUP_ID = 'group_id'
    NAME = 'name'


def _object_and_type(request_user: CmdbUser, object_id: int) -> tuple[dict[str, Any], CmdbType]:
    """
    The object the caller may view, and its Type

    Args:
        request_user (CmdbUser): The caller
        object_id (int): The object

    Raises:
        HTTPException: 403 when the caller may not view it, 404 when it or its Type does not exist

    Returns:
        tuple[dict[str, Any], CmdbType]: The stored object and its Type
    """
    objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    document: dict[str, Any] = read_object_or_abort(object_id, request_user, objects,
                                                    OBJECT_DENIED_MESSAGE.format(object_id=object_id),
                                                    OBJECT_MISSING_MESSAGE.format(object_id=object_id))
    document.pop(CmdbObjectScopeKey.BLOCK.value, None)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    stored_type: dict[str, Any] | None = types.get_type(document.get(CmdbObjectKey.TYPE_ID.value))

    if not stored_type:
        abort(404, TYPE_MISSING_MESSAGE.format(object_id=object_id))

    return document, CmdbType.from_data(stored_type)


def _object_section(document: dict[str, Any], object_type: CmdbType) -> dict[str, Any]:
    """
    The object as an explanation names it - no values

    Args:
        document (dict[str, Any]): The object
        object_type (CmdbType): Its Type

    Returns:
        dict[str, Any]: ``{public_id, type_id, type_active}``
    """
    return {ExplainAnswerKey.PUBLIC_ID: document.get(CmdbObjectKey.PUBLIC_ID.value),
            ExplainAnswerKey.TYPE_ID: object_type.public_id,
            ExplainAnswerKey.TYPE_ACTIVE: object_type.active is not False}


def _with_block(request_user: CmdbUser, document: dict[str, Any], entries: Iterable[GrantEntry]) -> dict[str, Any]:
    """
    The object with its scope block computed - when a condition reads one

    Args:
        request_user (CmdbUser): The caller - names the tenant
        document (dict[str, Any]): The object, without a stored block
        entries (Iterable[GrantEntry]): The conditional assignments evaluated on it

    Raises:
        HTTPException: 503 when the read ran past its time budget
        ScopeResolutionError: When the location tree or a subnet could not be read

    Returns:
        dict[str, Any]: The object, with its block when needed
    """
    if not reads_scope_block(tuple(entries)):
        return document

    objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    try:
        return {**document, CmdbObjectScopeKey.BLOCK.value: ObjectScopeBlocks(objects).block_of(document)}
    except BaseManagerIterationError as err:
        abort_if_query_too_slow(err)
        raise ScopeResolutionError(err) from err


def _role_type_documents(request_user: CmdbUser, entries: Iterable[GrantEntry]) -> list[dict[str, Any]]:
    """
    The Types the conditional assignments' roles name, as much of them as a condition reads

    Args:
        request_user (CmdbUser): The caller
        entries (Iterable[GrantEntry]): The conditional assignments

    Raises:
        TypesManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The Type documents (``public_id``, ``fields``, ``render_meta``); none without entries
    """
    listed: list[GrantEntry] = list(entries)

    if not listed:
        return []

    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    every_type: bool = any(entry.types.every_type for entry in listed)
    criteria: dict[str, Any] = {} if every_type else {TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(
        {type_id for entry in listed for type_id in entry.types.ids})}}

    return types.find(criteria=criteria, projection=_TYPE_PROJECTION)


def _views(type_documents: list[dict[str, Any]]) -> dict[int, dict[str, ScopeField]]:
    """
    Each Type's fields as a condition sees them

    Args:
        type_documents (list[dict[str, Any]]): Type documents

    Returns:
        dict[int, dict[str, ScopeField]]: By Type id
    """
    return {document[TypeSchemaKey.PUBLIC_ID.value]: field_views_of_document(document) for document in type_documents}


def _marks(entry: GrantEntry, views: dict[int, dict[str, ScopeField]], now: datetime, context: ScopeContext,
           document: dict[str, Any]) -> list[dict[str, Any]]:
    """
    One conditional assignment's conditions marked on the object - fields resolved across its role's Types

    Args:
        entry (GrantEntry): The assignment
        views (dict[int, dict[str, ScopeField]]): The Types' fields
        now (datetime): The evaluation instant
        context (ScopeContext): The resolved tokens
        document (dict[str, Any]): The object with its block

    Returns:
        list[dict[str, Any]]: ``{condition, met}`` per condition
    """
    conditions: list[dict[str, Any]] = list(entry.scope or ())
    fields, _ = resolve_scope_fields(scope_field_names({AccessAssignmentKey.SCOPE.value: conditions}),
                                     [type_views for type_id, type_views in views.items()
                                      if entry.types.contains(type_id)])

    return condition_marks(conditions, fields, now, context, document)


def _setters(request_user: CmdbUser, type_id: int) -> dict[str, list[dict[str, Any]]]:
    """
    The active Field Rules covering a Type, by the field they set

    Args:
        request_user (CmdbUser): The caller - names the tenant
        type_id (int): The Type

    Raises:
        FieldRulesManagerGetError: When the rules could not be read

    Returns:
        dict[str, list[dict[str, Any]]]: The rules by field name
    """
    setters: dict[str, list[dict[str, Any]]] = {}

    for rule in rules_on_type(load_active_rules(request_user), type_id):
        for name in rule.get(FieldRuleKey.SET.value) or {}:
            setters.setdefault(name, []).append(dict(rule))

    return setters


def _target_user(request_user: CmdbUser, user_id: int) -> CmdbUser:
    """
    The user explained, bound to the caller's tenant

    Args:
        request_user (CmdbUser): The caller
        user_id (int): The user

    Raises:
        HTTPException: 404 when no user has the id

    Returns:
        CmdbUser: The user
    """
    users: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)
    target: CmdbUser | None = users.get_user(user_id)

    if target is None:
        abort(404, USER_MISSING_MESSAGE.format(user_id=user_id))

    # Read from the caller's tenant database - its own reads go there too
    target.database = request_user.database

    return target


def _user_assignments(request_user: CmdbUser, target: CmdbUser, grants: AccessGrants, document: dict[str, Any],
                      object_type: CmdbType) -> list[dict[str, Any]]:
    """
    The user's assignments covering the object's Type, their conditions marked with the user's tokens

    Args:
        request_user (CmdbUser): The caller - names the tenant
        target (CmdbUser): The user explained
        grants (AccessGrants): Their grants
        document (dict[str, Any]): The object
        object_type (CmdbType): Its Type

    Raises:
        BaseManagerGetError | ScopeResolutionError: When a read fails

    Returns:
        list[dict[str, Any]]: One ``explain_assignment`` per assignment, ascending by id
    """
    covering: list[GrantEntry] = [entry for entry in grants.entries if entry.types.contains(object_type.public_id)]
    conditional: list[GrantEntry] = [entry for entry in covering if entry.conditional]
    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    group_of: dict[int, Any] = {stored[AccessAssignmentKey.PUBLIC_ID.value]: stored[AccessAssignmentKey.GROUP_ID.value]
                                for stored in assignments.assignments_of_groups(list(target.group_ids))}
    context: ScopeContext = ScopeContext()

    if conditional:
        objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        context = ScopeResolver(objects).resolve(target, scope_references(
            list(entry.scope or ()) for entry in conditional))

    judged: dict[str, Any] = _with_block(request_user, document, conditional)
    views: dict[int, dict[str, ScopeField]] = _views(_role_type_documents(request_user, conditional))
    now: datetime = datetime.now(timezone.utc)

    return [explain_assignment(entry, group_of.get(entry.assignment_id), object_type.public_id,
                               _marks(entry, views, now, context, judged) if entry.conditional else None)
            for entry in covering]


def explain_user_access(request_user: CmdbUser, user_id: int, object_id: int) -> dict[str, Any]:
    """
    Why a user may (not) view, create, edit and delete an object - the engine's verdicts, the assignments covering
    the object's Type with their conditions marked, and the field list

    Args:
        request_user (CmdbUser): The caller
        user_id (int): The user explained
        object_id (int): The object

    Raises:
        HTTPException: 403 when the caller may not view the object; 404 for a missing user, object or Type
        BaseManagerGetError | ScopeResolutionError: When a read fails

    Returns:
        dict[str, Any]: ``{user, object, operations, assignments, fields}``
    """
    document, object_type = _object_and_type(request_user, object_id)
    target: CmdbUser = _target_user(request_user, user_id)
    groups: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    rights: EffectiveRights = EffectiveRights(groups.get_groups(list(target.group_ids)))
    grants: AccessGrants = load_grants(target)
    evaluation: ScopeEvaluation | None = load_scope_evaluation(target, grants) if any(
        entry.conditional for entry in grants.entries) else None
    subject: ExplainSubject = ExplainSubject(target.active is not False, rights.grants)
    type_fields: list[dict[str, Any]] = object_type.get_fields() or []
    operations: list[dict[str, Any]] = explain_operations(subject, grants, evaluation, document,
                                                          object_type.active is not False,
                                                          classes_of_fields(type_fields))

    return {
        ExplainAnswerKey.USER: {ExplainAnswerKey.PUBLIC_ID: target.public_id,
                                ExplainAnswerKey.USER_NAME: target.user_name,
                                ExplainAnswerKey.ACTIVE: target.active is not False,
                                ExplainAnswerKey.GROUP_IDS: sorted(target.group_ids)},
        ExplainAnswerKey.OBJECT: _object_section(document, object_type),
        ExplainAnswerKey.OPERATIONS: operations,
        ExplainAnswerKey.ASSIGNMENTS: _user_assignments(request_user, target, grants, document, object_type),
        ExplainAnswerKey.FIELDS: field_rows(object_field_access(target, document, type_fields),
                                            _setters(request_user, object_type.public_id)),
    }


@dataclass(frozen=True)
class _ObjectContext:
    """
    What every group's answer on one object reads

    Attributes:
        document (dict[str, Any]): The object, without a stored block
        judged (dict[str, Any]): The object with its block computed when a condition reads one
        object_type (CmdbType): Its Type
        type_documents (list[dict[str, Any]]): The Types the evaluable conditions' roles name
        blocks (ObjectScopeBlocks | None): Computes a judged state's block - None when no condition reads one
        now (datetime): The evaluation instant
    """
    document: dict[str, Any]
    judged: dict[str, Any]
    object_type: CmdbType
    type_documents: list[dict[str, Any]]
    blocks: ObjectScopeBlocks | None
    now: datetime


def explain_group_access(request_user: CmdbUser, object_id: int) -> dict[str, Any]:
    """
    What each user group, by itself, may do on an object - "who may do what here"

    Args:
        request_user (CmdbUser): The caller
        object_id (int): The object

    Raises:
        HTTPException: 403 when the caller may not view the object; 404 for a missing object or Type
        BaseManagerGetError | ScopeResolutionError: When a read fails

    Returns:
        dict[str, Any]: ``{object, restricted, groups: [{group_id, name, operations, assignments}]}``
    """
    document, object_type = _object_and_type(request_user, object_id)
    every_assignment, roles = load_access_rules(request_user)
    groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    groups: list[CmdbUserGroup] = [groups_manager.hydrate_group(stored) for stored in groups_manager.find(
        criteria={}, sort=[(ExplainAnswerKey.PUBLIC_ID, 1)])]
    grants_of: dict[int, AccessGrants] = {group.public_id: build_grants(every_assignment, roles, [group.public_id])
                                          for group in groups}
    evaluable: tuple[GrantEntry, ...] = tuple(entry for grants in grants_of.values() for entry in grants.entries
                                              if entry.conditional and not names_member(entry))
    objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    blocks: ObjectScopeBlocks | None = ObjectScopeBlocks(objects) if reads_scope_block(evaluable) else None
    context: _ObjectContext = _ObjectContext(document, _with_block(request_user, document, evaluable), object_type,
                                             _role_type_documents(request_user, evaluable), blocks,
                                             datetime.now(timezone.utc))

    return {ExplainAnswerKey.OBJECT: _object_section(document, object_type),
            ExplainAnswerKey.RESTRICTED: build_grants(every_assignment, roles, []).is_restricted(
                object_type.public_id),
            ExplainAnswerKey.GROUPS: [_group_row(group, grants_of[group.public_id], context) for group in groups]}


def _group_row(group: CmdbUserGroup, grants: AccessGrants, context: _ObjectContext) -> dict[str, Any]:
    """
    One user group's answer on the object - its conditions naming the member are not evaluated

    Args:
        group (CmdbUserGroup): The group
        grants (AccessGrants): Its own grants
        context (_ObjectContext): The object and what its answers read

    Returns:
        dict[str, Any]: ``{group_id, name, operations: [{operation, verdict, allowed, step, ...}], assignments}``
    """
    type_id: int = context.object_type.public_id
    covering: list[GrantEntry] = [entry for entry in grants.entries if entry.types.contains(type_id)]
    member: list[GrantEntry] = [entry for entry in covering if entry.conditional and names_member(entry)]
    evaluable: tuple[GrantEntry, ...] = tuple(entry for entry in grants.entries
                                              if entry.conditional and not names_member(entry))
    evaluation: ScopeEvaluation = build_scope_evaluation(evaluable, context.type_documents, ScopeContext(),
                                                         context.now, context.blocks)
    subject: ExplainSubject = ExplainSubject(True, EffectiveRights([group]).grants)
    field_classes: dict[str, str] = classes_of_fields(context.object_type.get_fields() or [])
    views: dict[int, dict[str, ScopeField]] = _views(context.type_documents)
    operations: list[dict[str, Any]] = []

    for operation in EXPLAINED_OPERATIONS:
        row: dict[str, Any] = explain_operation(subject, grants, evaluation, context.document,
                                                context.object_type.active is not False, field_classes, operation)
        operations.append({**row, ExplainKey.VERDICT.value: group_verdict(row, member, operation, type_id)})

    return {ExplainAnswerKey.GROUP_ID: group.public_id, ExplainAnswerKey.NAME: group.name,
            ExplainAnswerKey.OPERATIONS: operations,
            ExplainAnswerKey.ASSIGNMENTS: [
                explain_assignment(entry, group.public_id, type_id,
                                   None if not entry.conditional or names_member(entry)
                                   else _marks(entry, views, context.now, ScopeContext(), context.judged))
                for entry in covering]}
