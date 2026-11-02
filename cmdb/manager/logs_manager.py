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
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_log import CmdbLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
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

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initializes the LogsManager on the logs collection (CmdbMetaLog.COLLECTION)

        Args:
            dbm (MongoDatabaseManager): Active database manager instance used for all queries
            database (str | None): Target database name. Required in cloud mode to select the
                                      tenant database; defaults to the manager's configured database
        """
        super().__init__(CmdbMetaLog.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_log(self, action: LogAction, log_type: str, **kwargs: Any) -> int:
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

        Raises:
            BaseManagerGetError: If the next public_id could not be read
            BaseManagerInsertError: If the log could not be written
            CmdbObjectLogToJsonError: If the assembled log cannot be serialised

        Returns:
            int: The public_id of the newly inserted log
        """
        document: dict[str, Any] = self._log_document(self.get_next_public_id(inc_id=True), action, log_type, kwargs)

        # The id was reserved from this collection's counter just above - nothing to raise after the insert
        return self.insert(document, id_from_counter=True)


    def insert_logs(self, action: LogAction, log_type: str, entries: list[dict[str, Any]]) -> list[int]:
        """
        Creates one log entry per payload, with one id reservation and one insert for all of them

        Each entry is assembled as ``insert_log`` assembles one; the ids are reserved as one block, in the order
        of ``entries``. All or nothing as far as this call can tell: an entry that cannot be assembled fails the
        call before anything is written

        Args:
            action (LogAction): The action every entry records
            log_type (str): The log type discriminator of every entry
            entries (list[dict[str, Any]]): The log-specific fields of each entry (see ``insert_log``)

        Raises:
            BaseManagerGetError: If the ids could not be reserved
            BaseManagerInsertError: If the entries could not be written
            CmdbObjectLogToJsonError: If an assembled entry cannot be serialised

        Returns:
            list[int]: The public_ids of the new entries, in the order of ``entries``; empty for no entries
        """
        if not entries:
            return []

        public_ids: list[int] = self.reserve_public_ids(len(entries))
        documents: list[dict[str, Any]] = [
            self._log_document(public_id, action, log_type, entry)
            for public_id, entry in zip(public_ids, entries, strict=True)
        ]

        return self.insert_many(documents, skip_public=True)


    @staticmethod
    def _log_document(public_id: int, action: LogAction, log_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Assembles the stored document of one log entry

        The static fields - the public_id, the action value and name, the log type and a UTC timestamp - merged
        with the caller's payload, whose keys win on a collision, then built as a CmdbLog and serialised

        Args:
            public_id (int): The entry's reserved public_id
            action (LogAction): The action the entry records
            log_type (str): The log type discriminator
            payload (dict[str, Any]): The log-specific fields (see ``insert_log``)

        Raises:
            CmdbObjectLogToJsonError: If the assembled entry cannot be serialised

        Returns:
            dict[str, Any]: The document to store
        """
        static_fields: dict[str, Any] = {
            'public_id': public_id,
            'action': action.value,
            'action_name': action.name,
            'log_type': log_type,
            'log_time': datetime.now(timezone.utc),
        }

        return CmdbObjectLog.to_json(CmdbLog(**{**static_fields, **payload}))

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object_log(self, public_id: int) -> dict[str, Any] | None:
        """
        Reads one CmdbObjectLog by its public_id

        The collection is shared by ``log_type``, and only object logs are served by the log routes - so a document
        of another kind with the same public_id reads as absent, exactly as every list filters it out

        Args:
            public_id (int): public_id of the log

        Raises:
            BaseManagerGetError: If the read fails

        Returns:
            dict[str, Any] | None: The stored object log (without ``_id``), or None when no object log has the id
        """
        return self.get_one_by({'public_id': public_id, 'log_type': OBJECT_LOG_TYPE})


    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser | None = None,
                permission: AccessControlPermission | None = None) -> IterationResult[CmdbObjectLog]:
        """
        Runs an aggregation over the logs collection and binds the rows to CmdbObjectLog

        Args:
            builder_params (BuilderParameters): Match filter / aggregation pipeline plus pagination
            user (CmdbUser | None): User requesting this action, used for ACL-aware querying
            permission (AccessControlPermission | None): Permission checked for the user when set

        Raises:
            BaseManagerIterationError: If the aggregation fails, or a stored log does not fit CmdbObjectLog
                (its INIT_FROM_DATA_ERROR); a programming error propagates unwrapped

        Returns:
            IterationResult[CmdbObjectLog]: The matching logs and their total count
        """
        aggregation_result, total = self.iterate_query(builder_params, user, permission)

        iteration_result: IterationResult[CmdbObjectLog] = IterationResult(aggregation_result, total)

        try:
            iteration_result.convert_to(CmdbObjectLog)
        except CmdbObjectLog.INIT_FROM_DATA_ERROR as err:
            LOGGER.error("[iterate] Unreadable stored log: %s", err)
            raise BaseManagerIterationError(err) from err

        return iteration_result
