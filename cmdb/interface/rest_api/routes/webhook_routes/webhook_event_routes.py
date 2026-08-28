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
Implementation of all API routes for CmdbWebhookEvents

A CmdbWebhookEvent is one delivery of a CmdbWebhook: what was sent, where, and how the receiver
answered. The three routes here read and prune that log. They carry no rights of their own - reading
an event needs ``base.framework.webhook.view`` and deleting one ``base.framework.webhook.delete``,
the rights of the webhook the event belongs to (see ``WebhookRight``)

For the cloud API they are ``ApiLevel.LOCKED``, which is a deliberate refusal rather than a level:
``__check_api_level`` denies a LOCKED route outright, so the delivery log is reachable from the
DataGerry frontend only. Note the asymmetry with the sibling blueprint: the webhook DEFINITIONS are
``ApiLevel.ADMIN``, so a cloud API client can create and edit a webhook but can not read its deliveries

Three properties of this log matter before changing anything here:

* **It is append-only and unbounded.** Every object write produces one document per matching active
  webhook. There is no retention policy and no bulk prune - the delete route removes one row - and
  deleting a CmdbWebhook deliberately leaves its events behind, so orphans accumulate. The indexes
  declared on ``CmdbWebhookEvent`` are what keep reading it from degrading as it grows.
* **Each row holds the full object documents.** ``object_before`` and ``object_after`` are complete
  serialised CmdbObjects, and this route returns them for every row even though the frontend's table
  renders four scalar columns.
* **Reading it needs no object ACL.** Those field values are readable with
  ``base.framework.webhook.view`` alone, whatever the object's own permissions say.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksEventManager

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WebhookRight
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.webhooks_event_manager import (
    WebhooksEventManagerGetError,
    WebhooksEventManagerDeleteError,
    WebhooksEventManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

webhook_event_blueprint = APIBlueprint('webhook_events', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@webhook_event_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@webhook_event_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
def get_webhook_event(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbWebhookEvent

    Requires the ``base.framework.webhook.view`` right - reading a delivery needs the same right as
    reading the webhook that produced it

    Args:
        public_id (int): public_id of the CmdbWebhookEvent which should be retrieved
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: The requested CmdbWebhookEvent

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhookEvent carries the
            public_id; 400 when the retrieval fails; 500 on an unexpected error
    """
    try:
        webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                                   request_user)

        requested_webhook_event = webhook_events_manager.get_item(public_id, as_dict=True)

        if not requested_webhook_event:
            abort(404, f"The Webhook Event with ID: {public_id} was not found!")

        return DefaultResponse(requested_webhook_event).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksEventManagerGetError as err:
        LOGGER.error("[get_webhook_event] WebhooksEventManagerGetError: %s", err, exc_info=True)
        abort(400, f"Could not retrieve Webhook Event with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_webhook_event] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Webhook Event with ID: {public_id}!")


@webhook_event_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@webhook_event_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
@webhook_event_blueprint.parse_collection_parameters()
def get_webhook_events(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a paged list of CmdbWebhookEvents

    Requires the ``base.framework.webhook.view`` right

    Two things about this route are unlike the other list routes and are tracked as decisions rather
    than settled here:

    - the frontend's log table sends ``?filter=`` as a **list of aggregation stages**
      (``$addFields`` + ``$match``, built in ``webhook-log-viewer.component.ts``), not as a plain
      criteria dict. Those stages reach the pipeline as given, which is why the filter shape can not
      simply be locked down on this route alone
    - each row carries the complete ``object_before`` / ``object_after`` documents, while the table
      renders only four scalar columns

    The collection is indexed on ``webhook_id`` and ``event_time`` (see ``CmdbWebhookEvent``), the two
    keys this route is sorted and searched by

    Args:
        params (CollectionParameters): Filter, sort and paging parameters
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        GetMultiResponse: The CmdbWebhookEvents matching the params, with the pager metadata

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the iteration fails; 500 on an
            unexpected error
    """
    try:
        webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                                   request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbWebhookEvent] = webhook_events_manager.iterate_items(builder_params)
        webhook_event_list: list[dict[str, Any]] = [
            CmdbWebhookEvent.to_json(webhook_event) for webhook_event in iteration_result.results
        ]

        api_response = GetMultiResponse(webhook_event_list,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksEventManagerIterationError as err:
        LOGGER.error("[get_webhook_events] WebhooksEventManagerIterationError: %s", err, exc_info=True)
        abort(400, "Could not retrieve Webhook Events!")
    except Exception as err:
        LOGGER.error("[get_webhook_events] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating the Webhook Events!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@webhook_event_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@webhook_event_blueprint.protect(auth=True, right=WebhookRight.DELETE.value)
def delete_webhook_event(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a CmdbWebhookEvent

    Requires the ``base.framework.webhook.delete`` right. Deleting a delivery prunes the log only; the
    CmdbWebhook that produced it is untouched

    Registered WITHOUT a trailing slash, like the GET route above it. It used to carry one, which made
    the frontend's slash-less DELETE (``webhookLog.service.ts``) take a 308 redirect first

    Args:
        public_id (int): public_id of the CmdbWebhookEvent which should be deleted
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: True after the CmdbWebhookEvent has been deleted

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhookEvent carries the
            public_id; 400 when the deletion fails; 500 on an unexpected error
    """
    try:
        webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                                   request_user)

        to_delete_webhook_event = webhook_events_manager.get_item(public_id, as_dict=True)

        if not to_delete_webhook_event:
            abort(404, f"The Webhook Event with ID: {public_id} was not found!")

        ack: bool = webhook_events_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksEventManagerGetError as err:
        LOGGER.error("[delete_webhook_event] WebhooksEventManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook Event with ID: {public_id}!")
    except WebhooksEventManagerDeleteError as err:
        LOGGER.error("[delete_webhook_event] WebhooksEventManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete Webhook Event with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_webhook_event] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting Webhook Event with ID: {public_id}!")
