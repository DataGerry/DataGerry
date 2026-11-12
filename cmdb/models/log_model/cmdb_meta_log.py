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
Implementation of CmdbMetaLog
"""
from logging import Logger, getLogger
from datetime import datetime
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.log_model.log_action_enum import LogAction
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbMetaLog - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbMetaLog(CmdbDAO):
    """CmdbMetaLog"""
    COLLECTION = 'framework.logs'

    # This collection only grows - one document per object create / edit / delete, each carrying a full
    # rendered snapshot - and it is read on every object's log tab, so the query shapes the REST routes
    # issue must not scan it, and their pages must not sort every matching log in memory:
    #   - `{object_id: X}` in log_time order (the per-object log list): `object_id_log_time_public_id` serves the
    #     match AND the sort, so a busy object's newest logs are read straight off the index
    #   - `{log_type: X, action: Y}` or `{log_type: X, action: {$in: [...]}}` (the delete-log list, and the page
    #     of the exists / notexists split): `log_type_action_log_time_public_id` serves the match by its first two
    #     keys and a log_time page by the rest - one action is one ordered run, several are merged in order
    #     (SORT_MERGE). An `action: {$ne: ...}` condition cannot do that, which is why the split lists the
    #     actions it wants
    # Both end on public_id because every list sort does: the query builder breaks ties on public_id in the
    # sort's own direction, so (log_time, public_id) is the order a page asks for, read forwards or backwards
    # The `object_id_log_time_public_id` index also serves the split's deleted-object read: grouping every log by
    # object_id with no filter is read off its first key (a DISTINCT_SCAN), one index key per object and no log
    # loaded
    # Existing installations pick these up on the next start: the collection validator adds a declared index
    # whose NAME is missing on every pass. It never changes or drops one, so an index that changes its keys gets
    # a new name and an updater drops the old one (`updater_20261114` dropped `object_id_log_time` and
    # `log_type_action`, the predecessors without the trailing keys)
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [
                ('object_id', CmdbDAO.DAO_ASCENDING),
                ('log_time', CmdbDAO.DAO_DESCENDING),
                ('public_id', CmdbDAO.DAO_DESCENDING),
            ],
            'name': 'object_id_log_time_public_id',
            'unique': False,
        },
        {
            'keys': [
                ('log_type', CmdbDAO.DAO_ASCENDING),
                ('action', CmdbDAO.DAO_ASCENDING),
                ('log_time', CmdbDAO.DAO_DESCENDING),
                ('public_id', CmdbDAO.DAO_DESCENDING),
            ],
            'name': 'log_type_action_log_time_public_id',
            'unique': False,
        },
    ]

    def __init__(
        self,
        *,
        public_id: int,
        log_type: str | None,
        log_time: datetime,
        action: LogAction,
        action_name: str,
    ) -> None:
        """
        Initializes a CmdbMetaLog

        Args:
            public_id (int): The unique identifier for the log entry
            log_type (str | None): The type/category of the log
            log_time (datetime): The timestamp of when the log event occurred
            action (LogAction): The action taken (e.g., CREATE, UPDATE, DELETE)
            action_name (str): A descriptive name for the action performed
        """
        self.log_type = log_type
        self.log_time: datetime = log_time
        self.action: LogAction = action
        self.action_name = action_name
        super().__init__(public_id=public_id)
