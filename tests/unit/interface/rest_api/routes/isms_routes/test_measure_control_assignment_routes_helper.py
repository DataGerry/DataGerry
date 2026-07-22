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
Unit tests for build_cma_summary (measure_control_assignment_routes)

The helper is pure (no database): given a RiskAssessment plus the pre-fetched risk / object /
object-summary / type / object-group lookup maps, it composes the ControlMeasureAssignment display
summary, or returns None when the assignment has no RiskAssessment.
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.measure_control_assignment_routes import build_cma_summary
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
