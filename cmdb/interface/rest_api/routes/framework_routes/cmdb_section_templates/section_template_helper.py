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
Helper methods for CmdbSectionTemplate routes

Request-payload validation and coercion helpers shared by the CmdbSectionTemplate CRUD routes, plus
the guard the update route applies to a stored template. Each helper aborts with HTTP 400 on malformed
input so the route handlers can stay focused on orchestration
"""
import json
from typing import Any

from flask import abort

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.utils.helpers import str_to_bool
# -------------------------------------------------------------------------------------------------------------------- #


def require_params(params: dict[str, Any], keys: list[str]) -> None:
    """
    Aborts 400 when any of the required request parameters is missing

    Args:
        params (dict[str, Any]): The parsed request parameters
        keys (list[str]): The parameter names that must be present
    """
    missing: list[str] = [key for key in keys if key not in params]

    if missing:
        abort(400, f"Missing required parameter(s): {', '.join(missing)}")


def parse_json_fields(raw: Any) -> list[dict[str, Any]]:
    """
    Parses the JSON-encoded 'fields' parameter, aborting 400 on malformed input

    The shape is checked, not only the syntax: the value has to be a list of field objects, because
    that is what the template stores and what the propagation diffing walks. A bare JSON value such as
    ``"5"`` used to parse cleanly and be stored as the field list

    Args:
        raw (Any): The raw 'fields' parameter value (a JSON string)

    Returns:
        list[dict[str, Any]]: The decoded field list
    """
    try:
        fields: Any = json.loads(raw)
    except (TypeError, ValueError):
        abort(400, "The 'fields' parameter must be a valid JSON string!")

    if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
        abort(400, "The 'fields' parameter must be a JSON list of field objects!")

    return fields


def coerce_bool(raw: Any) -> bool:
    """
    Coerces a request parameter to a bool, aborting 400 on an unrecognised value

    Args:
        raw (Any): The raw parameter value ('true' / 'false' or a native bool)

    Returns:
        bool: The coerced boolean
    """
    try:
        return str_to_bool(raw)
    except ValueError:
        abort(400, "Boolean parameters must be 'true' or 'false'!")


def coerce_public_id(raw: Any) -> int:
    """
    Coerces the 'public_id' parameter to an int, aborting 400 when it is not numeric

    Args:
        raw (Any): The raw 'public_id' parameter value

    Returns:
        int: The integer public_id
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        abort(400, "The 'public_id' parameter must be an integer!")


def guard_section_template_update(current_template: CmdbSectionTemplate, params: dict[str, Any]) -> None:
    """
    Refuses an update that would change what a CmdbSectionTemplate is not allowed to change

    Three properties are immutable, for three different reasons:

      - **predefined**: a predefined template is DataGerry-provided and propagated by the seeding code,
        so this route may neither edit one nor turn a template into one (or out of one)
      - **type**: section and multi-data section are different shapes; a consuming type has the section
        inlined, so switching would leave every consumer holding the wrong kind
      - **name**: the name IS the propagation key. Consuming types reference the template by name
        (``global_template_ids``, ``get_types_using_template``), so a rename would silently orphan every
        one of them - the template would exist under its new name while the types keep the old one

    Args:
        current_template (CmdbSectionTemplate): The stored template being updated
        params (dict[str, Any]): The normalised request payload

    Raises:
        HTTPException: 400 when the template is predefined or an immutable property would change
    """
    if current_template.predefined:
        abort(400, "A predefined SectionTemplate is not editable!")

    if current_template.predefined != params[SectionTemplateKey.PREDEFINED]:
        abort(400, "The 'predefined' property of a Section Template is not changable!")

    if current_template.type != params[SectionTemplateKey.TYPE]:
        abort(400, "The 'type' of a Section Template is not changable!")

    if current_template.name != params[SectionTemplateKey.NAME]:
        abort(400, "The 'name' of a Section Template is not changable - it is what consuming types "
                   "reference it by!")
