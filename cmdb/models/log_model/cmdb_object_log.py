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
Implementation of CmdbObjectLog
"""
from logging import Logger, getLogger
from datetime import datetime

from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbObjectLog - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectLog(CmdbMetaLog):
    """TODO:document"""

    DEFAULT_VERSION: str = '1.0.0'
    SCHEMA: dict = {
        'object_id': {
            'type': 'integer'
        },
        'public_id': {
            'type': 'integer'
        },
        'version': {
            'type': 'integer',
            'default': DEFAULT_VERSION
        },
        'user_id': {
            'type': 'integer'
        },
        'user_name': {
            'type': 'string',
            'required': True,
            'regex': r'(\w+)-*(\w)([\w-]*)'  # kebab case validation
        },
        'render_state': {
            'type': 'string'
        },
        'log_type': {
            'type': 'string',
            'required': True,
        },
        'log_time': {
            'type': 'datetime',
            'required': True,
        },
        'changes': {
            'type': 'list',
            'empty': True,
            'default': []
        },
        'comment': {
            'type': 'string'
        },
        'action': {
            'type': 'integer',
            'required': True,
        },
        'action_name': {
            'type': 'string',
            'required': True
        }
    }

    UNKNOWN_USER_STRING = 'Unknown'

    #pylint: disable=R0913, R0917
    def __init__(self,
                 public_id: int,
                 log_type, log_time: datetime,
                 action: LogAction,
                 action_name: str,
                 object_id: int,
                 version,
                 user_id: int,
                 user_name: str = None,
                 changes: list = None,
                 comment: str = None,
                 render_state = None):
        """
        Initializes a new instance of the CmdbObjectLog class,
        representing a log entry for changes made to a CMDB object.

        Args:
            public_id (int): Unique identifier for the log entry
            log_type: Type or category of the log (custom type expected)
            log_time (datetime): Timestamp when the log entry was created
            action (LogAction): Enum representing the type of action performed (e.g., create, update, delete)
            action_name (str): Human-readable name of the action
            object_id (int): ID of the CMDB object the log entry is associated with
            version: Version identifier of the object (exact type depends on implementation)
            user_id (int): ID of the user who performed the action
            user_name (str | None): Name of the user who performed the action. Defaults to an "unknown"
                                       string if not provided
            changes (list | None): List detailing the specific changes made to the object
            comment (str | None): Additional comments or notes regarding the log entry
            render_state (Any | None): Optional rendering state or snapshot of the object at the time of the log
        """
        self.object_id = object_id
        self.version = version
        self.user_id = user_id
        self.user_name = user_name or self.UNKNOWN_USER_STRING
        self.comment = comment
        self.changes = changes or []
        self.render_state = render_state

        super().__init__(
            public_id=public_id,
            log_type=log_type,
            log_time=log_time,
            action=action,
            action_name=action_name
        )


    @classmethod
    def from_data(cls, data: dict) -> "CmdbObjectLog":
        """Create a instance of CmdbType from database values"""
        return cls(
            public_id=data.get('public_id'),
            object_id=data.get('object_id'),
            version=data.get('version', None),
            user_name=data.get('user_name'),
            user_id=data.get('user_id'),
            render_state=data.get('render_state'),
            log_time=data.get('log_time', None),
            log_type=data.get('log_type', None),
            changes=data.get('changes', None),
            comment=data.get('comment', None),
            action=data.get('action', None),
            action_name=data.get('action_name', None),
        )


    @classmethod
    def to_json(cls, instance: "CmdbObjectLog") -> dict:
        """
        Convert a type instance to json conform data
        """
        return {
            'public_id': instance.public_id,
            'log_time': instance.log_time,
            'log_type': instance.log_type,
            'action': instance.action,
            'object_id': instance.object_id,
            'version': instance.version,
            'user_name': instance.user_name,
            'user_id': instance.user_id,
            'render_state': instance.render_state,
            'changes': instance.changes,
            'comment': instance.comment,
            'action_name': instance.action_name
        }
