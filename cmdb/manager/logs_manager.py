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
This module contains the implementation of the LogsManager
"""
from logging import Logger, getLogger
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

from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


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
        Initializes the LogsManager on the logs collection (CmdbMetaLog.COLLECTION)

        Args:
            dbm (MongoDatabaseManager): Active database manager instance used for all queries
            database (str, optional): Target database name. Required in cloud mode to select the
                                      tenant database; defaults to the manager's configured database
        """
        super().__init__(CmdbMetaLog.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_log(self, action: LogAction, log_type: str, **kwargs) -> int:
        """
        Creates a new log entry in the database

        Assembles the static log fields (a freshly incremented public_id, the action value and
        name, the log type and a UTC timestamp), merges in the caller-supplied log payload, builds
        a CmdbLog from it and persists its serialized form.

        Args:
            action (LogAction): The action the log records (e.g. CREATE, EDIT, DELETE)
            log_type (str): The log type discriminator (e.g. ``CmdbObjectLog.__name__``)
            **kwargs: The remaining log-specific fields merged into the document, e.g. ``object_id``,
                      ``user_id``, ``user_name``, ``version``, ``changes``, ``comment``,
                      ``render_state``. Keys here override the static fields on collision.

        Returns:
            int: The public_id of the newly inserted log
        """
        log_init = {}

        # set static values
        log_init['public_id'] = self.get_next_public_id(inc_id=True)
        log_init['action'] = action.value
        log_init['action_name'] = action.name
        log_init['log_type'] = log_type
        log_init['log_time'] = datetime.now(timezone.utc)
        log_data = {**log_init, **kwargs}

        new_log = CmdbLog(**log_data)
        ack = self.insert(CmdbObjectLog.to_json(new_log))

        return ack

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser = None,
                permission: AccessControlPermission = None) -> IterationResult[CmdbObjectLog]:
        """
        Runs an aggregation over the logs collection and binds the rows to CmdbObjectLog

        Args:
            builder_params (BuilderParameters): Match filter / aggregation pipeline plus pagination
            user (CmdbUser, optional): User requesting this action, used for ACL-aware querying
            permission (AccessControlPermission, optional): Permission checked for the user when set

        Raises:
            BaseManagerIterationError: If the aggregation or the IterationResult assembly fails

        Returns:
            IterationResult[CmdbObjectLog]: The matching logs and their total count
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbObjectLog] = IterationResult(aggregation_result, total)
            iteration_result.convert_to(CmdbObjectLog)

            return iteration_result
        except Exception as err:
            raise BaseManagerIterationError(err) from err
