# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.manager.person_reference_helper

The ISMS keys that reference a person or a person group, one list per collection - read by the write check and the
delete clean-up alike - and the spelling of a polymorphic key's '_ref_type' sibling
"""
import pytest

from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    PERSON_ONLY_RISK_ASSESSMENT_KEYS,
    POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    ref_type_key,
)
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #


class TestPersonReferenceKeys:
    """The one list of person-reference keys per collection, shared by the clean-up and the write check"""

    def test_the_risk_assessment_keys_are_the_ones_the_cascade_clears(self) -> None:
        """The write check and the delete clean-up read the same tuples, so they cannot drift"""
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.polymorphic is POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.person_only is PERSON_ONLY_RISK_ASSESSMENT_KEYS

    def test_the_risk_assessment_person_only_keys(self) -> None:
        """The assessor and the interviewed persons can only ever be persons"""
        assert set(PERSON_ONLY_RISK_ASSESSMENT_KEYS) == {
            RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value,
        }

    def test_the_assignment_has_one_polymorphic_key_and_no_person_only_one(self) -> None:
        """The responsible-for-implementation reference, the key its clean-up clears"""
        assert CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.polymorphic == (
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value,
        )
        assert CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.person_only == ()

    @pytest.mark.parametrize('key, ref_type', [
        (RiskAssessmentKey.RISK_OWNER_ID.value, RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value),
        (RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value, RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value),
        (RiskAssessmentKey.AUDITOR_ID.value, RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value),
        (ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value,
         ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value),
    ])
    def test_ref_type_key_spells_the_stored_sibling(self, key: str, ref_type: str) -> None:
        """Every polymorphic key's sibling, as the model's key enums name it"""
        assert ref_type_key(key) == ref_type
