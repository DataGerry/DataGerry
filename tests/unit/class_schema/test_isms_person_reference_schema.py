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
Unit tests for the person-reference rules of the two ISMS write schemas

Pure Cerberus tests, one field at a time: the assignment's ``responsible_for_implementation_id_ref_type`` names
one of the PersonReferenceType values or nothing, and an assessment's ``interviewed_persons`` holds positive
integer ids only. That an id names an existing person is the write route's check, not the schema's
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

IMPLEMENTER_REF_TYPE_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value
INTERVIEWED_KEY: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value


def _field_errors(schema: dict[str, Any], key: str, value: Any) -> Any:
    """The errors one field's value raises under a write schema; the other fields' errors are ignored"""
    validator = Validator(build_write_schema(schema))
    validator.validate({key: value})

    return validator.errors.get(key)


@pytest.mark.parametrize('reference_type', [*[member.value for member in PersonReferenceType], None])
def test_the_assignment_ref_type_accepts_a_person_reference_type_or_null(reference_type: Any) -> None:
    """Null stays legal: an assignment without a responsible person carries no ref_type either"""
    assert _field_errors(IsmsControlMeasureAssignment.SCHEMA, IMPLEMENTER_REF_TYPE_KEY, reference_type) is None


@pytest.mark.parametrize('reference_type', ['FOO', 'person', ''], ids=['unknown', 'lower-case', 'empty'])
def test_the_assignment_ref_type_refuses_anything_else(reference_type: str) -> None:
    """A value naming neither collection would never be cleaned by a person or group delete"""
    assert _field_errors(IsmsControlMeasureAssignment.SCHEMA, IMPLEMENTER_REF_TYPE_KEY, reference_type)


@pytest.mark.parametrize('interviewed', [[], [1], [1, 2, 3], None], ids=['empty', 'one', 'several', 'null'])
def test_interviewed_persons_accepts_positive_integer_ids(interviewed: Any) -> None:
    """An empty list and null both mean nobody was interviewed"""
    assert _field_errors(IsmsRiskAssessment.SCHEMA, INTERVIEWED_KEY, interviewed) is None


@pytest.mark.parametrize('entry', [0, -5, 'x', 1.5, {'a': 1}, [1]],
                         ids=['zero', 'negative', 'string', 'fraction', 'document', 'nested-list'])
def test_interviewed_persons_refuses_an_entry_that_is_no_id(entry: Any) -> None:
    """
    Each entry is a CmdbPerson public_id, so anything else is refused before the reference check

    A bool is not among them: Cerberus counts it as an integer, so it is the reference check that refuses it
    """
    assert _field_errors(IsmsRiskAssessment.SCHEMA, INTERVIEWED_KEY, [1, entry])
