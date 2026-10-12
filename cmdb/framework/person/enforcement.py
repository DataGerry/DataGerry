# DATAGERRY - OpenSource Enterprise CMDB
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
Un-bypassable person field invariants on the CmdbObject write path

A person field (FieldType.PERSON) stores ``{'ref_type', 'id'}`` pairs. The frontend only offers the objects
the field allows, an API client is not held to that - so every person value is canonicalised and judged here,
on the same dict both object write paths persist from: its shape, the kinds the field's 'person_ref_kind'
allows, and that every id names an existing object of the SpecialType its 'ref_type' claims. Mirrors
cmdb.framework.rack.enforcement in shape; the merged entry point is cmdb.framework.object_invariants
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.utils import ValidationErrorKey, build_error

from cmdb.framework.person.directory import resolve_person_kinds
from cmdb.framework.person.person_values import (
    get_person_field_definitions,
    iter_person_entries,
    normalize_person_value,
    person_value_errors,
    referenced_ids,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ABORT_PREFIX: str = 'Person validation failed'


def format_person_errors_for_abort(errors: list[dict[str, Any]]) -> str:
    """
    Joins structured person validation errors into one string suitable for Flask's abort(400, ...)

    Args:
        errors (list[dict[str, Any]]): The accumulated validator errors

    Returns:
        str: 'Person validation failed: <msg1> | <msg2> | ...'
    """
    joined: str = " | ".join(
        error.get(ValidationErrorKey.MESSAGE, 'unknown error')
        for error in errors
    )

    return f"{ABORT_PREFIX}: {joined}"


def enforce_person_object_invariants(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        candidate_object: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Canonicalises every person value of the candidate in place and returns the structured error list

    A no-op for an object whose CmdbType has no person field. The shape is judged first; the ids are only
    resolved - one query for all of them - when every value has a valid shape

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document, mutated in place

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when the candidate is valid
    """
    type_id: Any = candidate_object.get(CmdbObjectKey.TYPE_ID)

    if not isinstance(type_id, int):
        return []

    type_doc: dict[str, Any] | None = types_manager.get_type(type_id)

    if not type_doc:
        return []

    person_fields: dict[str, dict[str, Any]] = get_person_field_definitions(type_doc.get(TypeSchemaKey.FIELDS.value))

    if not person_fields:
        return []

    messages: list[str] = []
    references: list[tuple[str, str, int]] = []

    for entry, definition in iter_person_entries(candidate_object, person_fields):
        field_name: str = definition[FieldKey.NAME.value]
        value: Any = normalize_person_value(
            entry.get(CmdbObjectFieldKey.VALUE.value), bool(definition.get(FieldKey.MULTIPLE.value)),
        )
        entry[CmdbObjectFieldKey.VALUE.value] = value
        # Stamped server-side: the delete cascade finds person values by this row type, so it must not
        # depend on the client having sent it
        entry[CmdbObjectFieldKey.TYPE.value] = FieldType.PERSON.value

        shape_errors: list[str] = person_value_errors(field_name, value, definition)
        messages.extend(shape_errors)

        if not shape_errors:
            references.extend((field_name, ref_type, object_id) for ref_type, object_id in referenced_ids(value))

    if not messages and references:
        kinds: dict[int, str] = resolve_person_kinds(
            objects_manager, types_manager, (object_id for _, _, object_id in references),
        )

        messages.extend(
            f"The person field '{field_name}' references {ref_type} {object_id}, which does not exist"
            for field_name, ref_type, object_id in references
            if kinds.get(object_id) != ref_type
        )

    return [build_error(message) for message in messages]
