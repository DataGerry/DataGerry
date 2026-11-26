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
object out of their reach or into someone else's. A create or an edit must also be allowed to write each changed field;
every field is a regular field, written through a role granting the operation with ``write_regular_fields``. With a
trace the decision also names the user's assignments granting the operation on the judged Types

A Type held only through **conditional assignments** (phase 9, R21) allows the operation on a state its condition
matches - judged in memory (``scope_matcher``) on each judged state, so an edit may neither move an object out of the
user's scope nor into it from outside; the changed fields are judged against the assignments matching the state the
object is stored as
"""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cmdb.models.access_model import ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine.access_engine_constants import (
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
                   matching: tuple[ConditionalGrant, ...] = ()) -> tuple[str, ...]:
    """
    The changed fields the user may not write on a Type through roles granting the operation

    Args:
        grants (AccessGrants): The user's grants
        operation (ScopeOperation): The writing operation
        type_id (Any): The Type the object is to be stored as
        changed (list[str]): The changed field names, ascending
        matching (tuple[ConditionalGrant, ...]): The conditional assignments matching the state stored - a role of
            theirs writing regular fields counts too

    Returns:
        tuple[str, ...]: The refused names, ascending; empty when every one may be written
    """
    if grants.writes_regular_fields(operation, type_id) or any(grant.entry.write_regular_fields
                                                               for grant in matching):
        return ()

    return tuple(changed)


def decide(grants: AccessGrants, operation: ScopeOperation, before: Mapping[str, Any] | None = None,
           after: Mapping[str, Any] | None = None, trace: bool = False,
           evaluation: ScopeEvaluation | None = None) -> AccessDecision:
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
            changed_field_names(before if operation is ScopeOperation.EDIT else None, after), matching)

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
        after: Mapping[str, Any] | None = None, trace: bool = False) -> AccessDecision:
    """
    Decides whether a user may perform an operation on one object - the grants read once per request

    Functional rights are not part of it: the route's right check decides those before

    Args:
        user (CmdbUser): The user the request is made for
        operation (ScopeOperation): The operation
        before (Mapping[str, Any] | None): The stored object - needed by view, edit and delete
        after (Mapping[str, Any] | None): The object as it would be stored - needed by create and edit
        trace (bool): Whether the decision names the granting assignments. Defaults to False

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

    return decide(grants, operation, before, after, trace, evaluation)


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
