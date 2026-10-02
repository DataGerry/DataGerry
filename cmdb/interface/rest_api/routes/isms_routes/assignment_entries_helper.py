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
The ControlMeasureAssignments a RiskAssessment write carries, held to the rules of the assignment's own routes

``POST`` / ``PUT /isms/risk_assessments/`` carry ``control_measure_assignments``: a list on create, a
``{created, updated, deleted}`` diff on update. Each entry becomes a stored IsmsControlMeasureAssignment, so it is
judged by the SAME write schema ``POST /isms/control_measure_assignments/`` validates with - required fields,
types, enum values, unknown keys purged - before anything is written:

* ``validated_create_payload`` / ``validated_update_payload`` check the container shape, then every entry, and
  answer the cleaned documents the route writes. A created entry's ``public_id`` is server-owned and dropped (the
  schema does not declare it); an updated entry keeps its integer ``public_id``, its identity. ``risk_assessment_id``
  is the route's to stamp, so the entry schema does not take it from the body either
* ``abort_on_duplicate_control_measures`` refuses a ControlMeasure assigned to one RiskAssessment more than once;
  ``assignments_after_update`` is what the assessment holds once an update is applied, which is what that rule is
  judged on
"""
from functools import cache
from http import HTTPStatus
from typing import Any, Iterable, NamedTuple

from cerberus import Validator
from flask import abort

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.utils import duplicate_names
from cmdb.interface.blueprints.schema_error_format import ERRORS_SEPARATOR, flatten_schema_errors
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ASSIGNMENT_CONTROL_MEASURE_DUPLICATE_MSG,
    ASSIGNMENT_ENTRY_INVALID_MSG,
    ASSIGNMENT_ENTRY_NOT_AN_OBJECT_MSG,
    ASSIGNMENT_ID_INVALID_MSG,
    ASSIGNMENTS_NOT_A_DIFF_MSG,
    ASSIGNMENTS_NOT_A_LIST_MSG,
    AssignmentDiffKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AssignmentDiff',
    'abort_on_duplicate_control_measures',
    'assignments_after_update',
    'validated_create_payload',
    'validated_update_payload',
]

_PUBLIC_ID_KEY: str = ControlMeasureAssignmentKey.PUBLIC_ID.value
_CONTROL_MEASURE_KEY: str = ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value


class AssignmentDiff(NamedTuple):
    """The validated ControlMeasureAssignment diff of a RiskAssessment update"""
    created: list[dict[str, Any]]
    updated: list[dict[str, Any]]
    deleted: list[int]


@cache
def _entry_schema() -> dict[str, Any]:
    """
    The ControlMeasureAssignment write schema without ``risk_assessment_id``, which the route stamps

    Returns:
        dict[str, Any]: The schema every embedded entry is validated with
    """
    schema: dict[str, Any] = build_write_schema(IsmsControlMeasureAssignment.SCHEMA)
    schema.pop(ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value, None)

    return schema


def _is_public_id(value: Any) -> bool:
    """
    Answers whether a value can name a stored assignment

    Args:
        value (Any): The value, as sent

    Returns:
        bool: True for an integer that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _validated_entry(entry: Any, position: str) -> dict[str, Any]:
    """
    One embedded assignment, judged by the assignment write schema

    Args:
        entry (Any): The entry, as sent
        position (str): Where it sits in the payload, for the refusal (e.g. ``created #2``)

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for an entry that is no object or fails the schema

    Returns:
        dict[str, Any]: The cleaned entry - unknown keys and ``public_id`` purged
    """
    if not isinstance(entry, dict):
        abort(HTTPStatus.BAD_REQUEST, ASSIGNMENT_ENTRY_NOT_AN_OBJECT_MSG.format(position=position))

    validator = Validator(_entry_schema(), purge_unknown=True)

    if not validator.validate(entry):
        abort(HTTPStatus.BAD_REQUEST, ASSIGNMENT_ENTRY_INVALID_MSG.format(
            position=position, errors=ERRORS_SEPARATOR.join(flatten_schema_errors(validator.errors)),
        ))

    return validator.document


def _validated_list(entries: Any, label: str) -> list[dict[str, Any]]:
    """
    Every entry of one list of embedded assignments

    Args:
        entries (Any): The list, as sent; None is an empty list
        label (str): The list's name in the refusal

    Returns:
        list[dict[str, Any]]: The cleaned entries, in payload order
    """
    return [_validated_entry(entry, f'{label} #{index}') for index, entry in enumerate(entries or [], start=1)]


