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
input so the route handlers can stay focused on orchestration.

**These helpers are the only validation the write routes have.** ``CmdbSectionTemplate.SCHEMA``
describes the document, not the request - the payload arrives as text, with ``fields`` JSON-encoded -
and nothing below the route consults it either: the manager builds the model and inserts its
``__dict__``. So what is checked here is what is true of a stored template
"""
import json
from typing import Any

from flask import abort

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import (
    SECTION_TEMPLATE_TEXT_MAX_LENGTH,
    SECTION_TEMPLATE_WRITE_KEYS,
    SectionTemplateKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.utils import str_to_bool
# -------------------------------------------------------------------------------------------------------------------- #


def strip_unknown_template_keys(params: dict[str, Any]) -> dict[str, Any]:
    """
    Keeps only the client-settable keys of a section-template write payload

    Everything outside ``SECTION_TEMPLATE_WRITE_KEYS`` is dropped instead of rejected, mirroring the
    ``purge_unknown`` behaviour of the Cerberus-validated write routes.

    **Dropping it is the point, not tidiness.** ``CmdbSectionTemplate.__init__`` takes ``**kwargs``
    and the manager inserts the instance's ``__dict__``, so any extra request parameter becomes a
    stored document key that the model's own SCHEMA does not declare - and ``to_json`` drops it on the
    way out, so it is invisible to every reader while surviving each later edit

    Args:
        params (dict[str, Any]): The raw request parameters

    Returns:
        dict[str, Any]: A new dict holding only the whitelisted keys
    """
    return {key: value for key, value in params.items() if key in SECTION_TEMPLATE_WRITE_KEYS}


def require_text(raw: Any, param_name: str) -> str:
    """
    Aborts 400 when a text parameter is blank or unusably long

    ``name`` and ``label`` are what a template is identified and rendered by, and the name is also the
    **propagation key** consuming types reference it by - and immutable once stored, so a blank one
    can never be repaired, only deleted. A length cap keeps a name that no UI can render out of that
    position in the first place

    Args:
        raw (Any): The raw parameter value
        param_name (str): The parameter's name, for the refusal message

    Raises:
        HTTPException: 400 when the value is not a non-blank string within the length cap

    Returns:
        str: The value, unchanged
    """
    if not isinstance(raw, str) or not raw.strip():
        abort(400, f"The '{param_name}' of a Section Template must not be empty!")

    if len(raw) > SECTION_TEMPLATE_TEXT_MAX_LENGTH:
        abort(400, f"The '{param_name}' of a Section Template must be at most "
                   f"{SECTION_TEMPLATE_TEXT_MAX_LENGTH} characters!")

    return raw


def guard_template_fields(fields: list[dict[str, Any]]) -> None:
    """
    Aborts 400 when a field entry could not be used as a CmdbType field

    A template's fields are **inlined into every consuming CmdbType**, so an entry that is not a
    usable field definition becomes an unusable field on every one of them - past the type write
    routes, which is where such a shape would otherwise be refused. The three rules are the ones the
    type import applies to an uploaded field (``validate_type_structure``), plus uniqueness, which the
    type structure guard enforces on the other side of the propagation:

      - a non-blank ``name`` - it is the field's identifier, and an Object keys its value by it
      - a non-blank ``label`` - it is what the field is rendered as on every form and table
      - a known ``FieldType`` - the kind decides how the field is rendered and stored
      - names unique within the template - two fields sharing one name make every read of that name
        ambiguous, and the type they are inlined into would be refused for it

    Args:
        fields (list[dict[str, Any]]): The parsed field list

    Raises:
        HTTPException: 400 naming the first rule a field entry breaks
    """
    seen: set[str] = set()

    for field in fields:
        name: Any = field.get(FieldKey.NAME.value)
        label: Any = field.get(FieldKey.LABEL.value)
        field_type: Any = field.get(FieldKey.TYPE.value)

        if not isinstance(name, str) or not name.strip():
            abort(400, "Every field of a Section Template needs a name!")

        if not isinstance(label, str) or not label.strip():
            abort(400, f"The field '{name}' of a Section Template needs a label!")

        if not FieldType.is_valid(field_type):
            abort(400, f"The field '{name}' of a Section Template declares the unknown type "
                       f"'{field_type}'!")

        if name in seen:
            abort(400, f"A field name has to be unique within a Section Template. Used more than "
                       f"once: {name}!")

        seen.add(name)


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
