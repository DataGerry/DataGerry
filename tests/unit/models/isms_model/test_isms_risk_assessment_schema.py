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
type discriminator fields are constrained to their enum values. The three person ``_ref_type`` fields take null
like the ids they qualify - the pairing of a set id with a real type is the write routes' person-reference check.
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

SCHEMA: dict = IsmsRiskAssessment.SCHEMA
PERSON_REF_TYPE_KEYS: tuple[str, ...] = (
    RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value,
    RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value,
)
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


def _field_validates(key: str, document: dict[str, Any]) -> bool:
    """Validates a document against the one field's rule"""
    return Validator({key: SCHEMA[key]}).validate(document)


class TestPersonRefTypeNullability:
    """A person _ref_type is null exactly when there is nothing to qualify - the schema's half of that rule"""

    @pytest.mark.parametrize('key', PERSON_REF_TYPE_KEYS)
    @pytest.mark.parametrize('value', [None, *[reference_type.value for reference_type in PersonReferenceType]])
    def test_null_or_a_reference_type_is_accepted(self, key: str, value: Any) -> None:
        """Null for an id-less reference, the enum's values otherwise"""
        assert _field_validates(key, {key: value})

    @pytest.mark.parametrize('key', PERSON_REF_TYPE_KEYS)
    @pytest.mark.parametrize('value', ['person', 'NOBODY', '', 1])
    def test_anything_else_is_refused(self, key: str, value: Any) -> None:
        """Still pinned to the enum"""
        assert not _field_validates(key, {key: value})

    @pytest.mark.parametrize('key', PERSON_REF_TYPE_KEYS)
    def test_the_key_is_still_required(self, key: str) -> None:
        """Null is a value; leaving the key out is not"""
        assert not _field_validates(key, {})


# Values no id may take: 0, a negative number, a JSON boolean
NOT_AN_ID: list[Any] = [0, -1, True, False]
NOT_AN_ID_NAMES: list[str] = ['zero', 'negative', 'true', 'false']
A_STORED_ID: int = 7
MATRIX_KEYS: tuple[str, ...] = (RiskAssessmentKey.RISK_CALCULATION_BEFORE.value,
                                RiskAssessmentKey.RISK_CALCULATION_AFTER.value)


def _matrix_validates(matrix_key: str, matrix: dict[str, Any]) -> bool:
    """Validates one risk-calculation matrix against its rule"""
    return Validator({matrix_key: SCHEMA[matrix_key]}).validate({matrix_key: matrix})


def _matrix(impact_category_id: Any = A_STORED_ID, impact_id: Any = None, likelihood_id: Any = None) -> dict:
    """A matrix with one impacts row, every derived value null"""
    return {
        'impacts': [{'impact_category_id': impact_category_id, 'impact_id': impact_id}],
        'likelihood_id': likelihood_id, 'likelihood_value': None,
        'maximum_impact_id': None, 'maximum_impact_value': None,
    }


@pytest.mark.parametrize('matrix_key', MATRIX_KEYS)
class TestRiskCalculationIds:
    """Every id of a risk calculation is a whole number from 1, never a boolean; impact and likelihood may be null"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_an_impact_category_id_that_is_no_id_is_refused(self, matrix_key: str, value: Any) -> None:
        """Each used to be stored"""
        assert not _matrix_validates(matrix_key, _matrix(impact_category_id=value))

    def test_an_impact_category_id_may_not_be_null(self, matrix_key: str) -> None:
        """A row rates a category, so it has to name one"""
        assert not _matrix_validates(matrix_key, _matrix(impact_category_id=None))

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_an_impact_id_that_is_no_id_is_refused(self, matrix_key: str, value: Any) -> None:
        """``true`` used to be read as Impact 1 by the recalculation"""
        assert not _matrix_validates(matrix_key, _matrix(impact_id=value))

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_a_likelihood_id_that_is_no_id_is_refused(self, matrix_key: str, value: Any) -> None:
        """``true`` used to be read as Likelihood 1 by the recalculation"""
        assert not _matrix_validates(matrix_key, _matrix(likelihood_id=value))

    def test_an_unrated_row_and_likelihood_are_accepted(self, matrix_key: str) -> None:
        """null is not rated yet"""
        assert _matrix_validates(matrix_key, _matrix(impact_id=None, likelihood_id=None))

    def test_ids_from_one_are_accepted(self, matrix_key: str) -> None:
        """The control"""
        assert _matrix_validates(matrix_key, _matrix(A_STORED_ID, A_STORED_ID, A_STORED_ID))

    @pytest.mark.parametrize('derived_key', ['maximum_impact_id'])
    def test_a_derived_id_keeps_its_shape_rule_only(self, matrix_key: str, derived_key: str) -> None:
        """The server overwrites it on every write, so a client's 0 is not refused"""
        assert _matrix_validates(matrix_key, {**_matrix(), derived_key: 0})


class TestImplementationStatus:
    """``implementation_status`` names an option by id: a whole number from 1 or null, never a boolean"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_a_value_that_is_no_id_is_refused(self, value: Any) -> None:
        """Each used to be stored"""
        assert not _field_validates(RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
                                    {RiskAssessmentKey.IMPLEMENTATION_STATUS.value: value})

    @pytest.mark.parametrize('value', [None, A_STORED_ID], ids=['null', 'an-id'])
    def test_null_or_an_id_is_accepted(self, value: Any) -> None:
        """The control"""
        assert _field_validates(RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
                                {RiskAssessmentKey.IMPLEMENTATION_STATUS.value: value})
