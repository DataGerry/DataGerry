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
Unit tests for the helpers of measure_control_assignment_routes

``build_cma_summary`` is pure (no database): given a RiskAssessment plus the pre-fetched risk / object /
object-summary / type / object-group lookup maps, it composes the ControlMeasureAssignment display
summary, or returns None when the assignment has no RiskAssessment.

``guard_assignment_references`` runs with stub managers: the ControlMeasure, the RiskAssessment and the person
references are each checked, in that order, and the first that does not resolve refuses the write. Last, the
RiskAssessment may not already hold another assignment of the ControlMeasure
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.interface.rest_api.routes.isms_routes import measure_control_assignment_routes
from cmdb.interface.rest_api.routes.isms_routes.measure_control_assignment_routes import (
    build_cma_summary,
    guard_assignment_references,
)
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

RA_ID: int = 5
RISK_ID: int = 7
OBJECT_ID: int = 9
TYPE_ID: int = 11
OBJECT_GROUP_ID: int = 13

RISKS: dict[int, dict[str, Any]] = {RISK_ID: {'public_id': RISK_ID, 'name': 'MyRisk'}}
OBJECT_MAP: dict[int, dict[str, Any]] = {OBJECT_ID: {'public_id': OBJECT_ID, 'type_id': TYPE_ID}}
OBJECT_SUMMARIES: dict[int, str] = {OBJECT_ID: 'Obj summary'}
TYPES_MAP: dict[int, dict[str, Any]] = {TYPE_ID: {'public_id': TYPE_ID, 'label': 'Server'}}
OBJECT_GROUPS: dict[int, str] = {OBJECT_GROUP_ID: 'MyGroup'}


def _summary(risk_assessment: dict[str, Any] | None) -> str | None:
    """Runs build_cma_summary with the shared lookup maps."""
    return build_cma_summary(risk_assessment, RISKS, OBJECT_MAP, OBJECT_SUMMARIES, TYPES_MAP, OBJECT_GROUPS)


def test_returns_none_without_risk_assessment() -> None:
    """An assignment with no RiskAssessment yields None."""
    assert _summary(None) is None


def test_object_reference_includes_summary_and_type_label() -> None:
    """An OBJECT-typed assessment renders the object summary line plus the type label."""
    risk_assessment = {
        'public_id': RA_ID, 'risk_id': RISK_ID,
        'object_id_ref_type': ObjectReferenceType.OBJECT, 'object_id': OBJECT_ID,
    }

    assert _summary(risk_assessment) == f"#{RA_ID} - MyRisk @ Obj summary (Server)"


def test_object_group_reference_uses_group_name() -> None:
    """An OBJECT_GROUP-typed assessment renders the object group's name."""
    risk_assessment = {
        'public_id': RA_ID, 'risk_id': RISK_ID,
        'object_id_ref_type': ObjectReferenceType.OBJECT_GROUP, 'object_id': OBJECT_GROUP_ID,
    }

    assert _summary(risk_assessment) == f"#{RA_ID} - MyRisk @ MyGroup"


def test_unknown_risk_id_renders_empty_risk_name() -> None:
    """A risk_id absent from the risks map leaves the risk name blank."""
    risk_assessment = {
        'public_id': RA_ID, 'risk_id': 999,
        'object_id_ref_type': ObjectReferenceType.OBJECT_GROUP, 'object_id': OBJECT_GROUP_ID,
    }

    assert _summary(risk_assessment) == f"#{RA_ID} -  @ MyGroup"


def test_object_without_known_type_renders_empty_type_label() -> None:
    """An OBJECT whose type is not in the types map renders an empty type label."""
    risk_assessment = {
        'public_id': RA_ID, 'risk_id': RISK_ID,
        'object_id_ref_type': ObjectReferenceType.OBJECT, 'object_id': OBJECT_ID,
    }
    types_map: dict[int, dict[str, Any]] = {}

    result = build_cma_summary(risk_assessment, RISKS, OBJECT_MAP, OBJECT_SUMMARIES, types_map, OBJECT_GROUPS)

    assert result == f"#{RA_ID} - MyRisk @ Obj summary ()"


# -------------------------------------------------------------------------------------------------------------------- #

