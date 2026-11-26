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
The access decision for one object: may a user perform an operation on it, judged on the states the operation needs,
and may the user write every field the write changes

View and delete judge the stored object, create the object as it would be stored, edit both - so nobody moves an
object out of their reach or into someone else's. A create or an edit must also be allowed to write each changed field
(phase 12): a field without a class through a role granting the operation with ``write_regular_fields``, a classed
field through a role listing its class - on a restricted Type only, an open Type stays open (D1) - and a ``system``
field never, by no user (D2). With a trace the decision also names the user's assignments granting the operation on
the judged Types

A Type held only through **conditional assignments** (phase 9, R21) allows the operation on a state its condition
matches - judged in memory (``scope_matcher``) on each judged state, so an edit may neither move an object out of the
user's scope nor into it from outside; the changed fields are judged against the assignments matching the state the
object is stored as
"""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cmdb.models.access_model import SYSTEM_FIELD_CLASS, ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine.field_class_lookup import classes_of_fields, type_field_classes
from cmdb.framework.access_engine.access_engine_constants import (
    FieldAccess,
    FIELD_WRITING_OPERATIONS,
    FIELDS_REFUSED_MESSAGE,
    OPERATION_REFUSED_MESSAGE,
    MISSING_STATE_MESSAGE,
    OPERATION_STATES,
    AccessDecisionStep,
    ObjectState,
)
from cmdb.framework.access_engine.access_grants import AccessGrants
from cmdb.framework.access_engine.access_grants_reads import load_grants
from cmdb.framework.access_engine.object_field_changes import changed_field_names
from cmdb.framework.access_engine.scope_evaluation import ConditionalGrant, ScopeEvaluation, load_scope_evaluation
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AccessDecision:
    """
    Whether one operation on one object is allowed, and what decided it

    Attributes:
        allowed (bool): True when the operation is allowed
        operation (ScopeOperation): The operation decided
        step (AccessDecisionStep): What decided: no restriction, the assignments, or a field that may not be written
        type_id (Any): The Type that decided - the denied one, else the Type the object is (to be) stored as
        refused_fields (tuple[str, ...]): The changed fields that may not be written, ascending
        assignment_ids (tuple[int, ...]): With a trace, the user's assignments granting the operation on the judged
            Types, ascending; empty without one
    """
    allowed: bool
    operation: ScopeOperation
    step: AccessDecisionStep
    type_id: Any
    refused_fields: tuple[str, ...] = ()
    assignment_ids: tuple[int, ...] = ()


def judged_states(operation: ScopeOperation, before: Mapping[str, Any] | None,
                  after: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """
    The object states an operation is judged on, in OPERATION_STATES order

    Args:
        operation (ScopeOperation): The operation
        before (Mapping[str, Any] | None): The stored object
        after (Mapping[str, Any] | None): The object as it would be stored

    Raises:
        ValueError: When a state the operation is judged on is not given - a caller's mistake, never a refusal

    Returns:
        list[Mapping[str, Any]]: The states
    """
    given: dict[ObjectState, Mapping[str, Any] | None] = {ObjectState.BEFORE: before, ObjectState.AFTER: after}
    states: list[Mapping[str, Any]] = []

    for state in OPERATION_STATES[operation]:
        document: Mapping[str, Any] | None = given[state]

        if document is None:
            raise ValueError(MISSING_STATE_MESSAGE.format(operation=operation.value, state=state.value))

        states.append(document)

    return states


def refused_fields(grants: AccessGrants, operation: ScopeOperation, type_id: Any, changed: list[str],
                   matching: tuple[ConditionalGrant, ...] = (),
                   field_classes: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """
    The changed fields the user may not write on a Type through roles granting the operation

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The writing operation
        type_id (Any): The Type the object is to be stored as
        changed (list[str]): The changed field names, ascending
        matching (tuple[ConditionalGrant, ...]): The conditional assignments matching the state stored - their roles
            count too
        field_classes (Mapping[str, str] | None): The Type's classed fields (``field_class_lookup``). Defaults to None
            (no field carries a class)

    Returns:
        tuple[str, ...]: The refused names, ascending; empty when every one may be written
    """
    classes: Mapping[str, str] = field_classes or {}

    return tuple(name for name in changed
                 if not _may_write(grants, operation, type_id, classes.get(name), matching))


def _may_write(grants: AccessGrants, operation: ScopeOperation, type_id: Any, field_class: str | None,
               matching: tuple[ConditionalGrant, ...]) -> bool:
    """
    Whether the user may write one field of a class on a Type

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The writing operation
        type_id (Any): The Type
        field_class (str | None): The field's class; None for a regular field
        matching (tuple[ConditionalGrant, ...]): The conditional assignments matching the state stored

    Returns:
        bool: False for a ``system`` field always; on an open Type True; else a granting role must write it
    """
    if field_class == SYSTEM_FIELD_CLASS:
        return False

    if not grants.is_restricted(type_id):
        return True

    if field_class is None:
        return grants.writes_regular_fields(operation, type_id) or any(grant.entry.write_regular_fields
                                                                       for grant in matching)

    return grants.writes_class(operation, type_id, field_class) or any(field_class in grant.entry.field_classes
                                                                       for grant in matching)


def decide(grants: AccessGrants, operation: ScopeOperation, before: Mapping[str, Any] | None = None,
           after: Mapping[str, Any] | None = None, trace: bool = False,
           evaluation: ScopeEvaluation | None = None,
           field_classes: Mapping[str, str] | None = None) -> AccessDecision:
    """
    Decides one operation on one object from the user's grants

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The operation
        before (Mapping[str, Any] | None): The stored object - needed by view, edit and delete
        after (Mapping[str, Any] | None): The object as it would be stored - needed by create and edit
        trace (bool): Whether the decision names the granting assignments. Defaults to False
        evaluation (ScopeEvaluation | None): The user's conditional assignments, compiled; None - none evaluated
            (a Type held only conditionally is then denied)
        field_classes (Mapping[str, str] | None): The classed fields of the Type the object is stored as. Defaults to
            None (no field carries a class)

    Raises:
        ValueError: When a state the operation is judged on is not given

    Returns:
        AccessDecision: The decision
    """
    states: list[Mapping[str, Any]] = judged_states(operation, before, after)
    type_ids: list[Any] = [state.get(CmdbObjectKey.TYPE_ID.value) for state in states]
    assignment_ids: tuple[int, ...] = _granting_assignment_ids(grants, operation, type_ids) if trace else ()
    denied_type, matching = _judge_states(grants, evaluation, operation, states)

    if trace:
        assignment_ids = tuple(sorted({*assignment_ids, *(grant.entry.assignment_id for grant in matching)}))

    if denied_type is not _ALLOWED:
        return AccessDecision(False, operation, AccessDecisionStep.SCOPE, denied_type, (), assignment_ids)

    stored_as: Any = type_ids[-1]

    if operation in FIELD_WRITING_OPERATIONS:
        refused: tuple[str, ...] = refused_fields(
            grants, operation, stored_as,
            changed_field_names(before if operation is ScopeOperation.EDIT else None, after), matching,
            field_classes)

        if refused:
            return AccessDecision(False, operation, AccessDecisionStep.FIELD_CLASS, stored_as, refused,
                                  assignment_ids)

    step: AccessDecisionStep = AccessDecisionStep.SCOPE if any(grants.is_restricted(type_id) for type_id in type_ids) \
        else AccessDecisionStep.UNRESTRICTED

    return AccessDecision(True, operation, step, stored_as, (), assignment_ids)


# Marks "every judged state allowed" apart from any type_id a state may carry (None included)
_ALLOWED: object = object()


def _judge_states(grants: AccessGrants, evaluation: ScopeEvaluation | None, operation: ScopeOperation,
                  states: list[Mapping[str, Any]]) -> tuple[Any, tuple[ConditionalGrant, ...]]:
    """
    Judges each state: granted in full on its Type, or matched by a conditional assignment

    Args:
        grants (AccessGrants): The user's grants
        evaluation (ScopeEvaluation | None): The conditional assignments, compiled; None - none evaluated
        operation (ScopeOperation): The operation
        states (list[Mapping[str, Any]]): The judged states, the stored-as state last

    Returns:
        tuple[Any, tuple[ConditionalGrant, ...]]: The Type of the first state refused (``_ALLOWED`` when none is),
            and the conditional assignments matching the last state judged conditionally - empty when the state
            stored is granted in full
    """
    matching: tuple[ConditionalGrant, ...] = ()

    for state in states:
        type_id: Any = state.get(CmdbObjectKey.TYPE_ID.value)

        if grants.allows(operation, type_id):
            matching = ()
            continue

        matching = evaluation.matching(operation, state) if evaluation is not None else ()

        if not matching:
            return type_id, ()

    return _ALLOWED, matching


def refusal_message(decision: AccessDecision) -> str | None:
    """
    What a refused decision says - the fields refused, or the operation refused on the Type

    Args:
        decision (AccessDecision): The decision

    Returns:
        str | None: The message; None for an allowed decision
    """
    if decision.allowed:
        return None

    if decision.step is AccessDecisionStep.FIELD_CLASS:
        return FIELDS_REFUSED_MESSAGE.format(names=list(decision.refused_fields), type_id=decision.type_id)

    return OPERATION_REFUSED_MESSAGE.format(operation=decision.operation.value, type_id=decision.type_id)


def can(user: CmdbUser, operation: ScopeOperation, before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None, trace: bool = False,
        field_classes: Mapping[str, str] | None = None) -> AccessDecision:
    """
    Decides whether a user may perform an operation on one object - the grants read once per request

    Functional rights are not part of it: the route's right check decides those before

    Args:
        user (CmdbUser): The user the request is made for
        operation (ScopeOperation): The operation
        before (Mapping[str, Any] | None): The stored object - needed by view, edit and delete
        after (Mapping[str, Any] | None): The object as it would be stored - needed by create and edit
        trace (bool): Whether the decision names the granting assignments. Defaults to False
        field_classes (Mapping[str, str] | None): The classed fields of the Type the object is stored as, when the
            caller holds that Type; None reads them (once per request, only for a write changing a field)

    Raises:
        ValueError: When a state the operation is judged on is not given
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        AccessDecision: The decision
    """
    grants: AccessGrants = load_grants(user)
    evaluation: ScopeEvaluation | None = load_scope_evaluation(user, grants) \
        if grants.conditional_entries(operation) else None
    # The Type's classes are read only for a write that changes a field
    writes_fields: bool = operation in FIELD_WRITING_OPERATIONS and bool(
        changed_field_names(before if operation is ScopeOperation.EDIT else None, after))
    classes: Mapping[str, str] = field_classes if field_classes is not None else type_field_classes(
        user, (after or {}).get(CmdbObjectKey.TYPE_ID.value)) if writes_fields else {}

    return decide(grants, operation, before, after, trace, evaluation, classes)


def unwritable_fields(user: CmdbUser, state: Mapping[str, Any], field_names: list[str],
                      operation: ScopeOperation = ScopeOperation.EDIT,
                      field_classes: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """
    Which of an object's fields the user may not write in a create or an edit - the required rule and the form ask it

    The object's Type held only conditionally is judged by the assignments matching the state; an object the user may
    not write at all leaves every field unwritable

    Args:
        user (CmdbUser): The user the request is made for
        state (Mapping[str, Any]): The object (as stored, or as it would be stored)
        field_names (list[str]): The fields asked about
        operation (ScopeOperation): CREATE or EDIT. Defaults to EDIT
        field_classes (Mapping[str, str] | None): The Type's classed fields when the caller holds the Type; None reads
            them (``type_field_classes``)

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        tuple[str, ...]: The unwritable names, in the order asked
    """
    grants: AccessGrants = load_grants(user)
    type_id: Any = state.get(CmdbObjectKey.TYPE_ID.value)
    matching: tuple[ConditionalGrant, ...] = ()

    if not grants.allows(operation, type_id):
        evaluation: ScopeEvaluation | None = load_scope_evaluation(user, grants) \
            if grants.conditional_entries(operation, type_id) else None
        matching = evaluation.matching(operation, state) if evaluation is not None else ()

        if not matching:
            return tuple(field_names)

    return refused_fields(grants, operation, type_id, field_names, matching,
                          type_field_classes(user, type_id) if field_classes is None else field_classes)


def _granting_assignment_ids(grants: AccessGrants, operation: ScopeOperation, type_ids: list[Any]
                             ) -> tuple[int, ...]:
    """
    The user's assignments granting the operation on any of the judged Types

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The operation
        type_ids (list[Any]): The judged Types

    Returns:
        tuple[int, ...]: Their public_ids, ascending, each once
    """
    return tuple(sorted({assignment_id for type_id in type_ids
                         for assignment_id in grants.granting_assignment_ids(operation, type_id)}))


def object_field_access(user: CmdbUser, document: Mapping[str, Any],
                        type_fields: list[dict[str, Any]]) -> dict[str, str]:
    """
    What the user may do with each field of one object in an edit - the render's ``field_access`` (phase 12, D8)

    Args:
        user (CmdbUser): The user the request is made for
        document (Mapping[str, Any]): The object
        type_fields (list[dict[str, Any]]): Its Type's field definitions - their classes are read from them

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        dict[str, str]: ``write`` / ``read`` / ``system`` per field
    """
    classes: dict[str, str] = classes_of_fields(type_fields)
    field_names: list[str] = [field[FieldKey.NAME.value] for field in type_fields
                              if isinstance(field, dict) and isinstance(field.get(FieldKey.NAME.value), str)]
    unwritable: set[str] = set(unwritable_fields(user, document, field_names, ScopeOperation.EDIT, classes))

    return {name: FieldAccess.SYSTEM.value if classes.get(name) == SYSTEM_FIELD_CLASS
            else FieldAccess.READ.value if name in unwritable else FieldAccess.WRITE.value
            for name in field_names}
