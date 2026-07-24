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
Per-object normalization and validation for the object import workflows

Applied to each generated object before it is imported: forces the server-owned lifecycle fields,
derives ``special_type`` from the target type, defaults the optional fields and validates ``active``.
Returns a list of human-readable error strings (empty when the object is valid) so the caller can
report a rejected object without aborting the whole import.
"""
from typing import Any
from datetime import datetime, timezone

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.importer.importer_constants import DEFAULT_OBJECT_VERSION
# -------------------------------------------------------------------------------------------------------------------- #

# Accepted string spellings for a boolean import value (compared case-insensitively, stripped)
_TRUTHY_IMPORT_VALUES: frozenset[str] = frozenset({'true', 'yes', '1'})
_FALSY_IMPORT_VALUES: frozenset[str] = frozenset({'false', 'no', '0'})


def parse_import_bool(value: Any) -> bool | None:
    """
    Parses a boolean value as accepted by the object import

    Accepts real booleans, the integers ``1``/``0``, and (case-insensitive, whitespace-tolerant)
    the strings ``true``/``yes``/``1`` and ``false``/``no``/``0``. Any other value is rejected.

    Args:
        value (Any): The value to parse

    Returns:
        bool | None: The parsed boolean, or None if the value is not an accepted boolean
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, int):  # bool is handled above, so this is a plain int (e.g. 1 / 0)
        if value == 1:
            return True
        if value == 0:
            return False
        return None

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in _TRUTHY_IMPORT_VALUES:
            return True
        if normalized in _FALSY_IMPORT_VALUES:
            return False

    return None


def normalize_and_validate_object(working_object: dict, special_type: SpecialType | None) -> list[str]:
    """
    Normalizes an imported object's schema fields in place and validates the ones with rules

    Forces the server-owned fields (``version``, ``creation_time``, ``last_edit_time``, ``editor_id``)
    regardless of any provided value, derives ``special_type`` from the target type (user input
    ignored), defaults ``ci_explorer_tooltip`` and ``active`` when absent, and validates ``active``.

    Args:
        working_object (dict): The generated object to normalize (mutated in place)
        special_type (SpecialType | None): The target type's special type (assigned to the object)

    Returns:
        list[str]: The validation errors; an empty list means the object is valid
    """
    errors: list[str] = []

    # Server-owned lifecycle fields are always forced, ignoring any provided value
    working_object[CmdbObjectKey.VERSION.value] = DEFAULT_OBJECT_VERSION
    working_object[CmdbObjectKey.CREATION_TIME.value] = datetime.now(timezone.utc)
    working_object[CmdbObjectKey.LAST_EDIT_TIME.value] = None
    working_object[CmdbObjectKey.EDITOR_ID.value] = None

    # special_type mirrors the target type; a provided value is ignored
    working_object[CmdbObjectKey.SPECIAL_TYPE.value] = special_type

    # Optional fields default when absent, otherwise keep the provided value
    working_object.setdefault(CmdbObjectKey.CI_EXPLORER_TOOLTIP.value, None)

    _validate_active(working_object, errors)

    return errors


def _validate_active(working_object: dict, errors: list[str]) -> None:
    """
    Defaults / validates the ``active`` flag of an imported object (mutates the object / errors list)

    An absent or empty value defaults to True; any other value must parse as a boolean via
    ``parse_import_bool`` - if it does not, an error is appended and the object is left unchanged.

    Args:
        working_object (dict): The object being validated (its ``active`` value may be replaced)
        errors (list[str]): The error accumulator to append to on an invalid value
    """
    active_value = working_object.get(CmdbObjectKey.ACTIVE.value)

    if active_value is None or active_value == '':
        working_object[CmdbObjectKey.ACTIVE.value] = True
        return

    parsed = parse_import_bool(active_value)

    if parsed is None:
        errors.append(f"Invalid value for 'active': {active_value!r}")
    else:
        working_object[CmdbObjectKey.ACTIVE.value] = parsed
