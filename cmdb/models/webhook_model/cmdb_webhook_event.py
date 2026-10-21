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
from datetime import datetime
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType

from cmdb.class_schema.webhook_model.cmdb_webhook_event_schema import get_cmdb_webhook_event_schema
from cmdb.models.webhook_model.webhook_event_constants import WebhookEventKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CmdbWebhookEvent - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbWebhookEvent(CmdbDAO):
    """
    One webhook delivery attempt: the event payload plus the transport outcome

    Written only by `webhook_helper.deliver_webhook_event`, once per attempt, successful or not.
    `SCHEMA` describes that document (which payload fields each operation sets, the date type of
    `event_time`, the 0 code of a delivery without a response); nothing validates it at write time,
    `tests/unit/models/webhook_model/test_cmdb_webhook_event_schema.py` holds it to what the writer produces

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.webhookEvents'
    DEFAULT_VERSION: str = '1.0.0'

    # This collection grows with every delivery - one document per object write per matching active webhook,
    # kept until its webhook is deleted (which deletes the webhook's events too) - and it is never read by
    # public_id from the UI. The log table sorts by webhook_id (its default) and searches webhook_id /
    # event_time, so without these two declarations every page view is a collection scan plus an in-memory
    # sort over a collection that keeps growing
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(WebhookEventKey.WEBHOOK_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': 'webhook_id',
        },
        {
            'keys': [(WebhookEventKey.EVENT_TIME.value, CmdbDAO.DAO_DESCENDING)],
            'name': 'event_time',
        },
    ]

    REQUIRED_INIT_KEYS: list[str] = [
        WebhookEventKey.EVENT_TIME.value,
        WebhookEventKey.OPERATION.value,
        WebhookEventKey.WEBHOOK_ID.value,
        WebhookEventKey.OBJECT_BEFORE.value,
        WebhookEventKey.OBJECT_AFTER.value,
        WebhookEventKey.CHANGES.value,
        WebhookEventKey.STATUS.value,
        WebhookEventKey.RESPONSE_CODE.value,
    ]

    SCHEMA: dict[str, Any] = get_cmdb_webhook_event_schema()

# ---------------------------------------------------- CONSTRUCTOR --------------------------------------------------- #

    def __init__(
            self,
            *,
            event_time: datetime | None,
            operation: WebhookEventType,
            webhook_id: int,
            object_before: dict[str, Any] | None,
            object_after: dict[str, Any] | None,
            changes: dict[str, Any] | None,
            response_code: int,
            status: bool,
            **kwargs: Any
        ) -> None:
        """
        Initializes a new instance of the CmdbWebhookEvent class, representing the result of a webhook event operation

        Args:
            event_time (datetime | None): Timestamp when the event occurred
            operation (WebhookEventType): Type of operation that triggered the webhook (e.g., create, update, delete)
            webhook_id (int): ID of the webhook configuration associated with this event
            object_before (dict[str, Any] | None): Object state before the operation occurred
            object_after (dict[str, Any] | None): Object state after the operation occurred
            changes (dict[str, Any] | None): Dictionary summarizing the changes made to the object
            response_code (int): HTTP response status code returned by the webhook endpoint
            status (bool): Whether the webhook request was successful (True for any 2xx response code)
            **kwargs (Any): Additional fields to pass to the superclass initializer
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
    def from_data(cls, data: dict[str, Any]) -> "CmdbWebhookEvent":
        """
        Creates a CmdbWebhookEvent instance from a dictionary

        Args:
            data (dict[str, Any]): Dictionary containing the event data fields

        Returns:
            CmdbWebhookEvent: A new instance populated with the provided data
        """
        return cls(
            public_id=data.get(WebhookEventKey.PUBLIC_ID.value),
            event_time=data.get(WebhookEventKey.EVENT_TIME.value, None),
            operation=data.get(WebhookEventKey.OPERATION.value, None),
            webhook_id=data.get(WebhookEventKey.WEBHOOK_ID.value, None),
            object_before=data.get(WebhookEventKey.OBJECT_BEFORE.value, None),
            object_after=data.get(WebhookEventKey.OBJECT_AFTER.value, None),
            changes=data.get(WebhookEventKey.CHANGES.value, None),
            response_code=data.get(WebhookEventKey.RESPONSE_CODE.value, None),
            status=data.get(WebhookEventKey.STATUS.value, False),
        )


    @classmethod
    def to_json(cls, instance: "CmdbWebhookEvent") -> dict[str, Any]:
        """
        Serializes a CmdbWebhookEvent instance into a JSON-compatible dictionary

        Args:
            instance (CmdbWebhookEvent): The event instance to serialize

        Returns:
            dict[str, Any]: A dictionary representation of the event suitable for JSON output
        """
        return {
            WebhookEventKey.PUBLIC_ID.value: instance.get_public_id(),
            WebhookEventKey.EVENT_TIME.value: instance.event_time,
            WebhookEventKey.OPERATION.value: instance.operation,
            WebhookEventKey.WEBHOOK_ID.value: instance.webhook_id,
            WebhookEventKey.OBJECT_BEFORE.value: instance.object_before,
            WebhookEventKey.OBJECT_AFTER.value: instance.object_after,
            WebhookEventKey.CHANGES.value: instance.changes,
            WebhookEventKey.RESPONSE_CODE.value: instance.response_code,
            WebhookEventKey.STATUS.value: instance.status,
        }
