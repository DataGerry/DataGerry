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
Explaining access to one object - pure

Per operation (view, create, edit, delete) the checks run in the order a request meets them: the user must be active,
hold the operation's object right in one of its groups, and - for a write - the object's Type must be active; then the
engine decides (``decide`` with a trace), so an explanation and the real check never part. View and delete are judged
on the stored object, create on an object like it (its ``system`` fields left to the server), edit on an edit changing
nothing (which fields it could change is
the field list's answer).

Each assignment covering the object's Type is answered with its conditions, each marked met or not met on the object
(its scope block computed, the user's tokens resolved) - every condition met is the engine's match, one fragment of the
compiled scope per condition. A user group explained without a member cannot resolve a user token: an operation only
such a condition could grant is ``depends_on_member``. No field value is answered - only names, the stored conditions
and the marks
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cmdb.models.access_model import SYSTEM_FIELD_CLASS, FieldRuleKey, ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.framework.access_engine.access_decision import AccessDecision, decide
from cmdb.framework.access_engine.access_engine_constants import (
    EXPLAINED_OPERATIONS,
    OPERATION_RIGHTS,
    ExplainKey,
    ExplainStep,
    ExplainVerdict,
)
from cmdb.framework.access_engine.access_grants import AccessGrants, GrantEntry
from cmdb.framework.access_engine.scope_evaluation import ScopeEvaluation
from cmdb.framework.scope_compiler import (
    ScopeBlockKey,
    ScopeContext,
    ScopeField,
    block_kind,
    compile_block,
    document_matches,
    is_user_token,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ExplainSubject',
    'explained_states',
    'explain_operation',
    'explain_operations',
    'condition_marks',
    'explain_assignment',
    'names_member',
    'group_verdict',
    'field_rows',
]


@dataclass(frozen=True)
class ExplainSubject:
    """
    Who is explained - a user, or a user group by itself

    Attributes:
        active (bool): Whether they may log in (a group always may)
        holds_right (Callable[[str], bool]): Whether their groups grant a right, wildcards included
    """
    active: bool
    holds_right: Callable[[str], bool]


def explained_states(operation: ScopeOperation, document: Mapping[str, Any],
                     field_classes: Mapping[str, str] | None = None
                     ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """
    The states an operation is explained on

    Args:
        operation (ScopeOperation): The operation
        document (Mapping[str, Any]): The stored object
        field_classes (Mapping[str, str] | None): The Type's classed fields. Defaults to None (none)

    Returns:
        tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]: ``before`` and ``after`` - view / delete the stored
            object, create an object like it without its ``system`` fields (the server fills those, never a creator),
            edit the stored object unchanged
    """
    if operation is ScopeOperation.CREATE:
        system: set[str] = {name for name, field_class in (field_classes or {}).items()
                            if field_class == SYSTEM_FIELD_CLASS}

        return None, {**document, CmdbObjectKey.FIELDS.value: [
            entry for entry in document.get(CmdbObjectKey.FIELDS.value) or []
            if not (isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) in system)]}

    if operation is ScopeOperation.EDIT:
        return document, document

    return document, None


def explain_operation(subject: ExplainSubject, grants: AccessGrants, evaluation: ScopeEvaluation | None,
                      document: Mapping[str, Any], type_active: bool, field_classes: Mapping[str, str],
                      operation: ScopeOperation) -> dict[str, Any]:
    """
    Explains one operation on one object

    Args:
        subject (ExplainSubject): Who is explained
        grants (AccessGrants): Their grants
        evaluation (ScopeEvaluation | None): Their conditional assignments, compiled; None - none evaluated
        document (Mapping[str, Any]): The stored object
        type_active (bool): Whether the object's Type is active
        field_classes (Mapping[str, str]): The Type's classed fields
        operation (ScopeOperation): The operation

    Returns:
        dict[str, Any]: ``{operation, allowed, step, right, assignment_ids, refused_fields}``
    """
    right: str = OPERATION_RIGHTS[operation]
    row: dict[str, Any] = {ExplainKey.OPERATION.value: operation.value, ExplainKey.ALLOWED.value: False,
                           ExplainKey.RIGHT.value: right, ExplainKey.ASSIGNMENT_IDS.value: [],
                           ExplainKey.REFUSED_FIELDS.value: []}

    if not subject.active:
        return {**row, ExplainKey.STEP.value: ExplainStep.USER_INACTIVE.value}

    if not subject.holds_right(right):
        return {**row, ExplainKey.STEP.value: ExplainStep.FUNCTIONAL_RIGHT.value}

    if operation is not ScopeOperation.VIEW and not type_active:
        return {**row, ExplainKey.STEP.value: ExplainStep.TYPE_INACTIVE.value}

    before, after = explained_states(operation, document, field_classes)
    decision: AccessDecision = decide(grants, operation, before, after, True, evaluation, field_classes)

    return {**row, ExplainKey.ALLOWED.value: decision.allowed, ExplainKey.STEP.value: decision.step.value,
            ExplainKey.ASSIGNMENT_IDS.value: list(decision.assignment_ids),
            ExplainKey.REFUSED_FIELDS.value: list(decision.refused_fields)}


def explain_operations(subject: ExplainSubject, grants: AccessGrants, evaluation: ScopeEvaluation | None,
                       document: Mapping[str, Any], type_active: bool,
                       field_classes: Mapping[str, str]) -> list[dict[str, Any]]:
    """
    Explains every explained operation on one object, in order

    Args:
        subject (ExplainSubject): Who is explained
        grants (AccessGrants): Their grants
        evaluation (ScopeEvaluation | None): Their conditional assignments, compiled
        document (Mapping[str, Any]): The stored object
        type_active (bool): Whether the object's Type is active
        field_classes (Mapping[str, str]): The Type's classed fields

    Returns:
        list[dict[str, Any]]: One row per operation (``explain_operation``)
    """
    return [explain_operation(subject, grants, evaluation, document, type_active, field_classes, operation)
            for operation in EXPLAINED_OPERATIONS]


def condition_marks(conditions: Iterable[dict[str, Any]], fields: Mapping[str, ScopeField], now: datetime,
                    context: ScopeContext, document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Marks each condition of an assignment met or not met on one object

    Args:
        conditions (Iterable[dict[str, Any]]): The stored conditions
        fields (Mapping[str, ScopeField]): Their compared fields, resolved across the role's Types
        now (datetime): The evaluation instant
        context (ScopeContext): The user's resolved tokens
        document (Mapping[str, Any]): The object, its scope block computed when a condition reads one

    Returns:
        list[dict[str, Any]]: ``{condition, met}`` per condition, in order - a comparison of a field that did not
            resolve is not met (the assignment grants nothing then)
    """
    marks: list[dict[str, Any]] = []

    for condition in conditions:
        resolvable: bool = block_kind(condition) is not None or condition.get(ScopeBlockKey.FIELD.value) in fields
        met: bool = resolvable and document_matches(dict(document),
                                                     compile_block(condition, dict(fields), now, context))
        marks.append({ExplainKey.CONDITION.value: condition, ExplainKey.MET.value: met})

    return marks


def explain_assignment(entry: GrantEntry, group_id: Any, type_id: Any,
                       marks: list[dict[str, Any]] | None) -> dict[str, Any]:
    """
    One assignment covering the object's Type, as an explanation shows it

    Args:
        entry (GrantEntry): The assignment with its role
        group_id (Any): Its user group
        type_id (Any): The object's Type
        marks (list[dict[str, Any]] | None): Its conditions marked (``condition_marks``); None when they were not
            evaluated (a group explained without its member, a user token named)

    Returns:
        dict[str, Any]: ``{assignment_id, group_id, role_id, operations, unconditional, conditions, matched,
            grants_here}`` - ``matched`` None and ``grants_here`` empty when not evaluated
    """
    unconditional: bool = not entry.conditional
    matched: bool | None = True if unconditional else (
        None if marks is None else all(mark[ExplainKey.MET.value] for mark in marks))
    granted: list[str] = [operation.value for operation in EXPLAINED_OPERATIONS
                          if matched and entry.grants(operation, type_id)]

    return {ExplainKey.ASSIGNMENT_ID.value: entry.assignment_id, ExplainKey.GROUP_ID.value: group_id,
            ExplainKey.ROLE_ID.value: entry.role_id,
            ExplainKey.OPERATIONS.value: sorted(operation.value for operation in entry.operations),
            ExplainKey.UNCONDITIONAL.value: unconditional,
            ExplainKey.CONDITIONS.value: [] if unconditional else (
                marks if marks is not None else [{ExplainKey.CONDITION.value: condition, ExplainKey.MET.value: None}
                                                 for condition in entry.scope or ()]),
            ExplainKey.MATCHED.value: matched, ExplainKey.GRANTS_HERE.value: granted}


def names_member(entry: GrantEntry) -> bool:
    """
    Whether a conditional assignment compares against the member it is evaluated for (a user token)

    Args:
        entry (GrantEntry): The assignment

    Returns:
        bool: True when a condition's value is ``{user: person}`` or ``{user: groups}``
    """
    return any(is_user_token(condition.get(ScopeBlockKey.VALUE.value)) for condition in entry.scope or ())


def group_verdict(row: Mapping[str, Any], member_entries: Iterable[GrantEntry], operation: ScopeOperation,
                  type_id: Any) -> str:
    """
    A user group's verdict on one operation - a scope refusal another condition naming the member could lift depends
    on the member

    Args:
        row (Mapping[str, Any]): The operation's row (``explain_operation``), the member conditions not evaluated
        member_entries (Iterable[GrantEntry]): The group's assignments naming the member
        operation (ScopeOperation): The operation
        type_id (Any): The object's Type

    Returns:
        str: An ``ExplainVerdict`` value
    """
    if row[ExplainKey.ALLOWED.value]:
        return ExplainVerdict.ALLOWED.value

    if row[ExplainKey.STEP.value] == ExplainStep.SCOPE.value and any(
            entry.grants(operation, type_id) for entry in member_entries):
        return ExplainVerdict.DEPENDS_ON_MEMBER.value

    return ExplainVerdict.DENIED.value


def field_rows(field_access: Mapping[str, str], setters: Mapping[str, list[Mapping[str, Any]]]
               ) -> list[dict[str, Any]]:
    """
    The field list of an explanation: what the user may do with each field, and the rules setting it

    Args:
        field_access (Mapping[str, str]): ``write`` / ``read`` / ``system`` per field (``object_field_access``)
        setters (Mapping[str, list[Mapping[str, Any]]]): The active Field Rules covering the Type, by field they set

    Returns:
        list[dict[str, Any]]: ``{name, access, set_by: [{rule_id, rule_name}]}`` per field, in the Type's order
    """
    return [{ExplainKey.NAME.value: name, ExplainKey.ACCESS.value: access,
             ExplainKey.SET_BY.value: [{ExplainKey.RULE_ID.value: rule.get(FieldRuleKey.PUBLIC_ID.value),
                                        ExplainKey.RULE_NAME.value: rule.get(FieldRuleKey.NAME.value)}
                                       for rule in setters.get(name, [])]}
            for name, access in field_access.items()]
