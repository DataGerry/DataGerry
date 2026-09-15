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
This module contains the implementation of CmdbWebhookEvent, which is representing
a webhook event in Datagarry
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType

from cmdb.class_schema.webhook_model.cmdb_webhook_event_schema import get_cmdb_webhook_event_schema
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbWebhook - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbWebhookEvent(CmdbDAO):
    """
    Implementation of CmdbWebhookEvent

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.webhookEvents'
    DEFAULT_VERSION: str = '1.0.0'

    # This collection is append-only and unbounded - one document per object write per matching active
    # webhook - and it is never read by public_id from the UI. The log table sorts by webhook_id (its
    # default) and searches webhook_id / event_time, so without these two declarations every page view
    # is a collection scan plus an in-memory sort over a collection that only ever grows
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('webhook_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'webhook_id',
        },
        {
            'keys': [('event_time', CmdbDAO.DAO_DESCENDING)],
            'name': 'event_time',
        },
    ]

    REQUIRED_INIT_KEYS: list[str] = [
        'event_time',
        'operation',
        'webhook_id',
        'object_before',
        'object_after',
        'changes',
        'status',
        'response_code',
    ]

    SCHEMA: dict[str, Any] = get_cmdb_webhook_event_schema()

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    #pylint: disable=R0913, R0917
    def __init__(
            self,
            event_time,
            operation: WebhookEventType,
            webhook_id: int,
            object_before: dict,
            object_after: dict,
            changes: dict,
            response_code: int,
            status: bool,
            **kwargs
        ) -> None:
        """
        Initializes a new instance of the CmdbWebhookEvent class, representing the result of a webhook event operation

        Args:
            event_time: Timestamp when the event occurred (type can be datetime or str depending on usage)
            operation (WebhookEventType): Type of operation that triggered the webhook (e.g., create, update, delete)
            webhook_id (int): ID of the webhook configuration associated with this event
            object_before (dict): Object state before the operation occurred
            object_after (dict): Object state after the operation occurred
            changes (dict): Dictionary summarizing the changes made to the object
            response_code (int): HTTP response status code returned by the webhook endpoint
            status (bool): Whether the webhook request was successful (True if response code was 200)
            **kwargs: Additional fields to pass to the superclass initializer
        """
        self.event_time = event_time
        self.operation = operation
        self.webhook_id = webhook_id
        self.object_before = object_before
        self.object_after = object_after
        self.changes = changes
        self.response_code = response_code
        self.status = status

        super().__init__(**kwargs)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbWebhookEvent":
        """
        Creates a CmdbWebhookEvent instance from a dictionary

        Args:
            data (dict): Dictionary containing the event data fields

        Returns:
            CmdbWebhookEvent: A new instance populated with the provided data
        """
        return cls(
            public_id = data.get('public_id'),
            event_time = data.get('event_time', None),
            operation = data.get('operation', None),
            webhook_id = data.get('webhook_id', None),
            object_before = data.get('object_before', None),
            object_after = data.get('object_after', None),
            changes = data.get('changes', None),
            response_code = data.get('response_code', None),
            status = data.get('status', False),
        )


    @classmethod
    def to_json(cls, instance: "CmdbWebhookEvent") -> dict:
        """
        Serializes a CmdbWebhookEvent instance into a JSON-compatible dictionary

        Args:
            instance (CmdbWebhookEvent): The event instance to serialize

        Returns:
            dict: A dictionary representation of the event suitable for JSON output
        """
        return {
            'public_id': instance.get_public_id(),
            'event_time': instance.event_time,
            'operation': instance.operation,
            'webhook_id': instance.webhook_id,
            'object_before': instance.object_before,
            'object_after': instance.object_after,
            'changes': instance.changes,
            'response_code': instance.response_code,
            'status': instance.status,
        }
