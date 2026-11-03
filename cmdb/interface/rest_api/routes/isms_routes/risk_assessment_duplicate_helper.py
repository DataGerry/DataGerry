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
The pieces of ``POST /isms/risk_assessments/duplicate/<mode>/<ids>`` that decide what is copied, and where to

* ``parse_duplicate_target_ids`` reads the comma-separated target ids: each a distinct whole number from 1 to the
  largest integer MongoDB stores, every violation named in one 400 before anything is read or written
* ``abort_if_duplicate_source_missing`` answers 404 when the body's ``public_id`` names no stored RiskAssessment
* ``read_source_assignments`` reads the source's ControlMeasureAssignments once, a failed read answering its 400
* ``copied_assignments`` turns them into the documents one duplicate stores
"""
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.utils import duplicate_names
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG,
    DUPLICATE_SOURCE_NOT_FOUND_MSG,
    DUPLICATE_TARGET_SEPARATOR,
    DUPLICATE_TARGETS_INVALID_REASON,
    DUPLICATE_TARGETS_REASON_SEPARATOR,
    DUPLICATE_TARGETS_REFUSED_MSG,
    DUPLICATE_TARGETS_REPEATED_REASON,
    MAX_DUPLICATE_TARGET_ID,
    MIN_DUPLICATE_TARGET_ID,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'abort_if_duplicate_source_missing',
    'copied_assignments',
    'parse_duplicate_target_ids',
    'read_source_assignments',
]


def _target_id(token: str) -> int | None:
    """
    Reads one target id token, or None when it is no whole number in the stored bounds

    Only ASCII digits count: ``str.isdigit`` also accepts characters ``int`` cannot read, such as '²'

    Args:
        token (str): One comma-separated token of the path, surrounding whitespace already removed

    Returns:
        int | None: The id, or None when the token is not a valid target id
    """
    if not (token.isascii() and token.isdigit()):
        return None

    value: int = int(token)

    return value if MIN_DUPLICATE_TARGET_ID <= value <= MAX_DUPLICATE_TARGET_ID else None


def parse_duplicate_target_ids(segment: str) -> list[int]:
    """
    Reads the comma-separated target ids of a duplicate, in the order sent

    Every token has to be a whole number from MIN_DUPLICATE_TARGET_ID to MAX_DUPLICATE_TARGET_ID, and no id may
    be sent twice (it would store two identical duplicates on one target). Whitespace around a token is ignored

    Args:
        segment (str): The ``<ids>`` path segment, e.g. '1,3,4'

    Raises:
        HTTPException: 400 naming every invalid token and every repeated id, before anything is read or written

    Returns:
        list[int]: The target ids
    """
    tokens: list[str] = [token.strip() for token in segment.split(DUPLICATE_TARGET_SEPARATOR)]
    parsed: list[int | None] = [_target_id(token) for token in tokens]

    invalid: list[str] = [token for token, value in zip(tokens, parsed) if value is None]
    target_ids: list[int] = [value for value in parsed if value is not None]
    repeated: list[int] = duplicate_names(target_ids)

    reasons: list[str] = []

    if invalid:
        reasons.append(DUPLICATE_TARGETS_INVALID_REASON.format(
            minimum=MIN_DUPLICATE_TARGET_ID, maximum=MAX_DUPLICATE_TARGET_ID, tokens=invalid,
        ))

    if repeated:
        reasons.append(DUPLICATE_TARGETS_REPEATED_REASON.format(ids=repeated))

    if reasons:
        abort(HTTPStatus.BAD_REQUEST,
              DUPLICATE_TARGETS_REFUSED_MSG.format(reasons=DUPLICATE_TARGETS_REASON_SEPARATOR.join(reasons)))

    return target_ids


def abort_if_duplicate_source_missing(manager: RiskAssessmentManager, source_id: int) -> None:
    """
    Refuses a duplicate whose source RiskAssessment is not stored

    The source id decides whose ControlMeasureAssignments are copied, so it has to name a stored assessment. One
    projected read of the id alone

    Args:
        manager (RiskAssessmentManager): The RiskAssessment manager of the request
        source_id (int): The body's ``public_id``

    Raises:
        HTTPException: 404 when no RiskAssessment carries the id
        RiskAssessmentManagerGetError: When the read fails
    """
    if source_id not in manager.find_existing_public_ids([source_id]):
        abort(HTTPStatus.NOT_FOUND, DUPLICATE_SOURCE_NOT_FOUND_MSG.format(public_id=source_id))


def read_source_assignments(manager: RiskAssessmentManager, source_id: int) -> list[dict[str, Any]]:
    """
    Reads the ControlMeasureAssignments of the source RiskAssessment, once for every duplicate

    Args:
        manager (RiskAssessmentManager): The RiskAssessment manager of the request
        source_id (int): The public_id of the source RiskAssessment

    Raises:
        HTTPException: 400 when the read fails, the error logged

    Returns:
        list[dict[str, Any]]: The stored assignments, without ``_id``
    """
    try:
        return manager.get_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            criteria={ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: source_id},
        )
    except BaseManagerGetError as err:
        LOGGER.error("[read_source_assignments] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(HTTPStatus.BAD_REQUEST, DUPLICATE_SOURCE_ASSIGNMENTS_READ_MSG)


def copied_assignments(originals: list[dict[str, Any]], risk_assessment_id: int) -> list[dict[str, Any]]:
    """
    The source's assignments as one duplicate stores them: re-pointed at the duplicate, their ids the server's

    Args:
        originals (list[dict[str, Any]]): The source's stored assignments; not changed
        risk_assessment_id (int): The public_id of the duplicate they are copied onto

    Returns:
        list[dict[str, Any]]: One new document per original, without ``public_id``
    """
    copies: list[dict[str, Any]] = []

    for original in originals:
        copy: dict[str, Any] = {
            key: value for key, value in original.items() if key != ControlMeasureAssignmentKey.PUBLIC_ID.value
        }
        copy[ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value] = risk_assessment_id
        copies.append(copy)

    return copies
