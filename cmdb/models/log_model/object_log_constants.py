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
Entry keys of a CmdbObjectLog - one change-log entry of a CmdbObject

The keys the object write paths hand to ``LogsManager.insert_log`` for a CmdbObjectLog, named once:
the create / delete, edit, active-change and import writers all build the same entry.

``RENDER_STATE`` holds the object **as rendered** (a ``RenderResult``, JSON-encoded), whatever the
action - the log view draws it with the object renderer, so a raw stored document there renders empty.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'OBJECT_LOG_LOST_MARKER',
    'ObjectLogKey',
]

# The fixed text every lost change-log entry is logged under. A log entry is best-effort - the object
# write never waits for it - so this marker is how an operator finds out that one went missing: alert on
# it, and the line carries the action, the object id and the traceback
OBJECT_LOG_LOST_MARKER: str = 'OBJECT_LOG_LOST'


class ObjectLogKey(BaseStrEnum):
    """Keys of a CmdbObjectLog entry as the object write paths build it"""
    OBJECT_ID = 'object_id'
    VERSION = 'version'
    USER_ID = 'user_id'
    USER_NAME = 'user_name'
    COMMENT = 'comment'
    CHANGES = 'changes'
    RENDER_STATE = 'render_state'
