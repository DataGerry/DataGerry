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
Integration tests for the LikelihoodManager database-backed methods, run against the bound
collections.

Covers ``likelihood_calculation_basis_exists`` (uniqueness lookup), ``is_likelihood_used``
(cross-collection reference check into IsmsRiskAssessment), and ``update_with_follow_up`` which
updates the Likelihood and rewrites the likelihood_value of every referencing RiskAssessment via a
single aggregation-pipeline update (only the matrices whose likelihood_id matches are changed).
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.models.isms_model import IsmsLikelihood, IsmsRiskAssessment
from cmdb.errors.manager.likelihood_manager import LikelihoodManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LIKELIHOOD_ID: int = 97601
OTHER_LIKELIHOOD_ID: int = 97602
RISK_ASSESSMENT_ID: int = 97603

OLD_BASIS: float = 1.0
NEW_BASIS: float = 4.0
OTHER_BASIS: float = 2.0

ALL_LIKELIHOOD_IDS: list[int] = [LIKELIHOOD_ID, OTHER_LIKELIHOOD_ID]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]


@pytest.fixture(name='likelihood_manager')
def fixture_likelihood_manager(database_manager: MongoDatabaseManager) -> LikelihoodManager:
    """Provides a LikelihoodManager wired to the test database."""
    return LikelihoodManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any likelihoods / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_LIKELIHOOD_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _likelihood_doc(public_id: int, basis: float) -> dict[str, Any]:
    """Builds a minimal IsmsLikelihood document for direct insertion."""
    return {'public_id': public_id, 'name': f'Likelihood {public_id}', 'calculation_basis': basis}


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _risk_assessment(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Returns the seeded IsmsRiskAssessment document."""
    return database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .find_one({'public_id': RISK_ASSESSMENT_ID})


class TestLikelihoodCalculationBasisExists:
    """likelihood_calculation_basis_exists reports whether a basis is already taken."""

    def test_true_when_basis_present(self, likelihood_manager: LikelihoodManager,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A basis held by an existing Likelihood returns True."""
        _insert(database_manager, database_name, IsmsLikelihood.COLLECTION, _likelihood_doc(LIKELIHOOD_ID, OLD_BASIS))

        assert likelihood_manager.likelihood_calculation_basis_exists(OLD_BASIS) is True

    def test_false_when_basis_absent(self, likelihood_manager: LikelihoodManager) -> None:
        """An unused basis returns False."""
        assert likelihood_manager.likelihood_calculation_basis_exists(OLD_BASIS) is False

    def test_wraps_unexpected_error(self, likelihood_manager: LikelihoodManager, monkeypatch) -> None:
        """An unexpected lookup error is wrapped as LikelihoodManagerGetError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(LikelihoodManager, 'get_one_by', _boom)

        with pytest.raises(LikelihoodManagerGetError):
            likelihood_manager.likelihood_calculation_basis_exists(OLD_BASIS)


class TestIsLikelihoodUsed:
    """is_likelihood_used reports whether any RiskAssessment references the Likelihood."""

    def test_true_when_referenced(self, likelihood_manager: LikelihoodManager,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A Likelihood referenced in a RiskAssessment matrix returns True."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {'likelihood_id': LIKELIHOOD_ID, 'likelihood_value': OLD_BASIS},
        })

        assert likelihood_manager.is_likelihood_used(LIKELIHOOD_ID) is True

    def test_false_when_not_referenced(self, likelihood_manager: LikelihoodManager) -> None:
        """A Likelihood no RiskAssessment references returns False."""
        assert likelihood_manager.is_likelihood_used(LIKELIHOOD_ID) is False


class TestUpdateWithFollowUp:
    """update_with_follow_up updates the Likelihood and rewrites referencing RiskAssessments."""

    def test_rewrites_matching_likelihood_value(self, likelihood_manager: LikelihoodManager,
                                               database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Only the matrices whose likelihood_id matches get the new value; others are untouched."""
        _insert(database_manager, database_name, IsmsLikelihood.COLLECTION, _likelihood_doc(LIKELIHOOD_ID, OLD_BASIS))
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {'likelihood_id': LIKELIHOOD_ID, 'likelihood_value': OLD_BASIS},
            'risk_calculation_after': {'likelihood_id': OTHER_LIKELIHOOD_ID, 'likelihood_value': OTHER_BASIS},
        })

        likelihood_manager.update_with_follow_up(LIKELIHOOD_ID, _likelihood_doc(LIKELIHOOD_ID, NEW_BASIS))

        stored = database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)\
            .find_one({'public_id': LIKELIHOOD_ID})
        assert stored['calculation_basis'] == NEW_BASIS

        risk_assessment = _risk_assessment(database_manager, database_name)
        # before matrix referenced the updated likelihood -> value rewritten
        assert risk_assessment['risk_calculation_before']['likelihood_value'] == NEW_BASIS
        # after matrix referenced a different likelihood -> value preserved
        assert risk_assessment['risk_calculation_after']['likelihood_value'] == OTHER_BASIS
