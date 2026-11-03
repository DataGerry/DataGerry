# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of the ProtectionGoalManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import PROTECTION_GOAL_IN_USE_MESSAGE
from cmdb.manager.isms_manager.isms_manager_helper import delete_isms_item_if_unused_by_risk

from cmdb.models.isms_model import IsmsProtectionGoal
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.protection_goal_manager import PROTECTION_GOAL_MANAGER_ERRORS
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerNameCheckError,
    ProtectionGoalManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
#                                             ProtectionGoalManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ProtectionGoalManager(GenericManager):
    """
    The ProtectionGoalManager manages the interaction between IsmsProtectionGoals and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ProtectionGoalManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsProtectionGoal, PROTECTION_GOAL_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def find_name_holder(self, name: str) -> int | None:
        """
        Answers which IsmsProtectionGoal holds a name

        The readable half of the uniqueness rule: the unique index on ``name`` is what holds under concurrency. The
        name is compared exactly as sent - what the index compares - so another spelling never blocks a write

        Args:
            name (str): The name a write would store

        Raises:
            ProtectionGoalManagerNameCheckError: If the read failed (a BaseManagerGetError)

        Returns:
            int | None: The public_id of the IsmsProtectionGoal holding the name, or None when none does
        """
        try:
            holder: dict[str, Any] | None = self.get_one_by({ProtectionGoalKey.NAME.value: name})
        except BaseManagerGetError as err:
            LOGGER.error("[find_name_holder] %s: %s", type(err).__name__, err)
            raise ProtectionGoalManagerNameCheckError(err) from err

        return None if holder is None else holder.get(ProtectionGoalKey.PUBLIC_ID.value)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes an IsmsProtectionGoal from the database with followup logics

        Args:
            public_id (int): public_id of IsmsProtectionGoal which should be deleted

        Raises:
            ProtectionGoalManagerDeleteError: If the usage check, the delete or the restore of an item that
                gained a reference meanwhile fails
            ProtectionGoalManagerRiskUsageError: If the IsmsProtectionGoal is used by an IsmsRisk and cannot be deleted

        Returns:
            bool: True if success, else False
        """
        return delete_isms_item_if_unused_by_risk(
            self,
            public_id,
            RiskKey.PROTECTION_GOALS,
            ProtectionGoalManagerRiskUsageError,
            PROTECTION_GOAL_IN_USE_MESSAGE,
        )
