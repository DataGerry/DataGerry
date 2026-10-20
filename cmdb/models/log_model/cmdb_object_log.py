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
from typing import Any

from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import ObjectLogKey

from cmdb.class_schema.log_model.cmdb_object_log_schema import get_cmdb_object_log_schema
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbObjectLog - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectLog(CmdbMetaLog):
    """
    Implementation of CmdbObjectLog, a log entry recording a change made to a CmdbObject

    Written only through `LogsManager.insert_log`, best-effort after the object write. `SCHEMA` describes
    that stored entry (the `changes` shape per action, `render_state` as bytes, `user_name` as the display
    name, `type_id` as the logged object's type, which the reads judge the entry by); nothing validates it
    at write time -
    `tests/unit/models/log_model/test_cmdb_object_log_schema.py` holds it to what the writer produces

    Extends: CmdbMetaLog
    """

    SCHEMA: dict[str, Any] = get_cmdb_object_log_schema()

    UNKNOWN_USER_STRING = 'Unknown'

    # pylint: disable=too-many-arguments
    def __init__(self,
                 *,
                 public_id: int,
                 log_type: str | None,
                 log_time: datetime,
                 action: LogAction,
                 action_name: str,
                 object_id: int,
                 version: str | None,
                 user_id: int,
                 user_name: str | None = None,
                 changes: dict[str, Any] | list[Any] | None = None,
                 comment: str | None = None,
                 render_state: bytes | str | None = None,
                 type_id: int | None = None) -> None:
        """
        Initializes a new instance of the CmdbObjectLog class,
        representing a log entry for changes made to a CMDB object.

        Args:
            public_id (int): Unique identifier for the log entry
            log_type (str | None): Type or category of the log
            log_time (datetime): Timestamp when the log entry was created
            action (LogAction): Enum representing the type of action performed (e.g., create, update, delete)
            action_name (str): Human-readable name of the action
            object_id (int): ID of the CMDB object the log entry is associated with
            version (str | None): Version identifier of the object (e.g. '1.0.1')
            user_id (int): ID of the user who performed the action
            user_name (str | None): Name of the user who performed the action. Defaults to an "unknown"
                                       string if not provided
            changes (dict[str, Any] | list[Any] | None): The specific changes made to the object - the
                field-level diff dict of an edit, `{'old': bool, 'new': bool}` of an activation change; an
                entry without one (create, delete) stores an empty list
            comment (str | None): Additional comments or notes regarding the log entry
            render_state (bytes | str | None): Optional serialized render snapshot of the object at the time
                of the log (JSON-encoded bytes)
            type_id (int | None): public_id of the logged object's CmdbType at log time - what the reads
                judge the entry's visibility by. None for an entry whose type could not be determined
        """
        self.object_id = object_id
        self.type_id = type_id
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
    def from_data(cls, data: dict[str, Any]) -> "CmdbObjectLog":
        """Create a instance of CmdbType from database values"""
        return cls(
            public_id=data.get('public_id'),
            object_id=data.get('object_id'),
            version=data.get('version', None),
            user_name=data.get('user_name'),
            user_id=data.get('user_id'),
            render_state=data.get('render_state'),
            type_id=data.get(ObjectLogKey.TYPE_ID.value),
            log_time=data.get('log_time', None),
            log_type=data.get('log_type', None),
            changes=data.get('changes', None),
            comment=data.get('comment', None),
            action=data.get('action', None),
            action_name=data.get('action_name', None),
        )


    @classmethod
    def to_json(cls, instance: "CmdbObjectLog") -> dict[str, Any]:
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
            ObjectLogKey.TYPE_ID.value: instance.type_id,
            'changes': instance.changes,
            'comment': instance.comment,
            'action_name': instance.action_name
        }
