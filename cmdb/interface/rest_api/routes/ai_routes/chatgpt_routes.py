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
Definition of the ChatGPT REST routes for the document generator

Two routes: `/message` sends a prompt, `/status` answers whether the installation has a ChatGPT API
key at all. The status route exists so a client can disable the AI Assistant before a user presses
it, instead of learning from a failed generation
"""
from logging import Logger, getLogger
from flask import abort, request

from werkzeug import Response

from cmdb.models.user_model import CmdbUser

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client_constants import ChatGptStatusKey
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.ai import ChatGptNotConfiguredError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

chatgpt_blueprint = APIBlueprint('chatgpt', __name__)

# Key of the user message in the request body of the /message route
MESSAGE_FIELD: str = 'message'

# Status answered when the installation has no ChatGPT API key. Not a 500: nothing failed and the
# request was valid, the integration was simply never set up. Not the 403 the license guard on this
# same route already uses either, so the frontend can tell "you may not use this" from "nobody
# configured this" without reading the message
NOT_CONFIGURED_STATUS: int = 503
# -------------------------------------------------------------------------------------------------------------------- #

@chatgpt_blueprint.route('/message', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while interacting with ChatGPT")
def send_chatgpt_message(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to interact with ChatGPT regarding the document generator

    Answers `NOT_CONFIGURED_STATUS` when the installation has no ChatGPT API key, carrying the
    message that names the setting to add. Without that arm every unconfigured installation got the
    error tail's generic 500, which reported what the route was doing and never what was wrong

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The response from ChatGPT
    """
    request_body = request.get_json(silent=True)
    user_message = request_body.get(MESSAGE_FIELD) if isinstance(request_body, dict) else None

    if not user_message:
        abort(400, "No message provided!")

    try:
        chatgpt_response = ChatGptClient().send_template_request(user_message)
    except ChatGptNotConfiguredError as err:
        LOGGER.error("[send_chatgpt_message] ChatGptNotConfiguredError: %s", err)
        abort(NOT_CONFIGURED_STATUS, str(err))

    return DefaultResponse(chatgpt_response).make_response()


@chatgpt_blueprint.route('/status', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while checking whether ChatGPT is configured")
def get_chatgpt_status(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route reporting whether ChatGPT is configured

    **Authenticated, but carries no ACL right**, like the OpenCelium config-status route it mirrors:
    the answer is one boolean about the installation, so there is nothing to withhold from a user who
    may already reach the feature

    The question is answered by the same `resolve_api_key` the generation path uses, so the two
    cannot disagree about what "configured" means. No key value, no source and no part of either
    leaves the backend, and no OpenAI client is built - nothing here reaches the network

    Args:
        request_user (CmdbUser): The requesting user; unused in the body - the route reads only
                                 process-wide configuration, but the user is injected to authenticate

    Returns:
        DefaultResponse: `configured` (see `ChatGptStatusKey`), True when a usable API key exists
    """
    try:
        ChatGptClient.resolve_api_key()
        configured: bool = True
    except ChatGptNotConfiguredError:
        configured = False

    return DefaultResponse({ChatGptStatusKey.CONFIGURED.value: configured}).make_response()
