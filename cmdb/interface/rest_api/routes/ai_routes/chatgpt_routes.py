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
<<<<<<< HEAD
Definition of all routes for the Type Assistant
=======
Definition of the ChatGPT REST routes for the document generator
>>>>>>> origin/version-3.2
"""
from logging import Logger, getLogger
from flask import abort, request

from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
<<<<<<< HEAD
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.responses import DefaultResponse
=======
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.security.license.license_constants import LicenseFeature
>>>>>>> origin/version-3.2
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

chatgpt_blueprint = APIBlueprint('chatgpt', __name__)
<<<<<<< HEAD
=======

# Key of the user message in the request body of the /message route
MESSAGE_FIELD: str = 'message'
>>>>>>> origin/version-3.2
# -------------------------------------------------------------------------------------------------------------------- #

@chatgpt_blueprint.route('/message', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
<<<<<<< HEAD
=======
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
>>>>>>> origin/version-3.2
def send_chatgpt_message(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to interact with ChatGPT regarding the document generator

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The response from ChatGPT
    """
    try:
<<<<<<< HEAD
        user_message: dict = request.get_json()
        user_message = user_message.get('message')
=======
        request_body = request.get_json(silent=True)
        user_message = request_body.get(MESSAGE_FIELD) if isinstance(request_body, dict) else None
>>>>>>> origin/version-3.2

        if not user_message:
            abort(400, "No message provided!")

        chatgpt_response = ChatGptClient().send_template_request(user_message)

        return DefaultResponse(chatgpt_response).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[send_message_ai] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while interacting with ChatGPT!")
