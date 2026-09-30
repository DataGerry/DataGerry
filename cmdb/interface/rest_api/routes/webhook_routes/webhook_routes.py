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
Implementation of all API routes for CmdbWebhooks

A CmdbWebhook is an outbound HTTP callback: an event type plus the URL it is posted to. The five
routes here are its CRUD surface, each guarded by the matching ``base.framework.webhook.*`` right
(see ``WebhookRight``) on top of ``ApiLevel.ADMIN`` for the cloud API - a webhook sends DataGerry
data to a third-party URL, so who may create or edit one is an authorisation question, not only an
API-level one

The two write routes read their payload from the JSON body; a key the body leaves out is read from
the query string instead (``read_write_payload``), so a client that only sends query parameters keeps
working. ``parse_webhook_params`` then validates and normalises it and holds the result against
``CmdbWebhook.SCHEMA``

The deliveries these webhooks produce are the CmdbWebhookEvents served by ``webhook_event_routes``
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse, UpdateSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WEBHOOK_ENTITY_LABEL, WebhookRight
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import parse_webhook_params
from cmdb.interface.rest_api.routes.routes_helper import (
    pin_public_id,
    read_write_payload,
    request_wants_body,
    update_item_from_payload,
)
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.webhooks_manager import (
    WebhooksManagerInsertError,
    WebhooksManagerGetError,
    WebhooksManagerIterationError,
    WebhooksManagerUpdateError,
    WebhooksManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

webhook_blueprint = APIBlueprint('webhooks', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@webhook_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.ADD.value)
@webhook_blueprint.parse_request_parameters()
@handle_route_errors("while creating the Webhook")
def create_webhook(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a CmdbWebhook

    Requires the ``base.framework.webhook.add`` right. The payload is the JSON body, with the query
    string filling any key the body leaves out; ``parse_webhook_params`` validates and normalises it
    (a missing ``active`` becomes True). The public_id is server-owned: it is reserved from the
    collection counter, so a payload can not choose it

    Args:
        params (dict): The query-string parameters; a JSON body overrides them key by key
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: public_id of the created CmdbWebhook

    Raises:
        HTTPException: 400 when the payload is malformed or the insert fails; 403 when the user lacks
            the right; 500 on an unexpected error
    """
    webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

    payload: dict[str, Any] = read_write_payload(params, WEBHOOK_ENTITY_LABEL)
    parse_webhook_params(payload)

    try:
        payload['public_id'] = webhooks_manager.get_next_public_id(inc_id=True)

        new_webhook_id = webhooks_manager.insert_item(CmdbWebhook.from_data(payload))
    except WebhooksManagerInsertError as err:
        LOGGER.error("[create_webhook] WebhooksManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to create the Webhook in the database!")

    return DefaultResponse(new_webhook_id).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
@handle_route_errors("while retrieving the Webhook with ID: {public_id}")
def get_webhook(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbWebhook

    Requires the ``base.framework.webhook.view`` right

    Args:
        public_id (int): public_id of the CmdbWebhook which should be retrieved
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: The requested CmdbWebhook

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhook carries the
            public_id; 400 when the retrieval fails; 500 on an unexpected error
    """
    webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

    try:
        requested_webhook = webhooks_manager.get_item(public_id, as_dict=True)
    except WebhooksManagerGetError as err:
        LOGGER.error("[get_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")

    if not requested_webhook:
        abort(404, f"The Webhook with ID: {public_id} was not found!")

    return DefaultResponse(requested_webhook).make_response()


@webhook_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
@webhook_blueprint.parse_collection_parameters()
@handle_route_errors("while iterating the Webhooks")
def get_webhooks(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a paged list of CmdbWebhooks

    Requires the ``base.framework.webhook.view`` right

    Args:
        params (CollectionParameters): Filter, sort and paging parameters
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        GetMultiResponse: The CmdbWebhooks matching the params, with the pager metadata

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the iteration fails; 500 on an
            unexpected error
    """
    webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

    builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

    try:
        iteration_result: IterationResult[CmdbWebhook] = webhooks_manager.iterate_items(builder_params)
    except WebhooksManagerIterationError as err:
        LOGGER.error("[get_webhooks] WebhooksManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to iterate Webhooks!")

    webhook_list: list[dict[str, Any]] = [CmdbWebhook.to_json(webhook) for webhook in iteration_result.results]

    api_response = GetMultiResponse(webhook_list,
                                    total=iteration_result.total,
                                    params=params,
                                    url=request.url,
                                    body=request_wants_body())

    return api_response.make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.EDIT.value)
@webhook_blueprint.parse_request_parameters()
@handle_route_errors("while updating the Webhook with ID: {public_id}")
def update_webhook(public_id: int, params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a CmdbWebhook

    Requires the ``base.framework.webhook.edit`` right. The payload is read like on create - the JSON
    body, with the query string filling any key the body leaves out - and goes through the same
    ``parse_webhook_params`` validation. The public_id is pinned to the URL before the write, so a
    mismatched payload can not rewrite the CmdbWebhook's identity. Both methods replace the whole
    document: a key the payload leaves out is not kept from the stored webhook

    Args:
        public_id (int): public_id of the CmdbWebhook which should be updated
        params (dict): The query-string parameters; a JSON body overrides them key by key
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        UpdateSingleResponse: Response with the CmdbWebhook as stored

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhook carries the
            public_id; 400 when the payload is malformed or the update fails; 500 on an unexpected
            error
    """
    webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

    payload: dict[str, Any] = pin_public_id(read_write_payload(params, WEBHOOK_ENTITY_LABEL), public_id)
    parse_webhook_params(payload)

    try:
        if not webhooks_manager.get_item(public_id):
            abort(404, f"The Webhook with ID: {public_id} was not found!")
    except WebhooksManagerGetError as err:
        LOGGER.error("[update_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Could not retrieve Webhook with ID: {public_id}!")

    try:
        stored_webhook = update_item_from_payload(webhooks_manager, public_id, CmdbWebhook, payload)
    except WebhooksManagerUpdateError as err:
        LOGGER.error("[update_webhook] WebhooksManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Could not update Webhook with ID: {public_id}!")

    return UpdateSingleResponse(stored_webhook).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.DELETE.value)
@handle_route_errors("while deleting the Webhook with ID: {public_id}")
def delete_webhook(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a CmdbWebhook

    Requires the ``base.framework.webhook.delete`` right. The CmdbWebhookEvents already produced by
    this webhook are left in place: they are a delivery log, not children of the definition

    Registered WITHOUT a trailing slash, like the other ``/<public_id>`` routes here. The frontend calls
    it slash-less, so a trailing slash would cost that call a 308 redirect first

    Args:
        public_id (int): public_id of the CmdbWebhook which should be deleted
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: True after the CmdbWebhook has been deleted

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhook carries the
            public_id; 400 when the deletion fails; 500 on an unexpected error
    """
    webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

    try:
        to_delete_webhook = webhooks_manager.get_item(public_id, as_dict=True)
    except WebhooksManagerGetError as err:
        LOGGER.error("[delete_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")

    if not to_delete_webhook:
        abort(404, f"The Webhook with ID: {public_id} was not found!")

    try:
        ack: bool = webhooks_manager.delete_item(public_id)
    except WebhooksManagerDeleteError as err:
        LOGGER.error("[delete_webhook] WebhooksManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete Webhook with ID: {public_id}!")

    return DefaultResponse(ack).make_response()
