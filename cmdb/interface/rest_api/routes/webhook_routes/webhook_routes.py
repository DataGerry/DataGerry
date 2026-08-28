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

The deliveries these webhooks produce are the CmdbWebhookEvents served by ``webhook_event_routes``
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse, UpdateSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WebhookRight
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import parse_webhook_params
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
def create_webhook(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a CmdbWebhook

    Requires the ``base.framework.webhook.add`` right. The public_id is server-owned: it is reserved
    from the collection counter, so a payload can not choose it. The parameters arrive as query args
    rather than as a validated JSON body (see the request-schema decision in the backlog), so
    ``CmdbWebhook.SCHEMA`` never runs and ``parse_webhook_params`` is the whole of the validation -
    it is what refuses a webhook with no URL, an unusable scheme or an unknown event type

    Args:
        params (dict): CmdbWebhook parameters, incl. the ``event_types`` list
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: public_id of the created CmdbWebhook

    Raises:
        HTTPException: 400 when the parameters are malformed or the insert fails; 403 when the user
            lacks the right; 500 on an unexpected error
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        parse_webhook_params(params)
        params['public_id'] = webhooks_manager.get_next_public_id(inc_id=True)

        new_webhook_id = webhooks_manager.insert_item(CmdbWebhook.from_data(params))

        return DefaultResponse(new_webhook_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksManagerInsertError as err:
        LOGGER.error("[create_webhook] WebhooksManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to create the Webhook in the database!")
    except Exception as err:
        LOGGER.error("[create_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal error occured while creating the Webhook!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
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
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        requested_webhook = webhooks_manager.get_item(public_id, as_dict=True)

        if not requested_webhook:
            abort(404, f"The Webhook with ID: {public_id} was not found!")

        return DefaultResponse(requested_webhook).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksManagerGetError as err:
        LOGGER.error("[get_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while retrieving the Webhook with ID:{public_id}!")


@webhook_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.VIEW.value)
@webhook_blueprint.parse_collection_parameters()
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
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbWebhook] = webhooks_manager.iterate_items(builder_params)
        webhook_list: list[dict[str, Any]] = [CmdbWebhook.to_json(webhook) for webhook in iteration_result.results]

        api_response = GetMultiResponse(webhook_list,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksManagerIterationError as err:
        LOGGER.error("[get_webhooks] WebhooksManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to iterate Webhooks!")
    except Exception as err:
        LOGGER.error("[get_webhooks] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal error occured while iterating the Webhooks!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.EDIT.value)
@webhook_blueprint.parse_request_parameters()
def update_webhook(public_id: int, params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a CmdbWebhook

    Requires the ``base.framework.webhook.edit`` right. The public_id is pinned to the URL before the
    write, so a mismatched payload can not rewrite the CmdbWebhook's identity, and the parameters go
    through the same ``parse_webhook_params`` validation as on create

    The response is serialised from the instance that was just written rather than read back: a
    CmdbWebhook has no server-computed field, and ``update_item`` stores exactly
    ``CmdbWebhook.to_json(instance)``, so the two are the same document and the extra read was pure
    latency

    Args:
        public_id (int): public_id of the CmdbWebhook which should be updated
        params (dict): The updated CmdbWebhook parameters
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        UpdateSingleResponse: Response with the updated CmdbWebhook

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhook carries the
            public_id; 400 when the parameters are malformed or the update fails; 500 on an
            unexpected error
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        # Pin the identity to the URL so a mismatched body cannot rewrite the Webhook's public_id
        params['public_id'] = public_id
        parse_webhook_params(params)

        if not webhooks_manager.get_item(public_id):
            abort(404, f"The Webhook with ID: {public_id} was not found!")

        updated_webhook = CmdbWebhook.from_data(params)
        webhooks_manager.update_item(public_id, updated_webhook)

        return UpdateSingleResponse(CmdbWebhook.to_json(updated_webhook)).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksManagerGetError as err:
        LOGGER.error("[update_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Could not retrieve Webhook with ID: {public_id}!")
    except WebhooksManagerUpdateError as err:
        LOGGER.error("[update_webhook] WebhooksManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Could not update Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while updating the Webhook with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@webhook_blueprint.protect(auth=True, right=WebhookRight.DELETE.value)
def delete_webhook(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a CmdbWebhook

    Requires the ``base.framework.webhook.delete`` right. The CmdbWebhookEvents already produced by
    this webhook are left in place: they are a delivery log, not children of the definition

    Registered WITHOUT a trailing slash, like the other ``/<public_id>`` routes here. It used to carry
    one, which made the frontend's slash-less call take a 308 redirect first

    Args:
        public_id (int): public_id of the CmdbWebhook which should be deleted
        request_user (CmdbUser): The authenticated user issuing the request

    Returns:
        DefaultResponse: True after the CmdbWebhook has been deleted

    Raises:
        HTTPException: 403 when the user lacks the right; 404 when no CmdbWebhook carries the
            public_id; 400 when the deletion fails; 500 on an unexpected error
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        to_delete_webhook = webhooks_manager.get_item(public_id, as_dict=True)

        if not to_delete_webhook:
            abort(404, f"The Webhook with ID: {public_id} was not found!")

        ack: bool = webhooks_manager.delete_item(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except WebhooksManagerGetError as err:
        LOGGER.error("[delete_webhook] WebhooksManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")
    except WebhooksManagerDeleteError as err:
        LOGGER.error("[delete_webhook] WebhooksManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while deleting the Webhook with ID: {public_id}!")
