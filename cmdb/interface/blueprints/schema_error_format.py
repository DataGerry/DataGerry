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
Turns a Cerberus error tree into the reason a refused request body is answered with

Cerberus reports errors as a tree: a field maps to a list of messages, and a nested document or list
item maps to a further dict keyed by field name or item index. ``flatten_schema_errors`` walks it into
one ``path: reason`` line per failure, with list items written ``field[1]`` and nested fields
``field.child``; ``describe_schema_errors`` bounds and joins those lines into the text of the 400
"""
from typing import Any

from cmdb.interface.blueprints.api_blueprint_constants import (
    ERRORS_SEPARATOR,
    FIELD_ERROR_SEPARATOR,
    INVALID_BODY_MESSAGE,
    MAX_REPORTED_SCHEMA_ERRORS,
)
# -------------------------------------------------------------------------------------------------------------------- #

def _child_path(path: str, key: Any) -> str:
    """
    Appends one step to an error path

    Args:
        path (str): The path so far; empty at the top level
        key (Any): A field name, or the integer index of a list item

    Returns:
        str: ``field.child`` for a name, ``field[1]`` for an index
    """
    if isinstance(key, int):
        return f'{path}[{key}]'

    return f'{path}.{key}' if path else str(key)


def flatten_schema_errors(errors: dict[Any, Any], path: str = '') -> list[str]:
    """
    Walks a Cerberus error tree into one ``path: reason`` line per failure, in field order

    Args:
        errors (dict[Any, Any]): ``Validator.errors``, or a subtree of it
        path (str): The path of the subtree; empty at the top level

    Returns:
        list[str]: One line per failing rule
    """
    lines: list[str] = []

    for key in sorted(errors, key=str):
        key_path: str = _child_path(path, key)

        for entry in errors[key]:
            if isinstance(entry, dict):
                lines.extend(flatten_schema_errors(entry, key_path))
            else:
                lines.append(f'{key_path}{FIELD_ERROR_SEPARATOR}{entry}')

    return lines


def describe_schema_errors(errors: dict[Any, Any]) -> str:
    """
    Builds the message a request body refused by its schema is answered with

    Names each failing field and why, up to ``MAX_REPORTED_SCHEMA_ERRORS``, and says how many more
    there are beyond that. An empty tree still answers the lead text

    Args:
        errors (dict[Any, Any]): ``Validator.errors``

    Returns:
        str: ``Invalid data provided: field: reason; ...``
    """
    lines: list[str] = flatten_schema_errors(errors)

    if not lines:
        return f'{INVALID_BODY_MESSAGE}!'

    reported: list[str] = lines[:MAX_REPORTED_SCHEMA_ERRORS]
    hidden: int = len(lines) - len(reported)
    text: str = ERRORS_SEPARATOR.join(reported)

    if hidden:
        text = f'{text}{ERRORS_SEPARATOR}and {hidden} more'

    return f'{INVALID_BODY_MESSAGE}{FIELD_ERROR_SEPARATOR}{text}'
