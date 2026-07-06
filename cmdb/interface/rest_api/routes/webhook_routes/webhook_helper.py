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
Helper for emitting webhook events when a CmdbObject changes.

This orchestration spans two domains (reading the configured CmdbWebhooks and recording a
CmdbWebhookEvent), so it lives in the caller/helper layer rather than inside a manager - a manager
must not depend on another manager. Both managers are resolved here from the request user, mirroring
the calculate_risk_matrix(request_user) helper pattern.
"""
from logging import Logger, getLogger
from typing import Any
import json
from datetime import datetime, timezone
import requests

from cmdb.database.database_utils import default
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksManager, WebhooksEventManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def build_webhook_payload(
        operation: WebhookEventType,
        object_before: dict[str, Any] | None,
        object_after: dict[str, Any] | None,
        changes: dict[str, Any] | None) -> dict[str, Any]:
    """
    Builds the event payload sent to webhook endpoints and stored as a CmdbWebhookEvent.

    Args:
        operation (WebhookEventType): The operation that triggered the event
        object_before (dict[str, Any] | None): Object state before the change
        object_after (dict[str, Any] | None): Object state after the change
        changes (dict[str, Any] | None): Summary of the changes

    Returns:
        dict[str, Any]: The event payload (without transport metadata)
    """
    return {
        'event_time': datetime.now(timezone.utc),
        'operation': operation,
        'object_before': object_before,
        'object_after': object_after,
        'changes': changes,
    }


def send_webhook_event(
        request_user: CmdbUser,
        operation: WebhookEventType,
        object_before: dict[str, Any] | None = None,
        object_after: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None) -> None:
    """
    Notifies every active CmdbWebhook subscribed to the operation and records the resulting event.

    Failures are swallowed (logged) so a webhook problem never breaks the triggering object operation.

    Args:
        request_user (CmdbUser): The user whose request triggered the event (used to resolve managers)
        operation (WebhookEventType): The operation that triggered the event
        object_before (dict[str, Any] | None): Object state before the change
        object_after (dict[str, Any] | None): Object state after the change
        changes (dict[str, Any] | None): Summary of the changes
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)
        webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(
            ManagerType.WEBHOOKS_EVENT, request_user
        )

        # Only active webhooks subscribed to this operation, filtered server-side
        builder_params = BuilderParameters({'$and': [{'active': True}, {'event_types': operation}]})
        webhooks = webhooks_manager.iterate_items(builder_params).results

        for webhook in webhooks:
            payload = build_webhook_payload(operation, object_before, object_after, changes)

            response: requests.Response = requests.post(
                webhook.url,
                data=json.dumps(payload, default=default, ensure_ascii=False, indent=2),
                headers={'Content-Type': 'application/json'},
                timeout=3,
            )

            payload.update({
                'webhook_id': webhook.public_id,
                'response_code': response.status_code,
                'status': response.status_code == 200,
            })

            webhook_events_manager.insert_item(payload)
    except Exception as err:
        LOGGER.error("[send_webhook_event] Exception: %s, Type: %s", str(err), type(err))
