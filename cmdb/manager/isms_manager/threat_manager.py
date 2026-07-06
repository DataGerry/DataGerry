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
This module contains the implementation of the ThreatManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import delete_isms_item_if_unused_by_risk

from cmdb.models.isms_model import IsmsThreat

from cmdb.errors.manager.threat_manager import THREAT_MANAGER_ERRORS
from cmdb.errors.manager.threat_manager.threat_manager_errors import (
    ThreatManagerDeleteError,
    ThreatManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ThreatManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ThreatManager(GenericManager):
    """
    The ThreatManager manages the interaction between IsmsThreats and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsThreat, THREAT_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes an IsmsThreat from the database with followup logics

        Args:
            public_id (int): public_id of IsmsThreat which should be deleted

        Raises:
            ThreatManagerDeleteError: If the delete operation fails
            ThreatManagerRiskUsageError: If the IsmsThreat is used by an IsmsRisk and can not be deleted

        Returns:
            bool: True if success, else False
        """
        return delete_isms_item_if_unused_by_risk(
            self,
            public_id,
            'threats',
            ThreatManagerRiskUsageError,
            ThreatManagerDeleteError,
            'Threat is used by IsmsRisks!',
        )
