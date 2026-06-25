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
Definition of all routes for the Type Assistant
"""
from logging import Logger, getLogger
from flask import abort, request

from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

chatgpt_blueprint = APIBlueprint('chatgpt', __name__)
# -------------------------------------------------------------------------------------------------------------------- #

@chatgpt_blueprint.route('/message', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def send_chatgpt_message(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to interact with ChatGPT regarding the document generator

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The response from ChatGPT
    """
    try:
        user_message: dict = request.get_json()
        user_message = user_message.get('message')

        if not user_message:
            abort(400, "No message provided!")

        chatgpt_response = ChatGptClient().send_template_request(user_message)

        return DefaultResponse(chatgpt_response).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[send_message_ai] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while interacting with ChatGPT!")
