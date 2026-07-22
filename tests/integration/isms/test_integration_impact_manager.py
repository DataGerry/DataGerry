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
Integration tests for the ImpactManager database-backed methods, run against the bound collections.

Covers ``impact_calculation_basis_exists`` (uniqueness lookup), ``is_impact_used`` (cross-collection
reference check into IsmsRiskAssessment), and ``update_with_follow_up`` which updates the Impact and
recomputes the maximum_impact_id / maximum_impact_value of every referencing RiskAssessment.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment
from cmdb.errors.manager.impact_manager import ImpactManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_A: int = 97401
IMPACT_B: int = 97402
RISK_ASSESSMENT_ID: int = 97403

BASIS_A: float = 1.0
BASIS_B: float = 3.0
UPDATED_BASIS_A: float = 5.0

ALL_IMPACT_IDS: list[int] = [IMPACT_A, IMPACT_B]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]


@pytest.fixture(name='impact_manager')
def fixture_impact_manager(database_manager: MongoDatabaseManager) -> ImpactManager:
    """Provides an ImpactManager wired to the test database."""
    return ImpactManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any impacts / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_IMPACT_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _impact_doc(public_id: int, basis: float) -> dict[str, Any]:
    """Builds a minimal IsmsImpact document for direct insertion."""
    return {'public_id': public_id, 'name': f'Impact {public_id}', 'calculation_basis': basis}


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _risk_assessment(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Returns the seeded IsmsRiskAssessment document."""
    return database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .find_one({'public_id': RISK_ASSESSMENT_ID})


class TestImpactCalculationBasisExists:
    """impact_calculation_basis_exists reports whether a basis is already taken."""

    def test_true_when_basis_present(self, impact_manager: ImpactManager,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A basis held by an existing Impact returns True."""
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_A, BASIS_A))

        assert impact_manager.impact_calculation_basis_exists(BASIS_A) is True

    def test_false_when_basis_absent(self, impact_manager: ImpactManager) -> None:
        """An unused basis returns False."""
        assert impact_manager.impact_calculation_basis_exists(BASIS_A) is False

    def test_wraps_unexpected_error(self, impact_manager: ImpactManager, monkeypatch) -> None:
        """An unexpected lookup error is wrapped as ImpactManagerGetError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(ImpactManager, 'get_one_by', _boom)

        with pytest.raises(ImpactManagerGetError):
            impact_manager.impact_calculation_basis_exists(BASIS_A)


class TestIsImpactUsed:
    """is_impact_used reports whether any RiskAssessment references the Impact."""

    def test_true_when_referenced_by_risk_assessment(self, impact_manager: ImpactManager,
                                                     database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """An Impact referenced in a RiskAssessment matrix returns True."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {'impacts': [{'impact_id': IMPACT_A}]},
        })

        assert impact_manager.is_impact_used(IMPACT_A) is True

    def test_false_when_not_referenced(self, impact_manager: ImpactManager) -> None:
        """An Impact no RiskAssessment references returns False."""
        assert impact_manager.is_impact_used(IMPACT_A) is False


class TestUpdateWithFollowUp:
    """update_with_follow_up updates the Impact and recomputes referencing RiskAssessments."""

    def test_recomputes_maximum_impact_in_risk_assessment(self, impact_manager: ImpactManager,
                                                          database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """Raising Impact A's basis above B makes A the new maximum in both matrices."""
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_A, BASIS_A))
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_B, BASIS_B))
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {
                'impacts': [{'impact_id': IMPACT_A}, {'impact_id': IMPACT_B}],
                'maximum_impact_id': IMPACT_B,
                'maximum_impact_value': BASIS_B,
            },
            'risk_calculation_after': {
                'impacts': [{'impact_id': IMPACT_A}, {'impact_id': IMPACT_B}],
                'maximum_impact_id': IMPACT_B,
                'maximum_impact_value': BASIS_B,
            },
        })

        impact_manager.update_with_follow_up(IMPACT_A, _impact_doc(IMPACT_A, UPDATED_BASIS_A))

        stored_impact = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .find_one({'public_id': IMPACT_A})
        assert stored_impact['calculation_basis'] == UPDATED_BASIS_A

        risk_assessment = _risk_assessment(database_manager, database_name)
        assert risk_assessment['risk_calculation_before']['maximum_impact_id'] == IMPACT_A
        assert risk_assessment['risk_calculation_before']['maximum_impact_value'] == UPDATED_BASIS_A
        assert risk_assessment['risk_calculation_after']['maximum_impact_id'] == IMPACT_A
        assert risk_assessment['risk_calculation_after']['maximum_impact_value'] == UPDATED_BASIS_A

    def test_updates_impact_when_no_risk_assessment_references_it(self, impact_manager: ImpactManager,
                                                                 database_manager: MongoDatabaseManager,
                                                                 database_name: str) -> None:
        """With no referencing RiskAssessment the Impact is updated and no bulk write occurs."""
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_A, BASIS_A))

        impact_manager.update_with_follow_up(IMPACT_A, _impact_doc(IMPACT_A, UPDATED_BASIS_A))

        stored_impact = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .find_one({'public_id': IMPACT_A})
        assert stored_impact['calculation_basis'] == UPDATED_BASIS_A