def validated_create_payload(value: Any) -> list[dict[str, Any]]:
    """
    The assignments a new RiskAssessment is created with: a list of entries, each a valid assignment

    Args:
        value (Any): ``control_measure_assignments`` as sent; None is no assignments

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for anything but a list, or an invalid entry

    Returns:
        list[dict[str, Any]]: The cleaned entries, without ``public_id`` and ``risk_assessment_id``
    """
    if value is None:
        return []

    if not isinstance(value, list):
        abort(HTTPStatus.BAD_REQUEST, ASSIGNMENTS_NOT_A_LIST_MSG)

    return _validated_list(value, AssignmentDiffKey.CREATED.value)


def validated_update_payload(value: Any) -> AssignmentDiff:
    """
    The assignment diff of a RiskAssessment update: created and updated entries, deleted ids

    A created entry is judged like a create's. An updated one also needs its integer ``public_id`` - the route
    then checks it belongs to this assessment - and a deleted one is that id alone

    Args:
        value (Any): ``control_measure_assignments`` as sent; None is no change

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for anything but the diff object, an invalid entry or an
            id that is no integer

    Returns:
        AssignmentDiff: The cleaned diff
    """
    if value is None:
        return AssignmentDiff([], [], [])

    allowed: list[str] = [key.value for key in AssignmentDiffKey]
    not_a_diff: str = ASSIGNMENTS_NOT_A_DIFF_MSG.format(keys=allowed)

    if not isinstance(value, dict) or set(value) - set(allowed) or any(
            not isinstance(value.get(key) or [], list) for key in allowed):
        abort(HTTPStatus.BAD_REQUEST, not_a_diff)

    created: list[dict[str, Any]] = _validated_list(
        value.get(AssignmentDiffKey.CREATED.value), AssignmentDiffKey.CREATED.value,
    )
    updated: list[dict[str, Any]] = []

    for index, entry in enumerate(value.get(AssignmentDiffKey.UPDATED.value) or [], start=1):
        position: str = f'{AssignmentDiffKey.UPDATED.value} #{index}'
        cleaned: dict[str, Any] = _validated_entry(entry, position)
        public_id: Any = entry.get(_PUBLIC_ID_KEY)

        if not _is_public_id(public_id):
            abort(HTTPStatus.BAD_REQUEST, ASSIGNMENT_ID_INVALID_MSG.format(position=position, value=public_id))

        updated.append({**cleaned, _PUBLIC_ID_KEY: public_id})

    deleted: list[int] = []

    for index, public_id in enumerate(value.get(AssignmentDiffKey.DELETED.value) or [], start=1):
        if not _is_public_id(public_id):
            abort(HTTPStatus.BAD_REQUEST, ASSIGNMENT_ID_INVALID_MSG.format(
                position=f'{AssignmentDiffKey.DELETED.value} #{index}', value=public_id,
            ))

        deleted.append(public_id)

    return AssignmentDiff(created, updated, deleted)


def assignments_after_update(stored: dict[int, dict[str, Any]], diff: AssignmentDiff) -> list[dict[str, Any]]:
    """
    The assignments a RiskAssessment holds once an update's diff is applied

    Args:
        stored (dict[int, dict[str, Any]]): Its stored assignments, by public_id
        diff (AssignmentDiff): The validated diff (its updated and deleted ids already checked to be stored)

    Returns:
        list[dict[str, Any]]: The stored ones not deleted - an updated one as updated - and the created ones
    """
    updated_by_id: dict[int, dict[str, Any]] = {entry[_PUBLIC_ID_KEY]: entry for entry in diff.updated}
    deleted: set[int] = set(diff.deleted)

    kept: list[dict[str, Any]] = [
        updated_by_id.get(public_id, assignment)
        for public_id, assignment in stored.items() if public_id not in deleted
    ]

    return kept + list(diff.created)


def abort_on_duplicate_control_measures(assignments: Iterable[dict[str, Any]]) -> None:
    """
    Refuses a RiskAssessment that would hold one ControlMeasure more than once

    Args:
        assignments (Iterable[dict[str, Any]]): Every assignment the assessment would hold

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the ControlMeasures assigned more than once
    """
    repeated: list[Any] = duplicate_names([assignment.get(_CONTROL_MEASURE_KEY) for assignment in assignments])

    if repeated:
        abort(HTTPStatus.BAD_REQUEST, ASSIGNMENT_CONTROL_MEASURE_DUPLICATE_MSG.format(ids=sorted(repeated)))
