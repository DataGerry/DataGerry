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
The schema of a CmdbWebhookEvent
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_webhook_event_schema() -> dict[str, Any]:
    """
    Returns the CmdbWebhookEventSchema

    Returns:
        dict: Schema of the CmdbWebhookEvent
    """
    return {
        'public_id': {  # public_id of the CmdbWebhookEvent
            'type': 'integer',
        },
        'event_time': {  # Timestamp payload describing when the event occurred
            'type': 'dict',
            'nullable': True,
        },
        'operation': {  # Triggering operation (a WebhookEventType value: CREATE / UPDATE / DELETE)
            'type': 'string',
        },
        'webhook_id': {  # public_id of the CmdbWebhook that produced this event
            'type': 'integer',
        },
        'object_before': {  # Serialized object state before the change
            'type': 'dict',
            'required': False,
        },
        'object_after': {  # Serialized object state after the change
            'type': 'dict',
            'required': False,
        },
        'changes': {  # Diff between object_before and object_after
            'type': 'dict',
            'required': False,
        },
        'response_code': {  # HTTP status code returned by the webhook target
            'type': 'integer',
            'default': 200,
        },
        'status': {  # Whether delivery to the target succeeded
            'type': 'boolean',
            'required': False,
        },
    }
