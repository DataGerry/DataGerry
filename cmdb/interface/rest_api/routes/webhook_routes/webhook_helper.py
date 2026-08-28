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
Helper for the CmdbWebhook routes: validating the request parameters and emitting webhook events

Two roles, both belonging to the caller/helper layer rather than to a manager:

* ``parse_webhook_params`` normalises and validates what the create/update routes receive. The
  parameters arrive as query args rather than as a validated JSON body (a decision tracked in the
  backlog), so ``CmdbWebhook.SCHEMA`` never runs and this function is the ONLY validation a webhook
  document gets. It is therefore where the required fields, the event-type list and the URL scheme
  are checked.
* ``send_webhook_event`` notifies the configured CmdbWebhooks and records a CmdbWebhookEvent per
  delivery. The orchestration spans two domains (reading the CmdbWebhooks and writing the events), so
  it cannot live inside a manager - a manager must not depend on another manager. Both managers are
  resolved here from the request user, mirroring the calculate_risk_matrix(request_user) pattern.

Delivery rules worth knowing before changing anything here:

* **Each delivery is independent.** The POST and the event insert of one webhook are guarded on their
  own, so a webhook whose target times out can neither stop the webhooks after it nor suppress its own
  log entry. Every attempt produces a CmdbWebhookEvent, including a failed one - a delivery log that
  only recorded successes could not answer the one question it exists for.
* **Delivery does not block the write.** The webhooks are read on the request thread (one query) and
  the HTTP calls are handed to a small shared pool, because ``send_webhook_event`` is called inline
  from the object create / update / delete flows in ``objects_helper``. Delivering synchronously made
  every object save wait up to the request timeout for every active webhook.
