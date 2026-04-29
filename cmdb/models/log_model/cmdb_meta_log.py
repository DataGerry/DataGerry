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
    MODEL = 'CmdbLog'

    #pylint: disable=too-many-positional-arguments
    def __init__(self, public_id: int, log_type, log_time: datetime, action: LogAction, action_name: str):
        """
        Initializes a CmdbMetaLog

        Args:
            public_id (int): The unique identifier for the log entry
            log_type (str): The type/category of the log
            log_time (datetime): The timestamp of when the log event occurred
            action (LogAction): The action taken (e.g., CREATE, UPDATE, DELETE)
            action_name (str): A descriptive name for the action performed
        """
        self.log_type = log_type
        self.log_time: datetime = log_time
        self.action: LogAction = action
        self.action_name = action_name
        super().__init__(public_id=public_id)
