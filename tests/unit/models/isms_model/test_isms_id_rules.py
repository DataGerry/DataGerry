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
Unit tests: every id an ISMS document stores follows the shared id rule (a whole number from 1, never a boolean)

Pinned per schema: each ISMS document's own ``public_id``; the four option fields (the Threat, Vulnerability and
ControlMeasure ``source``, the Risk's ``category_id`` - null allowed); the ControlMeasureAssignment's ControlMeasure,
RiskAssessment and responsible person; every item of a Risk's three id lists; an ImpactCategory description's Impact.
Each refuses 0, a negative number and a JSON boolean (and a list item anything that is no id); each accepts an id from 1
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsRiskAssessment,
    IsmsRiskClass,
    IsmsRiskMatrix,
    IsmsThreat,
    IsmsVulnerability,
)
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_MODELS: list[Any] = [
    IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsImpact, IsmsImpactCategory, IsmsLikelihood,
    IsmsProtectionGoal, IsmsRisk, IsmsRiskAssessment, IsmsRiskClass, IsmsRiskMatrix, IsmsThreat, IsmsVulnerability,
]
NOT_AN_ID: list[Any] = [0, -1, True, False]
NOT_AN_ID_NAMES: list[str] = ['zero', 'negative', 'true', 'false']
AN_ID: int = 7
PUBLIC_ID: str = 'public_id'


def _validates(schema: dict[str, Any], key: str, value: Any) -> bool:
    """Validates a document holding only `key` against the one field's rule"""
    return Validator({key: schema[key]}).validate({key: value})


@pytest.mark.parametrize('model', ISMS_MODELS, ids=[model.__name__ for model in ISMS_MODELS])
class TestTheOwnPublicId:
    """Every ISMS document's own public_id"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_no_id_is_refused(self, model: Any, value: Any) -> None:
        """A boolean used to pass the integer rule"""
        assert not _validates(model.SCHEMA, PUBLIC_ID, value)

    def test_an_id_is_accepted(self, model: Any) -> None:
        """The control"""
        assert _validates(model.SCHEMA, PUBLIC_ID, AN_ID)

    def test_it_may_be_left_out(self, model: Any) -> None:
        """The server assigns it"""
        assert Validator({PUBLIC_ID: model.SCHEMA[PUBLIC_ID]}).validate({})


@pytest.mark.parametrize('key, nullable', [
    ('control_measure_id', False), ('risk_assessment_id', False), ('responsible_for_implementation_id', True),
])
class TestAssignmentIds:
    """The ControlMeasureAssignment's references"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_no_id_is_refused(self, key: str, nullable: bool, value: Any) -> None:
        """0 / -1 / a boolean"""
        assert not _validates(IsmsControlMeasureAssignment.SCHEMA, key, value)

    def test_null_only_where_the_reference_is_optional(self, key: str, nullable: bool) -> None:
        """The responsible person may be unset"""
        assert _validates(IsmsControlMeasureAssignment.SCHEMA, key, None) is nullable

    def test_an_id_is_accepted(self, key: str, nullable: bool) -> None:
        """The control"""
        assert _validates(IsmsControlMeasureAssignment.SCHEMA, key, AN_ID)


@pytest.mark.parametrize('key', ['threats', 'vulnerabilities', 'protection_goals'])
class TestRiskIdLists:
    """Every item of a Risk's three id lists"""

    @pytest.mark.parametrize('item', [0, -1, True, 'x', {'a': 1}, None], ids=[
        'zero', 'negative', 'true', 'string', 'dict', 'null'])
    def test_an_item_that_is_no_id_is_refused(self, key: str, item: Any) -> None:
        """Each used to be stored"""
        assert not _validates(IsmsRisk.SCHEMA, key, [AN_ID, item])

    def test_ids_are_accepted(self, key: str) -> None:
        """The control, an empty list too"""
        assert _validates(IsmsRisk.SCHEMA, key, [AN_ID, AN_ID + 1])
        assert _validates(IsmsRisk.SCHEMA, key, [])


class TestImpactDescriptionId:
    """An ImpactCategory description's Impact"""

    @pytest.mark.parametrize('value', [*NOT_AN_ID, None], ids=[*NOT_AN_ID_NAMES, 'null'])
    def test_no_id_is_refused(self, value: Any) -> None:
        """``true`` used to be stored"""
        assert not _validates(IsmsImpactCategory.SCHEMA, 'impact_descriptions',
                              [{'impact_id': value, 'value': 'x'}])

    def test_an_id_is_accepted(self) -> None:
        """The control"""
        assert _validates(IsmsImpactCategory.SCHEMA, 'impact_descriptions', [{'impact_id': AN_ID, 'value': 'x'}])


@pytest.mark.parametrize('model, key', [
    (IsmsThreat, 'source'), (IsmsVulnerability, 'source'), (IsmsControlMeasure, 'source'), (IsmsRisk, 'category_id'),
], ids=['threat-source', 'vulnerability-source', 'control-measure-source', 'risk-category'])
class TestOptionFields:
    """The fields holding an option id: null (nothing chosen) or an id from 1"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_no_id_is_refused(self, model: Any, key: str, value: Any) -> None:
        """Each used to be stored"""
        assert not _validates(model.SCHEMA, key, value)

    @pytest.mark.parametrize('value', [None, AN_ID], ids=['null', 'an-id'])
    def test_null_or_an_id_is_accepted(self, model: Any, key: str, value: Any) -> None:
        """The control"""
        assert _validates(model.SCHEMA, key, value)
