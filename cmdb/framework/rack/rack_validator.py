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
The field rules of a Rack CmdbObject

Stateless (no database access): a Rack is judged by its own two governed fields. The rules exist
because a Rack may not depend on the type's own `required` markers - those live on a CmdbType a user
can edit, and clearing one may not turn a Rack into a nameless, heightless object - and because no
field type expresses "positive whole number".

They are split in two sets so each caller runs only what its own pipeline does not already do:

  - validate_rack_required_values: the field is there and carries a value. Run by the object REST
    routes as the flag-independent safety net under their generic required-field check
    (cmdb.framework.object_required_fields), which only enforces what the type declares
  - validate_rack_field_values: the value that IS there is usable. Run by both the REST routes and
    the bulk importer (whose generic pipeline covers presence but accepts 0, -1 and 3.5 as numbers)

Both return plain message strings; enforcement wraps them into the structured error dicts the REST
write path reports, while the importer appends them to its own list[str] report
"""
from typing import Any

from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.utils import coerce_whole_number
from cmdb.framework.rack.rack_constants import RackLimits, RackValidationError
# -------------------------------------------------------------------------------------------------------------------- #


def _is_value_absent(value: Any) -> bool:
    """
    Reports whether a field value counts as "no value at all"

    Only None and the empty string are absent; 0 is a present (if invalid) height, which is why it is
    rejected by the value rules rather than the presence rules

    Args:
        value (Any): The field value to test

    Returns:
        bool: True when the value is None or an empty string
    """
    return value is None or value == ''


def coerce_rack_height(value: Any) -> int | None:
    """
    Coerces a Rack height to a whole number, or returns None when it is not one

    A Rack height is a U count, so it shares the generic whole-number rules: 42, 42.0 and '42' are all
    the same height, 3.5 is not one at all. Kept as a named alias rather than calling the utility
    directly so the domain reads as the domain

    Args:
        value (Any): The raw height field value

    Returns:
        int | None: The height as an int, or None when the value is not a whole number
    """
    return coerce_whole_number(value)


def validate_rack_required_values(candidate_object: dict[str, Any]) -> list[str]:
    """
    Checks the Rack's two required fields actually carry a value

    Separate from validate_rack_field_values so the bulk importer can skip it: its generic pipeline
    already rejects a missing required value, and running both would report the same problem twice

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[str]: The messages for the absent fields; empty when both carry a value
    """
    errors: list[str] = []

    if _is_value_absent(extract_field_value(candidate_object, RackField.NAME)):
        errors.append(RackValidationError.MISSING_NAME.value)

    if _is_value_absent(extract_field_value(candidate_object, RackField.HEIGHT)):
        errors.append(RackValidationError.MISSING_HEIGHT.value)

    return errors


def validate_rack_field_values(candidate_object: dict[str, Any]) -> list[str]:
    """
    Checks the values the Rack's governed fields DO carry are usable

    An absent value is not this function's concern (see validate_rack_required_values), so a Rackname
    of None passes here while a Rackname of '   ' does not, and a missing height passes while 0, -4
    and 3.5 do not

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[str]: The messages for the unusable values; empty when every present value is valid
    """
    errors: list[str] = []

    name: Any = extract_field_value(candidate_object, RackField.NAME)

    if not _is_value_absent(name) and not str(name).strip():
        errors.append(RackValidationError.BLANK_NAME.value)

    height: Any = extract_field_value(candidate_object, RackField.HEIGHT)

    if not _is_value_absent(height):
        coerced: int | None = coerce_rack_height(height)

        if coerced is None:
            errors.append(RackValidationError.INVALID_HEIGHT.format(value=height))
        elif coerced < RackLimits.MIN_HEIGHT:
            errors.append(
                RackValidationError.NON_POSITIVE_HEIGHT.format(minimum=RackLimits.MIN_HEIGHT, value=coerced)
            )

    return errors


def validate_rack_object(candidate_object: dict[str, Any]) -> list[str]:
    """
    Runs every Rack field rule - presence first, then value quality

    The entry point for callers that own the whole validation of a Rack candidate (the object REST
    write paths). The importer calls the two sets separately

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[str]: Accumulated messages; empty when the candidate is a valid Rack
    """
    return validate_rack_required_values(candidate_object) + validate_rack_field_values(candidate_object)
