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
Validation schema for CmdbWebhook

A CmdbWebhook configures an outbound webhook - target URL and subscribed event types
(collection ``framework.webhooks``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbWebhook.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_webhook_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbWebhook document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbWebhook.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbWebhook
            'type': 'integer',
        },
        'name': {  # Human-readable name of the webhook
            'type': 'string',
            'required': True,
        },
        'url': {  # Target URL events are POSTed to
            'type': 'string',
            'required': True,
        },
        'event_types': {  # WebhookEventType values the webhook listens for
            'type': 'list',
            'required': True,
        },
        'active': {  # Whether the webhook is currently active and receiving events
            'type': 'boolean',
            'default': True,
        },
    }
