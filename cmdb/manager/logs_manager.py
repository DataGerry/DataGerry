# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module contains the implementation of the LogsManager
"""
import logging
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_log import CmdbLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import BaseManagerIterationError, BaseManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  LogsManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class LogsManager(BaseManager):
    """
    The LogsManager handles the interaction between the Logs-API and the Database
    Extends: BaseManager
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection and the queue for sending events

        Args:
            database_manager (MongoDatabaseManager): Active database managers instance
        """
        super().__init__(CmdbMetaLog.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_log(self, action: LogAction, log_type: str, **kwargs) -> int:
        """
        Creates a new log in the database

        Args:
            action (LogAction): The action of the log
            log_type (str): The log type

        Returns:
            int: New public_id
        """
        log_init = {}

        # set static values
        log_init['public_id'] = self.get_next_public_id(inc_id=True)
        log_init['action'] = action.value
        log_init['action_name'] = action.name
        log_init['log_type'] = log_type
        log_init['log_time'] = datetime.now(timezone.utc)
        log_data = {**log_init, **kwargs}

        try:
            new_log = CmdbLog(**log_data)
            ack = self.insert(CmdbObjectLog.to_json(new_log))
        except BaseManagerInsertError as err:
            raise BaseManagerInsertError(err) from err

        return ack

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser = None,
                permission: AccessControlPermission = None) -> IterationResult[CmdbMetaLog]:
        """
        Performs an aggregation on the database
        Args:
            builder_params (BuilderParameters): Contains input to identify the target of action
            user (CmdbUser, optional): User requesting this action
            permission (AccessControlPermission, optional): Permission which should be checked for the user
        Raises:
            BaseManagerIterationError: Raised when something goes wrong during the aggregate part
            BaseManagerIterationError: Raised when something goes wrong during the building of the IterationResult
        Returns:
            IterationResult[CmdbMetaLog]: Result which matches the Builderparameters
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbMetaLog] = IterationResult(aggregation_result, total)
            iteration_result.convert_to(CmdbObjectLog)

            return iteration_result
        except Exception as err:
            raise BaseManagerIterationError(err) from err
