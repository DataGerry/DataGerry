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
"""
from logging import Logger, getLogger
from typing import Any
from ast import literal_eval

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
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

webhook_blueprint = APIBlueprint('webhooks', __name__)


def _parse_webhook_params(params: dict[str, Any]) -> None:
    """
    Normalises the form-encoded webhook params in place: ``event_types`` from a string literal to a
    list and ``active`` to a bool. Aborts 400 when event_types is missing or not a valid literal.

    Args:
        params (dict[str, Any]): The request params to normalise
    """
    try:
        params['event_types'] = literal_eval(params['event_types'])
    except (KeyError, ValueError, SyntaxError):
        abort(400, "Invalid or missing 'event_types' for the Webhook!")

    params['active'] = str(params.get('active')).lower() == 'true'

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@webhook_blueprint.route('/', methods=['POST'])
@webhook_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_webhook(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Creates a CmdbWebhook in the database

    Args:
        params (dict): CmdbWebhook parameters
    Returns:
        DefaultResponse: public_id of the created CmdbWebhook
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        _parse_webhook_params(params)
        params['public_id'] = webhooks_manager.get_next_public_id(inc_id=True)

        new_webhook_id = webhooks_manager.insert_item(CmdbWebhook.from_data(params))

        return DefaultResponse(new_webhook_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerInsertError as err:
        LOGGER.error("[create_webhook] BaseManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to create the Webhook in the database!")
    except Exception as err:
        LOGGER.error("[create_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal error occured while creating the Webhook!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_webhook(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the CmdbWebhook with the given public_id

    Args:
        public_id (int): public_id of CmdbWebhook which should be retrieved
        request_user (CmdbUser): User which is requesting the CmdbWebhook
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        requested_webhook = webhooks_manager.get_item(public_id, as_dict=True)

        if not requested_webhook:
            abort(404, f"The Webhook with ID: {public_id} was not found!")

        return DefaultResponse(requested_webhook).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerGetError as err:
        LOGGER.error("[get_webhook] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while retrieving the Webhook with ID:{public_id}!")


@webhook_blueprint.route('/', methods=['GET', 'HEAD'])
@webhook_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_webhooks(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Returns all CmdbWebhooks based on the params

    Args:
        params (CollectionParameters): Parameters to identify documents in database
    Returns:
        (GetMultiResponse): All CmdbWebhooks considering the params
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbWebhook] = webhooks_manager.iterate_items(builder_params)
        webhook_list: list[dict[str, Any]] = [CmdbWebhook.to_json(webhook) for webhook in iteration_result.results]

        api_response = GetMultiResponse(webhook_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except BaseManagerIterationError as err:
        LOGGER.error("[get_webhooks] BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to iterate Webhooks!")
    except Exception as err:
        LOGGER.error("[get_webhooks] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal error occured while iterating the Webhooks!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@webhook_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_webhook(params: dict[str, Any], request_user: CmdbUser, public_id: int) -> Response:
    """
    Updates a CmdbWebhook

    Args:
        params (dict): updated CmdbWebhook parameters
        public_id (int): public_id of the CmdbWebhook which should be updated
    Returns:
        UpdateSingleResponse: Response with the updated CmdbWebhook
    """
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        # Pin the identity to the URL so a mismatched body cannot rewrite the Webhook's public_id
        params['public_id'] = public_id
        _parse_webhook_params(params)

        if not webhooks_manager.get_item(public_id):
            abort(404, f"The Webhook with ID: {public_id} was not found!")

        webhooks_manager.update_item(public_id, CmdbWebhook.from_data(params))

        updated_webhook = webhooks_manager.get_item(public_id, as_dict=True)

        return UpdateSingleResponse(updated_webhook).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerGetError as err:
        LOGGER.error("[update_webhook] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Could not retrieve Webhook with ID: {public_id}!")
    except BaseManagerUpdateError as err:
        LOGGER.error("[update_webhook] BaseManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Could not update Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while updating the Webhook with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@webhook_blueprint.route('/<int:public_id>/', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def delete_webhook(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes the CmdbWebhook with the given public_id

    Args:
        public_id (int): public_id of CmdbWebhook which should be deleted
        request_user (CmdbUser): User which is requesting the deletion
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
    except BaseManagerGetError as err:
        LOGGER.error("[delete_webhook] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Webhook with ID: {public_id}!")
    except BaseManagerDeleteError as err:
        LOGGER.error("[delete_webhook] BaseManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete Webhook with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_webhook] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal error occured while deleting the Webhook with ID: {public_id}!")
