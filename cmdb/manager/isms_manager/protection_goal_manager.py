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
import logging

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsProtectionGoal, IsmsRisk

from cmdb.errors.manager.protection_goal_manager import PROTECTION_GOAL_MANAGER_ERRORS
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerDeleteError,
    ProtectionGoalManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             ProtectionGoalManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ProtectionGoalManager(GenericManager):
    """
    The ProtectionGoalManager manages the interaction between IsmsProtectionGoals and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsProtectionGoal, PROTECTION_GOAL_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes an IsmsProtectionGoal from the database with followup logics

        Args:
            public_id (int): public_id of IsmsProtectionGoal which should be deleted

        Raises:
            ProtectionGoalManagerDeleteError: If the delete operation fails
            ProtectionGoalManagerRiskUsageError: If the IsmsProtectionGoal is used by an IsmsRisk and cannot be deleted

        Returns:
            bool: True if success, else False
        """
        try:
            # Only deletable if no Risk is using this IsmsProtectionGoal
            risk_using_protection_goal = self.get_one_by(
                {'protection_goals': public_id},
                IsmsRisk.COLLECTION,
            )

            if risk_using_protection_goal:
                raise ProtectionGoalManagerRiskUsageError('ProtectionGoal is used by IsmsRisks!')

            return self.delete_item(public_id)
        except ProtectionGoalManagerRiskUsageError as err:
            raise err
        except Exception as err:
            raise ProtectionGoalManagerDeleteError(str(err)) from err
