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
Unit tests for cmdb.class_schema.id_schema_helper - the Cerberus rule of a field holding a public_id

Pinned through a real Validator: a whole number from 1 passes; 0, a negative number, a JSON boolean and text are
refused, the boolean with its own message; ``required`` / ``nullable`` do what they say; every call hands out a new
dict. And through every RiskAssessment schema key that names a document by its id: each refuses those values.
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.class_schema_constants import ID_IS_NO_BOOLEAN_MSG
from cmdb.class_schema.id_schema_helper import MIN_PUBLIC_ID, check_no_boolean, get_id_rule
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'target_id'
VALID_ID: int = 7
REFUSED_IDS: list[Any] = [0, -1, True, False, '7', 1.0]
REFUSED_IDS_NAMES: list[str] = ['zero', 'negative', 'true', 'false', 'text', 'float']

# The RiskAssessment keys naming another document by its id - the risk, the object, the persons
RISK_ASSESSMENT_ID_KEYS: list[str] = [
    RiskAssessmentKey.RISK_ID.value,
    RiskAssessmentKey.OBJECT_ID.value,
    RiskAssessmentKey.RISK_ASSESSOR_ID.value,
    RiskAssessmentKey.RISK_OWNER_ID.value,
    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
    RiskAssessmentKey.AUDITOR_ID.value,
]


def _validate(rule: dict[str, Any], document: dict[str, Any]) -> Validator:
    """A validator over one field, run on the document"""
    validator = Validator({FIELD: rule})
    validator.validate(document)
    return validator


class TestGetIdRule:
    """get_id_rule"""

    def test_a_whole_number_from_one_passes(self) -> None:
        """The smallest id and any larger one"""
        assert _validate(get_id_rule(), {FIELD: MIN_PUBLIC_ID}).errors == {}
        assert _validate(get_id_rule(), {FIELD: VALID_ID}).errors == {}

    @pytest.mark.parametrize('value', REFUSED_IDS, ids=REFUSED_IDS_NAMES)
    def test_anything_else_is_refused(self, value: Any) -> None:
        """Including a boolean, which Cerberus' integer type alone lets through"""
        assert FIELD in _validate(get_id_rule(), {FIELD: value}).errors

    @pytest.mark.parametrize('value', [True, False], ids=['true', 'false'])
    def test_a_boolean_is_refused_with_its_own_message(self, value: bool) -> None:
        """So the caller learns why"""
        assert ID_IS_NO_BOOLEAN_MSG in _validate(get_id_rule(), {FIELD: value}).errors[FIELD]

    def test_required_and_nullable(self) -> None:
        """Absent / null as the arguments say"""
        assert FIELD in _validate(get_id_rule(), {}).errors
        assert _validate(get_id_rule(required=False), {}).errors == {}
        assert FIELD in _validate(get_id_rule(), {FIELD: None}).errors
        assert _validate(get_id_rule(nullable=True), {FIELD: None}).errors == {}

    def test_every_call_is_a_new_rule(self) -> None:
        """A schema adding to it never changes another's"""
        assert get_id_rule() is not get_id_rule()

    def test_check_no_boolean_leaves_an_integer_alone(self) -> None:
        """Only the boolean reports"""
        reported: list[tuple[str, str]] = []

        check_no_boolean(FIELD, VALID_ID, lambda field, message: reported.append((field, message)))
        check_no_boolean(FIELD, True, lambda field, message: reported.append((field, message)))

        assert reported == [(FIELD, ID_IS_NO_BOOLEAN_MSG)]


class TestTheRiskAssessmentIds:
    """Every id key of the RiskAssessment schema carries the rule"""

    @pytest.mark.parametrize('key', RISK_ASSESSMENT_ID_KEYS)
    @pytest.mark.parametrize('value', REFUSED_IDS, ids=REFUSED_IDS_NAMES)
    def test_a_value_that_is_no_id_is_refused(self, key: str, value: Any) -> None:
        """0, negatives, booleans, text, floats"""
        validator = Validator({key: IsmsRiskAssessment.SCHEMA[key]})

        assert not validator.validate({key: value})

    @pytest.mark.parametrize('key', RISK_ASSESSMENT_ID_KEYS)
    def test_an_id_passes(self, key: str) -> None:
        """The control"""
        assert Validator({key: IsmsRiskAssessment.SCHEMA[key]}).validate({key: VALID_ID})

    @pytest.mark.parametrize('items', [[True], [VALID_ID, 0], [-2]], ids=['boolean', 'zero', 'negative'])
    def test_an_interviewed_person_that_is_no_id_is_refused(self, items: list[Any]) -> None:
        """The list's items carry the rule too"""
        key: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value

        assert not Validator({key: IsmsRiskAssessment.SCHEMA[key]}).validate({key: items})

    def test_the_risk_and_the_object_are_required_and_never_null(self) -> None:
        """An assessment always assesses one risk for one object"""
        for key in (RiskAssessmentKey.RISK_ID.value, RiskAssessmentKey.OBJECT_ID.value):
            rule: dict[str, Any] = IsmsRiskAssessment.SCHEMA[key]
            assert (rule['required'], rule['nullable']) == (True, False)