* **Any 2xx counts as delivered**, not only ``200``.
"""
from logging import Logger, getLogger
from typing import Any
from ast import literal_eval
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
import json
from datetime import datetime, timezone

from flask import abort
import requests

from cmdb.database.database_utils import default
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksManager, WebhooksEventManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import (
    WEBHOOK_ALLOWED_URL_SCHEMES,
    WEBHOOK_DELIVERED_STATUS_MAX,
    WEBHOOK_DELIVERED_STATUS_MIN,
    WEBHOOK_DISPATCH_MAX_WORKERS,
    WEBHOOK_DISPATCH_THREAD_PREFIX,
    WEBHOOK_NO_RESPONSE_CODE,
    WEBHOOK_REQUEST_TIMEOUT_SECONDS,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Shared pool the deliveries are handed to. A ThreadPoolExecutor starts no thread until the first
#: submit, so holding it at module level costs nothing when no webhook is configured
DISPATCH_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=WEBHOOK_DISPATCH_MAX_WORKERS,
    thread_name_prefix=WEBHOOK_DISPATCH_THREAD_PREFIX,
)

# ------------------------------------------------ REQUEST PARAMETERS ------------------------------------------------ #

def parse_webhook_params(params: dict[str, Any]) -> None:
    """
    Normalises and validates the form-encoded CmdbWebhook params in place

    The create and update routes read their parameters from the query string, so nothing has coerced
    or checked them yet and ``CmdbWebhook.SCHEMA`` is never applied. This function is the whole of the
    validation a webhook document gets:

    - ``name`` and ``url`` must be present and non-blank (the schema marks both required, but it does
      not run - and a webhook with no URL is one whose every delivery fails)
    - ``url`` must carry an allowed scheme and a host: the server itself fetches this URL
    - ``event_types`` must be a **list** of known ``WebhookEventType`` values. It arrives as a string
      literal, and ``literal_eval`` happily returns an int or a dict, either of which would be stored
      and produce a webhook that silently never matches an event
    - ``active`` is coerced to a bool

    Args:
        params (dict[str, Any]): The request params to normalise, modified in place

    Raises:
        HTTPException: 400 when a required parameter is missing or blank, when the URL is not usable,
            or when event_types is not a list of known event types
    """
    params['name'] = _require_non_blank(params.get('name'), 'name')
    params['url'] = _validated_webhook_url(params.get('url'))
    params['event_types'] = _validated_event_types(params.get('event_types'))
    params['active'] = str(params.get('active')).lower() == 'true'


def _require_non_blank(value: Any, field_name: str) -> str:
    """
    Returns the value as a stripped string, aborting when it is missing or blank

    Args:
        value (Any): The raw parameter value
        field_name (str): Name of the parameter, used in the error message

    Raises:
        HTTPException: 400 when the value is None or contains only whitespace

    Returns:
        str: The value with surrounding whitespace removed
    """
    if value is None or not str(value).strip():
        abort(400, f"The '{field_name}' of a Webhook is required!")

    return str(value).strip()


def _validated_webhook_url(value: Any) -> str:
    """
    Returns the target URL, aborting when it is missing or not a fetchable http(s) URL

    Args:
        value (Any): The raw ``url`` parameter

    Raises:
        HTTPException: 400 when the URL is missing, blank, carries a scheme outside
            ``WEBHOOK_ALLOWED_URL_SCHEMES`` or has no host

    Returns:
        str: The validated URL
    """
    url = _require_non_blank(value, 'url')

    # urlsplit never raises for a plain string, so the checks below are the whole guard
    parts = urlsplit(url)

    if parts.scheme.lower() not in WEBHOOK_ALLOWED_URL_SCHEMES:
        allowed = ', '.join(sorted(WEBHOOK_ALLOWED_URL_SCHEMES))
        abort(400, f"The 'url' of a Webhook must use one of these schemes: {allowed}!")

    if not parts.netloc:
        abort(400, "The 'url' of a Webhook must contain a host!")

    return url


def _validated_event_types(value: Any) -> list[str]:
    """
    Parses the ``event_types`` string literal into a list of known WebhookEventType values

    Args:
        value (Any): The raw ``event_types`` parameter, a Python/JSON list literal as a string

    Raises:
        HTTPException: 400 when the value is missing, is not a valid literal, is not a list, is empty
            or names an event type that does not exist

    Returns:
        list[str]: The event type values the webhook subscribes to
    """
    if value is None:
        abort(400, "Invalid or missing 'event_types' for the Webhook!")

    try:
        event_types = literal_eval(str(value))
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        abort(400, "Invalid or missing 'event_types' for the Webhook!")

    if not isinstance(event_types, list) or not event_types:
        abort(400, "The 'event_types' of a Webhook must be a non-empty list!")

    known = {event_type.value for event_type in WebhookEventType}
    unknown = [str(event_type) for event_type in event_types if str(event_type) not in known]

    if unknown:
        abort(400, f"Unknown Webhook event types: {', '.join(unknown)}! Allowed: {', '.join(sorted(known))}")

    return [str(event_type) for event_type in event_types]

# -------------------------------------------------- EVENT EMISSION -------------------------------------------------- #

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


def deliver_webhook_event(webhook: Any, payload: dict[str, Any],
                          webhook_events_manager: WebhooksEventManager) -> None:
    """
    POSTs one payload to one CmdbWebhook and records the resulting CmdbWebhookEvent

    Guarded on its own so one unreachable target cannot affect any other webhook, and so a failed
    attempt is still logged: a transport failure is recorded with ``WEBHOOK_NO_RESPONSE_CODE`` and
    ``status`` False rather than not being recorded at all. Any 2xx counts as delivered.

    Args:
        webhook (Any): The CmdbWebhook to notify (needs ``url`` and ``public_id``)
        payload (dict[str, Any]): The event payload; this function adds the transport metadata to it
        webhook_events_manager (WebhooksEventManager): Manager used to store the CmdbWebhookEvent
    """
    try:
        response: requests.Response = requests.post(
            webhook.url,
            data=json.dumps(payload, default=default, ensure_ascii=False, indent=2),
            headers={'Content-Type': 'application/json'},
            timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
        )
        response_code = response.status_code
        delivered = WEBHOOK_DELIVERED_STATUS_MIN <= response_code < WEBHOOK_DELIVERED_STATUS_MAX
    except Exception as err:
        LOGGER.error("[deliver_webhook_event] Webhook ID: %s could not be reached: %s. Type: %s",
                     webhook.public_id, err, type(err).__name__)
        response_code = WEBHOOK_NO_RESPONSE_CODE
        delivered = False

    payload.update({
        'webhook_id': webhook.public_id,
        'response_code': response_code,
        'status': delivered,
    })

    try:
        webhook_events_manager.insert_item(payload)
    except Exception as err:
        LOGGER.error("[deliver_webhook_event] Could not record the event of Webhook ID: %s: %s. Type: %s",
                     webhook.public_id, err, type(err).__name__)


def dispatch_webhook_deliveries(webhooks: list[Any], payload: dict[str, Any],
                                webhook_events_manager: WebhooksEventManager) -> None:
    """
    Hands one delivery per CmdbWebhook to the shared pool so the caller's write is not blocked

    Each delivery gets its own copy of the payload, because ``deliver_webhook_event`` adds that
    webhook's transport metadata to the dict it is given.

    Args:
        webhooks (list[Any]): The CmdbWebhooks to notify
        payload (dict[str, Any]): The event payload shared by every delivery
        webhook_events_manager (WebhooksEventManager): Manager used to store the CmdbWebhookEvents
    """
    for webhook in webhooks:
        DISPATCH_EXECUTOR.submit(deliver_webhook_event, webhook, dict(payload), webhook_events_manager)


def send_webhook_event(
        request_user: CmdbUser,
        operation: WebhookEventType,
        object_before: dict[str, Any] | None = None,
        object_after: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None) -> None:
    """
    Notifies every active CmdbWebhook subscribed to the operation and records the resulting events

    The webhooks are read here, on the request thread, because resolving the managers needs the
    request context; the HTTP calls are then dispatched off it. Failures while reading are swallowed
    (logged) so a webhook problem never breaks the triggering object operation - a per-delivery
    failure is handled in ``deliver_webhook_event`` and does not reach this level.

    Args:
        request_user (CmdbUser): The user whose request triggered the event (used to resolve managers)
        operation (WebhookEventType): The operation that triggered the event
        object_before (dict[str, Any] | None): Object state before the change
        object_after (dict[str, Any] | None): Object state after the change
        changes (dict[str, Any] | None): Summary of the changes
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        # Only active webhooks subscribed to this operation, filtered server-side
        builder_params = BuilderParameters({'$and': [{'active': True}, {'event_types': operation}]})
        webhooks = webhooks_manager.iterate_items(builder_params).results

        if not webhooks:
            return

        webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(
            ManagerType.WEBHOOKS_EVENT, request_user
        )

        # One payload for the whole fan-out - it is identical for every webhook
        payload = build_webhook_payload(operation, object_before, object_after, changes)

        dispatch_webhook_deliveries(webhooks, payload, webhook_events_manager)
    except Exception as err:
        LOGGER.error("[send_webhook_event] Exception: %s, Type: %s", str(err), type(err))
