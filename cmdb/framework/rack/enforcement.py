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
Un-bypassable Rack invariants on the CmdbObject write path

The frontend form honours a field's `required` marker, but an API client does not, and no field type
expresses "positive whole number" - so the Rack rules are enforced here, on the same dict both object
write paths persist from. Mirrors cmdb.framework.ipam.enforcement in shape; the merged entry point
that runs this next to the IPAM invariants is cmdb.framework.object_invariants
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import TypesManager

from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey

from cmdb.utils import ValidationErrorKey, build_error

from cmdb.framework.rack.rack_constants import ABORT_PREFIX
from cmdb.framework.rack.rack_validator import coerce_rack_height, validate_rack_object
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def format_rack_errors_for_abort(errors: list[dict[str, Any]]) -> str:
    """
    Joins structured Rack validation errors into one string suitable for Flask's abort(400, ...)

    Rack-specific counterpart of the IPAM formatter, so a Rack problem is not reported to the user
    under the IPAM feature's name

    Args:
        errors (list[dict[str, Any]]): The accumulated validator errors

    Returns:
        str: 'Rack validation failed: <msg1> | <msg2> | ...'
    """
    joined: str = " | ".join(
        error.get(ValidationErrorKey.MESSAGE, 'unknown error')
        for error in errors
    )

    return f"{ABORT_PREFIX}: {joined}"


def is_rack_object(types_manager: TypesManager, candidate_object: dict[str, Any]) -> bool:
    """
    Reports whether a candidate CmdbObject belongs to the Rack SpecialType

    Resolved through the stored CmdbType rather than the object's own 'special_type' key, because that
    key is server-owned and a candidate coming straight off a request may not carry it yet

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        bool: True when the object's CmdbType carries the RACK marker
    """
    type_id: Any = candidate_object.get(CmdbObjectKey.TYPE_ID)

    if not isinstance(type_id, int):
        return False

    type_doc: dict[str, Any] | None = types_manager.get_type(type_id)

    if not type_doc:
        return False

    return type_doc.get(TypeSchemaKey.SPECIAL_TYPE) == SpecialType.RACK


def normalize_rack_object(candidate_object: dict[str, Any]) -> None:
    """
    Canonicalises a Rack candidate's height in place so the stored value is always an int

    A client may send the height as '42' (CSV import has no other way) or 42.0 (JSON), and both write
    paths persist from this same dict - so without this the same rack height would be stored as three
    different types depending on who wrote it. A value that is not a whole number is left untouched
    for the validators to reject

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document, mutated in place
    """
    height: Any = extract_field_value(candidate_object, RackField.HEIGHT)

    if height is None or height == '':
        return

    coerced: int | None = coerce_rack_height(height)

    # No "already equal" short-circuit: 42 == 42.0 is True in Python, so comparing values would skip
    # exactly the float-to-int rewrite this exists for. The assignment is idempotent instead
    if coerced is None:
        return

    # Every matching entry is rewritten rather than only the first: a document carrying the field
    # twice is a data-integrity problem, but canonicalising just one of them would hide it behind an
    # inconsistency instead
    for field in candidate_object.get(CmdbObjectKey.FIELDS) or []:
        if field.get(CmdbObjectFieldKey.NAME) == RackField.HEIGHT:
            field[CmdbObjectFieldKey.VALUE.value] = coerced


def enforce_rack_object_invariants(
        types_manager: TypesManager,
        candidate_object: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Runs every Rack validator that applies to the candidate and returns the structured error list

    A no-op for any object that is not a Rack. For a Rack the height is canonicalised in place first
    (see normalize_rack_object), so a valid candidate is persisted with an int height. Caller is
    expected to abort 400 with format_rack_errors_for_abort(errors) when the list is non-empty

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when the candidate is valid
    """
    if not is_rack_object(types_manager, candidate_object):
        return []

    normalize_rack_object(candidate_object)

    return [build_error(message) for message in validate_rack_object(candidate_object)]
