# DataGerry - OpenSource Enterprise CMDB
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
The schema of a CmdbObjectLog
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_VERSION: str = '1.0.0'

# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_object_log_schema() -> dict[str, Any]:
    """
    Returns the CmdbObjectLogSchema

    Returns:
        dict: Schema of the CmdbObjectLog
    """
    return {
        'object_id': {  # public_id of the CmdbObject this log entry refers to
            'type': 'integer',
        },
        'public_id': {  # public_id of the log entry itself
            'type': 'integer',
        },
        'version': {  # Object version at log time (NOTE: typed integer but defaults to the '1.0.0' string)
            'type': 'integer',
            'default': DEFAULT_VERSION,
        },
        'user_id': {  # public_id of the CmdbUser who triggered the action
            'type': 'integer',
        },
        'user_name': {  # Name of the acting user
            'type': 'string',
            'required': True,
            'regex': r'(\w+)-*(\w)([\w-]*)',  # kebab case validation
        },
        'render_state': {  # Optional serialized render snapshot of the object at log time
            'type': 'string',
        },
        'log_type': {  # Log category / type discriminator
            'type': 'string',
            'required': True,
        },
        'log_time': {  # Timestamp when the log entry was created
            'type': 'datetime',
            'required': True,
        },
        'changes': {  # List of field-level changes captured in this entry
            'type': 'list',
            'empty': True,
            'default': [],
        },
        'comment': {  # Optional free-text comment on the action
            'type': 'string',
        },
        'action': {  # LogAction as an integer code (e.g. create / edit / delete)
            'type': 'integer',
            'required': True,
        },
        'action_name': {  # Human-readable name of the action
            'type': 'string',
            'required': True,
        },
    }
