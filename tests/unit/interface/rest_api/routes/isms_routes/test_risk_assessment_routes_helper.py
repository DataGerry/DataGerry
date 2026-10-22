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
Unit tests for the pure helpers of risk_assessment_routes

``_assignments_person_references``: the person references of the assignments a RiskAssessment write carries, read
with the assignment's own keys. The list's naming steps are tested with their module
(``test_risk_assessment_naming_helper``).
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_routes import _assignments_person_references
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import PersonReference
from cmdb.manager.person_reference_helper import ref_type_key
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

IMPLEMENTER_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value


def test_assignment_references_are_read_from_every_assignment_in_order() -> None:
    """One reference per assignment naming somebody; an assignment naming nobody adds none"""
    assignments: list[dict[str, Any]] = [
        {IMPLEMENTER_KEY: 70, ref_type_key(IMPLEMENTER_KEY): PersonReferenceType.PERSON.value},
        {IMPLEMENTER_KEY: None, ref_type_key(IMPLEMENTER_KEY): None},
        {IMPLEMENTER_KEY: 71, ref_type_key(IMPLEMENTER_KEY): PersonReferenceType.PERSON_GROUP.value},
    ]

    assert _assignments_person_references(assignments) == [
        PersonReference(IMPLEMENTER_KEY, 70, PersonReferenceType.PERSON.value),
        PersonReference(IMPLEMENTER_KEY, 71, PersonReferenceType.PERSON_GROUP.value),
    ]


def test_no_assignments_carry_no_references() -> None:
    """A RiskAssessment write without assignments"""
    assert not _assignments_person_references([])
