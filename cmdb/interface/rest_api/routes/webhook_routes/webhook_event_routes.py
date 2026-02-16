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
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import WebhooksEventManager

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

webhook_event_blueprint = APIBlueprint('webhook_events', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@webhook_event_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_webhook_event(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the CmdbWebhookEvent with the given public_id
    
    Args:
        public_id (int): public_id of CmdbWebhookEvent which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbWebhookEvent
    """
    webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                               request_user)

    try:
        requested_webhook_event = webhook_events_manager.get_webhook_event(public_id)
    except BaseManagerGetError as err:
        #TODO: ERROR-FIX
        LOGGER.debug("[get_webhook_event] %s", err)
        abort(400, f"Could not retrieve Webhook Event with ID: {public_id}!")

    api_response = DefaultResponse(requested_webhook_event)

    return api_response.make_response()


@webhook_event_blueprint.route('/', methods=['GET', 'HEAD'])
@webhook_event_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_webhook_events(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns all CmdbWebhookEvents based on the params

    Args:
        params (CollectionParameters): Parameters to identify documents in database
    Returns:
        (GetMultiResponse): All CmdbWebhookEvents considering the params
    """
    webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                               request_user)

    try:
        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbWebhookEvent] = webhook_events_manager.iterate(builder_params)
        webhook_event_list: list[dict[str, Any]] = [webhook_event_.__dict__ for webhook_event_ in iteration_result.results]

        api_response = GetMultiResponse(webhook_event_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except BaseManagerIterationError as err:
        #TODO: ERROR-FIX
        LOGGER.debug("[get_webhook_events] %s: %s", type(err), err, exc_info=True)
        abort(400, "Could not retrieve Webhook Events!")
    except Exception as err:
        LOGGER.error("[get_webhook_events] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating the Webhook Events!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@webhook_event_blueprint.route('/<int:public_id>/', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def delete_webhook_event(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes the CmdbWebhookEvent with the given public_id
    
    Args:
        public_id (int): public_id of CmdbWebhookEvent which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbWebhookEvent
    """
    webhook_events_manager: WebhooksEventManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS_EVENT,
                                                                               request_user)

    try:
        webhook_event_instance: CmdbWebhookEvent = webhook_events_manager.get_webhook_event(public_id)

        if not webhook_event_instance:
            abort(400, f"Webhook with ID: {public_id} not found!")

        #TODO: REFACTOR-FIX
        ack: bool = webhook_events_manager.delete({'public_id':public_id})

        return DefaultResponse(ack).make_response()
    except BaseManagerGetError as err:
        #TODO: ERROR-FIX
        LOGGER.debug("[delete_webhook_event] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook Event with ID: {public_id}!")
    except BaseManagerDeleteError as err:
        #TODO: ERROR-FIX
        LOGGER.debug("[delete_webhook_event] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to delete Webhook Event with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_webhook_events] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting Webhook Event with ID: {public_id}!")
