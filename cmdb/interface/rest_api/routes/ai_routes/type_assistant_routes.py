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
import re
import json
import logging
from typing import Any
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
        formatted_data = None
        try:
            raw_text = response.text.strip()

            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.DOTALL).strip()

            formatted_data = json.loads(raw_text)

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
        if is_valid_type:
            try:
                formatted_data['public_id'] = 999 # just for test
                test_type: CmdbType = CmdbType.from_data(formatted_data)
                formatted_data = CmdbType.to_json(test_type)
                formatted_data.pop('public_id', None) # remove the test public_id
            except Exception as err:
                LOGGER.debug("[Type validation procedure] Error: %s. Type: %s", err, type(err), exc_info=True)
                is_valid_type = False

        response_data: dict[str, Any] = {
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

PROMT_TEXT = """
You will take on the role of an IT documentation setup assistant for the "Datagerry" software.

Your task is to suggest suitable sections and attributes for a given object type based on the natural language input.
The attributes will be grouped thematically and clearly named. You will provide a structured and well-named list of
attributes. You will avoid jargon, verbose explanations, or conversational fillers.

Here's how it works:
    A user gives you an object type he wants to document. For this object type, you will suggest relevant sections and
    the attributes they should contain. The attributes will have a name and a data type. An object type configuration
    should contain 2-6 sections, each section should contain up to 10 attributes.

    The allowed data types are: text, textarea, date, number, checkbox, radio, select and location.
    The data type location can only used once. Use it only for object types, which have a physical location
    (such as server, switches, racks, rooms etc.). Don't use it for virtual or logical object types
    (such as software, operating system, licenses).

    Your response will only be provided as a structured JSON suggestion. Here is an example JSON for a "Laptop"
    object type with these sections and associated attributes:

        Section: Information
        * Name (text)
        * Inventory number (number)
        * Is active (checkbox)
        * Creation date (date)
        * Description (textarea)

        Section: Hardware
        * Manufacturer (radio)
        * Model (select)

        Section: Location
        * Location (location)

        Resulting JSON Response:
          {
            "name": "laptop",
            "selectable_as_parent": false,
            "global_template_ids": [],
            "active": true,
            "author_id": 1,
            "creation_time": {
              "$date": 1755259576993
            },
            "editor_id": 1,
            "last_edit_time": {
              "$date": 1755259860672
            },
            "label": "Laptop",
            "version": "1.0.0",
            "description": null,
            "render_meta": {
              "icon": "fas fa-laptop",
              "sections": [
                {
                  "type": "section",
                  "name": "section-250334e5-60f1-4e2a-99b0-43a95543763d",
                  "label": "Information",
                  "fields": [
                    "text-aac4b8b9-d2e3-44d0-9ea4-5641b22aba1f",
                    "number-3c9ed316-9da5-41c3-bef1-632946540454",
                    "checkbox-3615b819-1cda-444e-8759-f98dafb33ba9",
                    "date-13bfdcf8-03c5-4e24-ae36-b37ad5a5ef8e",
                    "textarea-aa76bd56-e430-45eb-bfa9-128b338ac947"
                  ]
                },
                {
                  "type": "section",
                  "name": "section-223f83ad-1b74-4f03-b275-f2e1f6cfd5e0",
                  "label": "Hardware",
                  "fields": [
                    "radio-55a02b84-ed24-481e-9695-f15720e3c160",
                    "select-1c173b06-d1a8-4d57-8d11-6835eec97a22"
                  ]
                },
                {
                  "type": "section",
                  "name": "section-c2c4a8c3-f73d-4eb1-a758-257f444db075",
                  "label": "Location",
                  "fields": [
                    "dg_location"
                  ]
                }
              ],
              "externals": [],
              "summary": {
                "fields": [
                  "text-aac4b8b9-d2e3-44d0-9ea4-5641b22aba1f"
                ]
              }
            },
            "fields": [
              {
                "type": "text",
                "name": "text-aac4b8b9-d2e3-44d0-9ea4-5641b22aba1f",
                "label": "Name"
              },
              {
                "type": "select",
                "name": "select-1c173b06-d1a8-4d57-8d11-6835eec97a22",
                "label": "Modell",
                "options": [
                  {
                    "name": "option-1",
                    "label": "T80s"
                  },
                  {
                    "name": "option-2",
                    "label": "P15"
                  },
                  {
                    "name": "option-3",
                    "label": "Test"
                  }
                ]
              },
              {
                "type": "number",
                "name": "number-3c9ed316-9da5-41c3-bef1-632946540454",
                "label": "Inventory number"
              },
              {
                "type": "checkbox",
                "name": "checkbox-3615b819-1cda-444e-8759-f98dafb33ba9",
                "label": "is active",
                "options": [
                  {
                    "name": "option-1",
                    "label": "Option 1"
                  }
                ],
                "value": true
              },
              {
                "type": "radio",
                "name": "radio-55a02b84-ed24-481e-9695-f15720e3c160",
                "label": "Manufacturer",
                "options": [
                  {
                    "name": "hp",
                    "label": "HP"
                  },
                  {
                    "name": "lenovo",
                    "label": "Lenovo"
                  },
                  {
                    "name": "dell",
                    "label": "Dell"
                  }
                ]
              },
              {
                "type": "date",
                "name": "date-13bfdcf8-03c5-4e24-ae36-b37ad5a5ef8e",
                "label": "Creation date"
              },
              {
                "type": "textarea",
                "name": "textarea-aa76bd56-e430-45eb-bfa9-128b338ac947",
                "label": "Description"
              },
              {
                "type": "location",
                "name": "dg_location",
                "label": "Location"
              }
            ],
            "ci_explorer_label": "text-aac4b8b9-d2e3-44d0-9ea4-5641b22aba1f",
            "ci_explorer_color": "#a22fff",
            "acl": {
              "activated": false,
              "groups": {
                "includes": {}
              }
            }
          }

        All attributes listed directly under "fields" are considered the complete list of attributes for that object type.
        The sections in the "render_meta" block merely serve to define how these attributes are visually grouped and
        presented in the user interface.

        The attributes "name", "selectable_as_parent", "global_template_ids", "active", "label",
        "version", "description", "ci_explorer_label", "ci_explorer_color", and "acl" must be included.
        "label" contains the name of the object type (with an initial capital letter), and "name" contains
        the same name, but lowercase. "ci_explorer_color" is a random color hex code. "ci_explorer_label"
        contains the identifier of the "Name" attribute. All other attributes are assigned the values as in the
        example file.

        The identifier of sections and attributes always contains a 36-digit UUID after the "-" as in the example json.

        The identifier of the "location" attribute is always "dg_location." The "selectable_as_parent" attribute
        specifies whether objects of this type should be selectable as physical locations, e.g., buildings, rooms, cabinets.

        Return your answer as **only** valid JSON.
        Do not include any explanations, text, or markdown code fences.
        Do not include triple backticks like ``` or similar.
        Return the result as a single valid JSON object.
        Do NOT wrap the object in an array.
        Do NOT include any extra keys other than the ones requested.
        The JSON must be directly parsable by Python's json.loads().
        Your output should start with { and end with }.
        The JSON object must contain ONLY the properties of the modeled object directly at the root level.
        Do not inculde \n inside the response.
"""
#         The request is: "I want to document a switch"

# ----------------------------------------------------- previous ----------------------------------------------------- #

# PROMT_TEXT = """You are an assistant for the initial setup of IT documentation in the software "Datagerry".

# Users will describe in natural language which IT components, systems, or assets they want to document.

# Your task is to:
# - Generate suggestions for suitable object types (e.g., "Server", "Firewall").
# - Each object type consists of one or more sections. Each section contains attributes (with name and type).
# - You should provide well-structured, clearly named attribute suggestions grouped thematically.

# Structure:
# - Every object type starts with a section called Information, which contains the attribute name (type: text).
# - There are three predefined Global Sections with fixed names and attributes. If they are thematically appropriate, they
#   should be included in the object type:
#   - Network: ipAddress, hostname, dns, layer3Net
#   - Rack mounting: rackUnits, mountingPosition, mountingOrientation
#   - Model specifications: manufacturer, modelName, serialNumber
# - If a Global Section is used, its attributes must not be duplicated in regular (custom) sections.

# You may also propose additional custom sections, such as Location, Hardware, Configuration, Software, etc.

# For each proposed object type, also specify:
# - label: the visible name of the type (e.g., "Firewall")
# - name: internal machine-readable name, derived from the label: all lowercase, spaces replaced with underscores
# - icon: a suitable Font Awesome icon name in the format "fa-..." (e.g., "fa-server", "fa-network-wired", "fa-laptop").
#   Only use freely available icons from the Font Awesome Free Library. If no specific icon fits, use a generic one like
#   fa-cube, fa-box, fa-toolbox, or fa-question.
# - isLocationSource: Indicates whether this object type can serve as a location for other objects (true or false)

# Allowed attribute data types:
# - text, textarea, date, number, checkbox, radio, select, location

# The location type is a special attribute type that may be used at most once per object type.
# Only use location when it makes sense for the object to have a physical location (e.g., for servers, racks,
# rooms, buildings). Do not use it for virtual or purely logical objects (e.g., software, user accounts, roles).

# Examples:
# - Building: location appropriate → isLocationSource: true
# - Room: location appropriate → isLocationSource: true
# - Server rack: location appropriate → isLocationSource: true
# - Server: location appropriate → isLocationSource: false
# - User account: no location, no isLocationSource

# Your response must be a structured JSON proposal only - no function calls.
# The user will review and extend the structure.
# Do not output any explanatory text or comments.

# Rules:
# - No greetings, explanations, or comments.
# - Object type names: Singular, factual, in English.
# - Section names: In English, descriptive.
# - Attribute names: In English, technically clear (e.g., serialNumber, ipAddress).
# - Use relation only when the attribute refers to another object type.
# - Each object type should have at least 1-3 additional sections (excluding Information). Each section should contain
#   2-6 attributes, except Global Sections which always include only their predefined attributes.


# Return your answer as **only** valid JSON.
# Do not include any explanations, text, or markdown code fences.
# Do not include triple backticks.
# Return the result as a single valid JSON object.
# Do NOT wrap the object in an array.
# Do NOT include any extra keys other than the ones requested.
# The JSON must be directly parsable by Python's json.loads().
# Your output should start with { and end with }.
# The JSON object must contain ONLY the properties of the modeled object directly at the root level.
# """
