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
Unit tests for the IsmsRiskAssessment validation schema

Pins the two behaviours changed in the ISMS sweep: the before/after risk_calculation matrices are
built from one shared sub-schema (identical cell shape), with the before-matrix impacts required and
the after-matrix impacts optional (an untreated assessment has no after sliders); and the reference-
type discriminator fields are constrained to their enum values.
"""
from cmdb.models.isms_model import IsmsRiskAssessment
# -------------------------------------------------------------------------------------------------------------------- #

SCHEMA: dict = IsmsRiskAssessment.SCHEMA
_SHARED_CELL_KEYS = ('likelihood_id', 'likelihood_value', 'maximum_impact_id', 'maximum_impact_value')


class TestRiskCalculationSchema:
    """The before/after risk_calculation matrices come from one shared builder."""

    def test_before_and_after_share_the_same_cell_shape(self) -> None:
        """Both matrices expose the same keys and identical impact-entry / scalar rules."""
        before = SCHEMA['risk_calculation_before']['schema']
        after = SCHEMA['risk_calculation_after']['schema']

        assert set(before) == set(after)
        assert before['impacts']['schema'] == after['impacts']['schema']
        assert {key: before[key] for key in _SHARED_CELL_KEYS} == {key: after[key] for key in _SHARED_CELL_KEYS}

    def test_before_impacts_required_after_optional(self) -> None:
        """before.impacts is required; after.impacts is optional (untreated assessments have none)."""
        assert SCHEMA['risk_calculation_before']['schema']['impacts']['required'] is True
        assert SCHEMA['risk_calculation_after']['schema']['impacts']['required'] is False


class TestReferenceTypeConstraints:
    """The *_ref_type discriminator fields are constrained to their enum values."""

    def test_object_ref_type_allowed(self) -> None:
        """object_id_ref_type only accepts the ObjectReferenceType values."""
        assert set(SCHEMA['object_id_ref_type']['allowed']) == {'OBJECT', 'OBJECT_GROUP'}

    def test_person_ref_types_allowed(self) -> None:
        """Every person ref_type field only accepts the PersonReferenceType values."""
        for field in ('risk_owner_id_ref_type', 'responsible_persons_id_ref_type', 'auditor_id_ref_type'):
            assert set(SCHEMA[field]['allowed']) == {'PERSON', 'PERSON_GROUP'}
