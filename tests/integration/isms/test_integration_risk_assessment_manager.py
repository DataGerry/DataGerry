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
Integration tests for RiskAssessmentManager.delete_with_follow_up, run against the bound collections.

Deleting an IsmsRiskAssessment cascades: every IsmsControlMeasureAssignment linked to it (via
risk_assessment_id) is removed before the assessment itself is deleted.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment, IsmsImpact, IsmsLikelihood
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

RISK_ASSESSMENT_ID: int = 99101
CONTROL_ASSIGNMENT_ID_A: int = 99102
CONTROL_ASSIGNMENT_ID_B: int = 99103
IMPACT_LOW_ID: int = 99110
IMPACT_HIGH_ID: int = 99111
LIKELIHOOD_ID: int = 99112

BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
LIKELIHOOD_BASIS: float = 2.0

ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CONTROL_ASSIGNMENT_ID_A, CONTROL_ASSIGNMENT_ID_B]
ALL_IMPACT_IDS: list[int] = [IMPACT_LOW_ID, IMPACT_HIGH_ID]
ALL_LIKELIHOOD_IDS: list[int] = [LIKELIHOOD_ID]


@pytest.fixture(name='risk_assessment_manager')
def fixture_risk_assessment_manager(database_manager: MongoDatabaseManager) -> RiskAssessmentManager:
    """Provides a RiskAssessmentManager wired to the test database."""
    return RiskAssessmentManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any assessments / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_IMPACT_IDS}})
        database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_LIKELIHOOD_IDS}})

    _purge()
    yield
    _purge()


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _exists(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, public_id: int) -> bool:
    """Returns True if a document with the public_id exists in the collection."""
    return database_manager.get_collection(collection, database_name)\
        .find_one({'public_id': public_id}) is not None


class TestRiskAssessmentDeleteWithFollowUp:
    """delete_with_follow_up removes the assessment and its linked ControlMeasureAssignments."""

    def test_cascades_to_control_measure_assignments(self, risk_assessment_manager: RiskAssessmentManager,
                                                     database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """Both assignments linked to the assessment are removed together with the assessment."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {'public_id': RISK_ASSESSMENT_ID})
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID_A, 'risk_assessment_id': RISK_ASSESSMENT_ID})
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID_B, 'risk_assessment_id': RISK_ASSESSMENT_ID})

        result = risk_assessment_manager.delete_with_follow_up(RISK_ASSESSMENT_ID)

        assert result is True
        assert not _exists(database_manager, database_name, IsmsRiskAssessment.COLLECTION, RISK_ASSESSMENT_ID)
        assert not _exists(
            database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CONTROL_ASSIGNMENT_ID_A
        )
        assert not _exists(
            database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CONTROL_ASSIGNMENT_ID_B
        )

    def test_wraps_unexpected_error_as_delete_error(self, risk_assessment_manager: RiskAssessmentManager,
                                                    monkeypatch) -> None:
        """An unexpected error during the follow-up is wrapped as RiskAssessmentManagerDeleteError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(RiskAssessmentManager, 'delete_many_from_other_collection', _boom)

        with pytest.raises(RiskAssessmentManagerDeleteError):
            risk_assessment_manager.delete_with_follow_up(RISK_ASSESSMENT_ID)

    def test_deletes_assessment_without_assignments(self, risk_assessment_manager: RiskAssessmentManager,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """An assessment with no linked assignments is deleted without error."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {'public_id': RISK_ASSESSMENT_ID})

        result = risk_assessment_manager.delete_with_follow_up(RISK_ASSESSMENT_ID)

        assert result is True
        assert not _exists(database_manager, database_name, IsmsRiskAssessment.COLLECTION, RISK_ASSESSMENT_ID)


class TestRecalculateRiskValues:
    """recalculate_risk_values derives maximum_impact + likelihood_value from the scale collections."""

    def test_overwrites_client_values_from_scales(self, risk_assessment_manager: RiskAssessmentManager,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """The before matrix is recomputed from impacts + likelihood; the empty after matrix nulls out."""
        _insert(database_manager, database_name, IsmsImpact.COLLECTION,
                {'public_id': IMPACT_LOW_ID, 'calculation_basis': BASIS_LOW})
        _insert(database_manager, database_name, IsmsImpact.COLLECTION,
                {'public_id': IMPACT_HIGH_ID, 'calculation_basis': BASIS_HIGH})
        _insert(database_manager, database_name, IsmsLikelihood.COLLECTION,
                {'public_id': LIKELIHOOD_ID, 'calculation_basis': LIKELIHOOD_BASIS})

        data: dict[str, Any] = {
            'risk_calculation_before': {
                'impacts': [
                    {'impact_category_id': 1, 'impact_id': IMPACT_LOW_ID},
                    {'impact_category_id': 2, 'impact_id': IMPACT_HIGH_ID},
                ],
                'likelihood_id': LIKELIHOOD_ID,
                'maximum_impact_id': 0, 'maximum_impact_value': 0.0, 'likelihood_value': 0.0,
            },
            'risk_calculation_after': {
                'impacts': [], 'likelihood_id': None,
                'maximum_impact_id': 42, 'maximum_impact_value': 9.9, 'likelihood_value': 9.9,
            },
        }

        risk_assessment_manager.recalculate_risk_values(data)

        before = data['risk_calculation_before']
        assert before['maximum_impact_id'] == IMPACT_HIGH_ID
        assert before['maximum_impact_value'] == BASIS_HIGH
        assert before['likelihood_value'] == LIKELIHOOD_BASIS

        after = data['risk_calculation_after']
        assert after['maximum_impact_id'] is None
        assert after['maximum_impact_value'] is None
        assert after['likelihood_value'] is None
