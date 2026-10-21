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
Integration tests for RiskManager.delete_with_follow_up, run against the bound collections.

Deleting an IsmsRisk cascades: every IsmsRiskAssessment referencing it (via risk_id) is removed, and
every IsmsControlMeasureAssignment referencing those assessments (via risk_assessment_id) is removed
too, before the Risk itself is deleted.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment, IsmsControlMeasureAssignment
# -------------------------------------------------------------------------------------------------------------------- #

RISK_ID: int = 98001
RISK_ASSESSMENT_ID: int = 98002
CONTROL_ASSIGNMENT_ID: int = 98003

# second risk + cascade for the bulk delete
RISK_ID_2: int = 98011
RISK_ASSESSMENT_ID_2: int = 98012
CONTROL_ASSIGNMENT_ID_2: int = 98013
MISSING_RISK_ID: int = 98099

ALL_RISK_IDS: list[int] = [RISK_ID, RISK_ID_2]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID, RISK_ASSESSMENT_ID_2]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CONTROL_ASSIGNMENT_ID, CONTROL_ASSIGNMENT_ID_2]


@pytest.fixture(name='risk_manager')
def fixture_risk_manager(database_manager: MongoDatabaseManager) -> RiskManager:
    """Provides a RiskManager wired to the test database."""
    return RiskManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any risks / assessments / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})

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


class TestRiskDeleteWithFollowUp:
    """RiskManager.delete_with_follow_up removes the Risk and its dependent ISMS records."""

    def test_cascades_to_assessments_and_assignments(self, risk_manager: RiskManager,
                                                     database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """Deleting the Risk also deletes its RiskAssessments and their ControlMeasureAssignments."""
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID, 'name': 'R'})
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION,
                {'public_id': RISK_ASSESSMENT_ID, 'risk_id': RISK_ID})
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID, 'risk_assessment_id': RISK_ASSESSMENT_ID})

        result = risk_manager.delete_with_follow_up(RISK_ID)

        assert result is True
        assert not _exists(database_manager, database_name, IsmsRisk.COLLECTION, RISK_ID)
        assert not _exists(database_manager, database_name, IsmsRiskAssessment.COLLECTION, RISK_ASSESSMENT_ID)
        assert not _exists(
            database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CONTROL_ASSIGNMENT_ID
        )

    def test_deletes_risk_without_assessments(self, risk_manager: RiskManager,
                                             database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """A Risk with no referencing assessments is deleted without error."""
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID, 'name': 'R'})

        result = risk_manager.delete_with_follow_up(RISK_ID)

        assert result is True
        assert not _exists(database_manager, database_name, IsmsRisk.COLLECTION, RISK_ID)


class TestRiskDeleteManyWithFollowUp:
    """RiskManager.delete_many_with_follow_up batches the Risk -> RA -> CMA cascade over several Risks."""

    def test_cascades_all_and_returns_counts(self, risk_manager: RiskManager,
                                            database_manager: MongoDatabaseManager,
                                            database_name: str) -> None:
        """Both Risks + their RiskAssessments + ControlMeasureAssignments are removed; counts returned."""
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID, 'name': 'R'})
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID_2, 'name': 'R2'})
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION,
                {'public_id': RISK_ASSESSMENT_ID, 'risk_id': RISK_ID})
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION,
                {'public_id': RISK_ASSESSMENT_ID_2, 'risk_id': RISK_ID_2})
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID, 'risk_assessment_id': RISK_ASSESSMENT_ID})
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID_2, 'risk_assessment_id': RISK_ASSESSMENT_ID_2})

        # a non-existent id in the batch is silently ignored
        deleted_ids, deleted_ras, deleted_cmas = risk_manager.delete_many_with_follow_up(
            [RISK_ID, RISK_ID_2, MISSING_RISK_ID]
        )

        assert set(deleted_ids) == {RISK_ID, RISK_ID_2}
        assert deleted_ras == 2
        assert deleted_cmas == 2
        assert not _exists(database_manager, database_name, IsmsRisk.COLLECTION, RISK_ID_2)
        assert not _exists(database_manager, database_name, IsmsRiskAssessment.COLLECTION, RISK_ASSESSMENT_ID_2)
        assert not _exists(
            database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION, CONTROL_ASSIGNMENT_ID_2
        )

    def test_deletes_risks_without_assessments_zero_cascade(self, risk_manager: RiskManager,
                                                           database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """Risks with no RiskAssessments are deleted with zero RA / CMA cascade counts."""
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID, 'name': 'R'})
        _insert(database_manager, database_name, IsmsRisk.COLLECTION, {'public_id': RISK_ID_2, 'name': 'R2'})

        deleted_ids, deleted_ras, deleted_cmas = risk_manager.delete_many_with_follow_up([RISK_ID, RISK_ID_2])

        assert set(deleted_ids) == {RISK_ID, RISK_ID_2}
        assert (deleted_ras, deleted_cmas) == (0, 0)
        assert not _exists(database_manager, database_name, IsmsRisk.COLLECTION, RISK_ID)
        assert not _exists(database_manager, database_name, IsmsRisk.COLLECTION, RISK_ID_2)

    def test_empty_input_returns_zeros(self, risk_manager: RiskManager) -> None:
        """An empty id list is a no-op returning empty ids and zero counts."""
        assert risk_manager.delete_many_with_follow_up([]) == ([], 0, 0)

    def test_non_existent_ids_are_ignored(self, risk_manager: RiskManager) -> None:
        """A batch of only non-existent ids deletes nothing and returns empty ids / zero counts."""
        assert risk_manager.delete_many_with_follow_up([MISSING_RISK_ID]) == ([], 0, 0)
