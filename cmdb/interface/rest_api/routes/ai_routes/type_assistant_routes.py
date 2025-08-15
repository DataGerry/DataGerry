# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import json
import logging
from flask import abort, request
from cerberus import Validator

from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType

from cmdb.interface.rest_api.ai_models.gemini_model import gemini_model
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

type_assistant_blueprint = APIBlueprint('type_assistant', __name__)
# -------------------------------------------------------------------------------------------------------------------- #

@type_assistant_blueprint.route('/message', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def send_message_ai(request_user: CmdbUser):
    """
    HTTP `POST` route to interact with Gemini AI

    Args:
        data (dict): User message to AI ({'message': <string>})
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The response from the AI
    """
    try:
        user_message: dict = request.get_json()
        user_message = user_message.get('message')

        # LOGGER.debug(f"user_message: {user_message}")

        if not user_message:
            abort(400, "No message provided!")

        full_prompt = f"{PROMT_TEXT}\n\n{user_message}"

        response = gemini_model.generate_content(full_prompt)

        is_valid_type = True

        try:
            formatted_data = json.loads(response.text)

            try:
                validator = Validator(CmdbType.SCHEMA, purge_unknown=True)
                validator.validate(formatted_data)
            except Exception as err:
                LOGGER.debug("AI Response Type validation failed. Error:%s", err)
                is_valid_type = False

        except Exception as err:
            LOGGER.debug("AI Response to json failed. Error:%s", err)
            is_valid_type = False
            formatted_data = response.text

        # LOGGER.debug("formatted_text: %s", formatted_data)

        response_data = {
            'data': formatted_data,
            'is_valid_type': is_valid_type
        }

        # LOGGER.debug("response text: %s", response.text)
        return DefaultResponse(response_data).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[send_message_ai] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while interacting with the AI!")

# -------------------------------------------------------------------------------------------------------------------- #

PROMT_TEXT = """You are an assistant for the initial setup of IT documentation in the software "Datagerry".

Users will describe in natural language which IT components, systems, or assets they want to document.

Your task is to:
- Generate suggestions for suitable object types (e.g., "Server", "Firewall").
- Each object type consists of one or more sections. Each section contains attributes (with name and type).
- You should provide well-structured, clearly named attribute suggestions grouped thematically.

Structure:
- Every object type starts with a section called Information, which contains the attribute name (type: text).
- There are three predefined Global Sections with fixed names and attributes. If they are thematically appropriate, they
  should be included in the object type:
  - Network: ipAddress, hostname, dns, layer3Net
  - Rack mounting: rackUnits, mountingPosition, mountingOrientation
  - Model specifications: manufacturer, modelName, serialNumber
- If a Global Section is used, its attributes must not be duplicated in regular (custom) sections.

You may also propose additional custom sections, such as Location, Hardware, Configuration, Software, etc.

For each proposed object type, also specify:
- label: the visible name of the type (e.g., "Firewall")
- name: internal machine-readable name, derived from the label: all lowercase, spaces replaced with underscores
- icon: a suitable Font Awesome icon name in the format "fa-..." (e.g., "fa-server", "fa-network-wired", "fa-laptop").
  Only use freely available icons from the Font Awesome Free Library. If no specific icon fits, use a generic one like
  fa-cube, fa-box, fa-toolbox, or fa-question.
- isLocationSource: Indicates whether this object type can serve as a location for other objects (true or false)

Allowed attribute data types:
- text, textarea, date, number, checkbox, radio, select, location

The location type is a special attribute type that may be used at most once per object type.
Only use location when it makes sense for the object to have a physical location (e.g., for servers, racks,
rooms, buildings). Do not use it for virtual or purely logical objects (e.g., software, user accounts, roles).

Examples:
- Building: location appropriate → isLocationSource: true
- Room: location appropriate → isLocationSource: true
- Server rack: location appropriate → isLocationSource: true
- Server: location appropriate → isLocationSource: false
- User account: no location, no isLocationSource

Your response must be a structured JSON proposal only - no function calls.
The user will review and extend the structure.
Do not output any explanatory text or comments.

Rules:
- No greetings, explanations, or comments.
- Object type names: Singular, factual, in English.
- Section names: In English, descriptive.
- Attribute names: In English, technically clear (e.g., serialNumber, ipAddress).
- Use relation only when the attribute refers to another object type.
- Each object type should have at least 1-3 additional sections (excluding Information). Each section should contain
  2-6 attributes, except Global Sections which always include only their predefined attributes.


Return your answer as **only** valid JSON.
Do not include any explanations, text, or markdown code fences.
Do not include triple backticks.
Return the result as a single valid JSON object.
Do NOT wrap the object in an array.
Do NOT include any extra keys other than the ones requested.
The JSON must be directly parsable by Python's json.loads().
Your output should start with { and end with }.
The JSON object must contain ONLY the properties of the modeled object directly at the root level.
"""
