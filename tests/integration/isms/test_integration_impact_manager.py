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

Covers ``impact_calculation_basis_exists`` (uniqueness lookup) and the unique index behind it,
``is_impact_used`` (cross-collection reference check into IsmsRiskAssessment), and ``update_with_follow_up``
which updates the Impact and recomputes the maximum_impact_id / maximum_impact_value of every referencing
RiskAssessment - recording both writes in a ledger, whose undo puts both back when the propagation fails.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment
from cmdb.utils.error_chain import find_cause
from cmdb.errors.database import DocumentDuplicateKeyError, DocumentInsertError
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.impact_manager import (
    ImpactManagerCalculationBasisError,
    ImpactManagerInsertError,
    ImpactManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_A: int = 97401
IMPACT_B: int = 97402
RISK_ASSESSMENT_ID: int = 97403

BASIS_A: float = 1.0
BASIS_B: float = 3.0
UPDATED_BASIS_A: float = 5.0

ALL_IMPACT_IDS: list[int] = [IMPACT_A, IMPACT_B]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]

# The unique index on the weight is named after its key
BASIS_INDEX_NAME: str = 'calculation_basis'


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

    def test_wraps_a_failed_lookup(self, impact_manager: ImpactManager, monkeypatch) -> None:
        """The lookup's BaseManagerGetError is wrapped as ImpactManagerCalculationBasisError."""
        def _down(*_args, **_kwargs):
            raise BaseManagerGetError('db down')

        monkeypatch.setattr(ImpactManager, 'get_one_by', _down)

        with pytest.raises(ImpactManagerCalculationBasisError):
            impact_manager.impact_calculation_basis_exists(BASIS_A)

    def test_a_bug_propagates_as_itself(self, impact_manager: ImpactManager, monkeypatch) -> None:
        """A programming error under the lookup is not wrapped."""
        def _bug(*_args, **_kwargs):
            raise RuntimeError('bug')

        monkeypatch.setattr(ImpactManager, 'get_one_by', _bug)

        with pytest.raises(RuntimeError):
            impact_manager.impact_calculation_basis_exists(BASIS_A)


class TestUniqueCalculationBasis:
    """The declared unique index is what holds the rule when two writes race the pre-check."""

    def test_a_second_impact_of_one_basis_is_refused_as_a_duplicate(
            self, impact_manager: ImpactManager, database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """Built here (the test session builds no indexes); the second insert carries the duplicate-key cause."""
        database_manager.create_indexes(IsmsImpact.COLLECTION, database_name, IsmsImpact.get_index_keys())

        try:
            _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_A, BASIS_A))

            with pytest.raises(ImpactManagerInsertError) as excinfo:
                impact_manager.insert_item(_impact_doc(IMPACT_B, BASIS_A))

            assert find_cause(excinfo.value, DocumentDuplicateKeyError) is not None
        finally:
            # Left in place it would refuse a later test's scale that reuses a basis on purpose
            database_manager.drop_index(IsmsImpact.COLLECTION, database_name, BASIS_INDEX_NAME)


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

        answered = impact_manager.update_with_follow_up(IMPACT_A, _impact_doc(IMPACT_A, UPDATED_BASIS_A),
                                                        WriteLedger())

        stored_impact = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .find_one({'public_id': IMPACT_A}, {'_id': 0})
        assert stored_impact['calculation_basis'] == UPDATED_BASIS_A
        # What the manager answers is the document it stored - the update route hands it to the client
        assert answered == stored_impact

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

        ledger = WriteLedger()

        impact_manager.update_with_follow_up(IMPACT_A, _impact_doc(IMPACT_A, UPDATED_BASIS_A), ledger)

        stored_impact = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .find_one({'public_id': IMPACT_A})
        assert stored_impact['calculation_basis'] == UPDATED_BASIS_A
        # Only the Impact's own update is in the ledger
        assert len(ledger.entries) == 1

    def test_a_failed_propagation_is_undone_with_the_impact(
            self, impact_manager: ImpactManager, database_manager: MongoDatabaseManager,
            database_name: str, monkeypatch) -> None:
        """
        The bulk write fails: the manager raises its UpdateError, and undoing the ledger puts the Impact's basis
        back and leaves the RiskAssessment's maximum as it was
        """
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_A, BASIS_A))
        _insert(database_manager, database_name, IsmsImpact.COLLECTION, _impact_doc(IMPACT_B, BASIS_B))
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {
                'impacts': [{'impact_id': IMPACT_A}, {'impact_id': IMPACT_B}],
                'maximum_impact_id': IMPACT_B,
                'maximum_impact_value': BASIS_B,
            },
        })
        real_bulk_write = database_manager.bulk_write
        failing: dict[str, bool] = {'on': True}

        def _bulk_write(collection: str, *args: Any) -> int:
            if failing['on'] and collection == IsmsRiskAssessment.COLLECTION:
                raise DocumentInsertError('bulk write failed')

            return real_bulk_write(collection, *args)

        monkeypatch.setattr(database_manager, 'bulk_write', _bulk_write)
        ledger = WriteLedger()

        with pytest.raises(ImpactManagerUpdateError):
            impact_manager.update_with_follow_up(IMPACT_A, _impact_doc(IMPACT_A, UPDATED_BASIS_A), ledger)

        failing['on'] = False

        assert not ledger.undo()
        stored_impact = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .find_one({'public_id': IMPACT_A})
        assert stored_impact['calculation_basis'] == BASIS_A
        before = _risk_assessment(database_manager, database_name)['risk_calculation_before']
        assert (before['maximum_impact_id'], before['maximum_impact_value']) == (IMPACT_B, BASIS_B)
