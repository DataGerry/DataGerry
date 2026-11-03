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
The Cerberus rule of a field holding a public_id

A public_id is a whole number from 1. Cerberus' ``integer`` type alone lets through 0, negative numbers and - since
Python counts ``True`` / ``False`` as 1 / 0 - a JSON boolean, which would be stored as ``true`` in an id field. Every
schema that names another document by its id declares the field with ``get_id_rule`` instead
"""
from typing import Any, Callable

from cmdb.class_schema.class_schema_constants import ID_IS_NO_BOOLEAN_MSG
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['check_no_boolean', 'get_id_rule']

# The smallest public_id a document can carry
MIN_PUBLIC_ID: int = 1


def check_no_boolean(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Cerberus ``check_with`` rule refusing a JSON boolean where an id belongs

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    if isinstance(value, bool):
        error(field, ID_IS_NO_BOOLEAN_MSG)


def get_id_rule(required: bool = True, nullable: bool = False) -> dict[str, Any]:
    """
    Builds the Cerberus rule of a field holding one public_id: an integer from 1, never a boolean

    Also the item rule of a list of ids (``{'type': 'list', 'schema': get_id_rule()}``). A new dict on every call

    Args:
        required (bool): Whether the field must be present. Defaults to True
        nullable (bool): Whether it may be null - an optional reference. Defaults to False

    Returns:
        dict[str, Any]: The Cerberus rule
    """
    return {
        'type': 'integer',
        'min': MIN_PUBLIC_ID,
        'check_with': check_no_boolean,
        'required': required,
        'nullable': nullable,
    }