MEASURE_ID: int = 31
ASSESSMENT_ID: int = 32
UPDATED_ASSIGNMENT_ID: int = 33
ASSIGNMENT: dict[str, Any] = {
    ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value: MEASURE_ID,
    ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: ASSESSMENT_ID,
}


class TestGuardAssignmentReferences:
    """Every reference of an assignment write resolves, or the write is refused before it runs"""

    @pytest.fixture(name='wiring')
    def fixture_wiring(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
        """Stub managers behind ManagerProvider, and a recording person-reference check"""
        risk_assessment_manager = MagicMock()
        risk_assessment_manager.find_existing_public_ids.return_value = {ASSESSMENT_ID}
        monkeypatch.setattr(
            measure_control_assignment_routes.ManagerProvider, 'get_manager',
            lambda manager_type, _user: risk_assessment_manager if manager_type is ManagerType.RISK_ASSESSMENT
            else None,
        )
        person_check = MagicMock()
        monkeypatch.setattr(measure_control_assignment_routes, 'check_person_references', person_check)
        assignment_manager = MagicMock()
        assignment_manager.get_missing_control_measure_ids.return_value = set()
        assignment_manager.is_control_measure_assigned.return_value = False

        return {'assignments': assignment_manager, 'assessments': risk_assessment_manager, 'persons': person_check}

    def test_passes_and_checks_every_reference(self, wiring: dict[str, MagicMock]) -> None:
        """The measure, the assessment and the handed-in person references"""
        request_user = MagicMock()
        references = [MagicMock()]

        with Flask(__name__).app_context():
            guard_assignment_references(ASSIGNMENT, references, wiring['assignments'], request_user)

        wiring['assignments'].get_missing_control_measure_ids.assert_called_once_with([ASSIGNMENT])
        wiring['assessments'].find_existing_public_ids.assert_called_once_with([ASSESSMENT_ID])
        wiring['persons'].assert_called_once_with(references, request_user)
        wiring['assignments'].is_control_measure_assigned.assert_called_once_with(ASSESSMENT_ID, MEASURE_ID, None)

    def test_an_unknown_control_measure_is_refused_first(self, wiring: dict[str, MagicMock]) -> None:
        """Nothing else is asked once the measure is missing"""
        wiring['assignments'].get_missing_control_measure_ids.return_value = {MEASURE_ID}

        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            guard_assignment_references(ASSIGNMENT, [], wiring['assignments'], MagicMock())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str(MEASURE_ID) in caught.value.description
        wiring['assessments'].find_existing_public_ids.assert_not_called()
        wiring['persons'].assert_not_called()

    def test_an_unknown_risk_assessment_is_refused(self, wiring: dict[str, MagicMock]) -> None:
        """An assignment linked to no assessment would be an orphan the assessment's delete never removes"""
        wiring['assessments'].find_existing_public_ids.return_value = set()

        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            guard_assignment_references(ASSIGNMENT, [], wiring['assignments'], MagicMock())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str(ASSESSMENT_ID) in caught.value.description
        wiring['persons'].assert_not_called()

    def test_a_measure_the_assessment_already_holds_is_refused(self, wiring: dict[str, MagicMock]) -> None:
        """A 400 naming both ids, judged after every reference resolved"""
        wiring['assignments'].is_control_measure_assigned.return_value = True

        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            guard_assignment_references(ASSIGNMENT, [], wiring['assignments'], MagicMock())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert f'ID:{MEASURE_ID}' in caught.value.description
        assert f'ID:{ASSESSMENT_ID}' in caught.value.description
        wiring['persons'].assert_called_once()

    def test_an_update_does_not_count_itself(self, wiring: dict[str, MagicMock]) -> None:
        """The assignment being updated is handed on, so its own stored row is no duplicate"""
        with Flask(__name__).app_context():
            guard_assignment_references(
                ASSIGNMENT, [], wiring['assignments'], MagicMock(), exclude_public_id=UPDATED_ASSIGNMENT_ID,
            )

        wiring['assignments'].is_control_measure_assigned.assert_called_once_with(
            ASSESSMENT_ID, MEASURE_ID, UPDATED_ASSIGNMENT_ID,
        )
