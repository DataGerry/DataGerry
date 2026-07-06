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
Integration tests for ProtectionGoalManager.delete_with_follow_up, run against the bound collections.

The manager (like Threat / Vulnerability, now via the shared delete_isms_item_if_unused_by_risk
helper) refuses to delete an IsmsProtectionGoal that an IsmsRisk still references, and otherwise
deletes it.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.models.isms_model import IsmsProtectionGoal, IsmsRisk
from cmdb.errors.manager.protection_goal_manager import ProtectionGoalManagerRiskUsageError
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTION_GOAL_ID: int = 99501
RISK_ID: int = 99502

ALL_PROTECTION_GOAL_IDS: list[int] = [PROTECTION_GOAL_ID]
ALL_RISK_IDS: list[int] = [RISK_ID]


@pytest.fixture(name='protection_goal_manager')
def fixture_protection_goal_manager(database_manager: MongoDatabaseManager) -> ProtectionGoalManager:
    """Provides a ProtectionGoalManager wired to the test database."""
    return ProtectionGoalManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any protection goals / risks seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_PROTECTION_GOAL_IDS}})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})

    _purge()
    yield
    _purge()


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _exists(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> bool:
    """Returns True if the protection goal exists."""
    return database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
        .find_one({'public_id': public_id}) is not None


class TestProtectionGoalDeleteWithFollowUp:
    """delete_with_follow_up guards against deleting a ProtectionGoal used by a Risk."""

    def test_deletes_when_unused(self, protection_goal_manager: ProtectionGoalManager,
                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ProtectionGoal that no Risk references is deleted and returns True."""
        _insert(database_manager, database_name, IsmsProtectionGoal.COLLECTION,
                {'public_id': PROTECTION_GOAL_ID, 'name': 'G', 'predefined': False})

        result = protection_goal_manager.delete_with_follow_up(PROTECTION_GOAL_ID)

        assert result is True
        assert not _exists(database_manager, database_name, PROTECTION_GOAL_ID)

    def test_raises_when_used_by_risk(self, protection_goal_manager: ProtectionGoalManager,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ProtectionGoal referenced by a Risk raises RiskUsageError and is not deleted."""
        _insert(database_manager, database_name, IsmsProtectionGoal.COLLECTION,
                {'public_id': PROTECTION_GOAL_ID, 'name': 'G', 'predefined': False})
        _insert(database_manager, database_name, IsmsRisk.COLLECTION,
                {'public_id': RISK_ID, 'protection_goals': [PROTECTION_GOAL_ID]})

        with pytest.raises(ProtectionGoalManagerRiskUsageError):
            protection_goal_manager.delete_with_follow_up(PROTECTION_GOAL_ID)

        assert _exists(database_manager, database_name, PROTECTION_GOAL_ID)
