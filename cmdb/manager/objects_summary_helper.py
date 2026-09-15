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
The one-line summary a CmdbObject is shown as

Every list, picker and reference in the product identifies an object by this line, so its shape is a
user-facing contract: `Type label #public_id - field | field | field`, with the configured summary
fields in declaration order.

**Pure composition over already-loaded data**, which is why it lives beside the manager rather than in
it: `get_summary_line` reads one object and its type, `get_summary_lines_lookup` reads many in two bulk
queries, and both compose the result here - so the single and the batch path cannot drift into
producing different text for the same object.
"""
from logging import Logger, getLogger
from typing import Any

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def compose_summary_line(
    target_object: dict[str, Any],
    target_object_type: Any,
    with_type: bool = True,
) -> str:
    """
    Composes the summary line for a CmdbObject that has already been loaded

    Pure composition over already-loaded data: the object as a dict and its CmdbType
    instance. The 'type label + public_id' prefix is built first, then the configured
    summary fields are appended in declaration order (separator '-' before the first
    field, '|' between fields). If anything goes wrong while walking the configured
    fields the helper falls back to the default prefix line and logs at debug level -
    a partially broken type definition should not block the caller. Centralizing this
    composition lets `get_summary_line` and `get_summary_lines_lookup` share one body

    A summary field the object has no value for contributes NOTHING - neither text nor a
    separator. Interpolating it would put the literal word 'None' in front of a user (an object
    whose summary field is unset used to read '#264 - None'), and emitting the separator alone
    would leave a line trailing off as '#264 - '. Only a genuinely absent value is skipped:
    `0`, `False` and other falsy-but-present values are real data and are rendered. The
    separator therefore tracks the first field actually EMITTED, not the first one configured,
    so an unset first field does not push a stray '|' to the front of the line

    Args:
        target_object (dict[str, Any]): The CmdbObject document (as_dict=True shape)
        target_object_type: The CmdbType instance of the object
        with_type (bool): If True the type label is included in the prefix

    Returns:
        str: The composed summary line
    """
    if with_type:
        default_line = f"{target_object_type.label} #{target_object.get('public_id')}"
    else:
        default_line = f"#{target_object.get('public_id')}"

    if not target_object_type.has_summaries():
        return default_line

    summary_line = default_line

    try:
        summary_fields = target_object_type.get_summary().fields
        first = True

        line: dict
        for line in summary_fields:
            field_name = line.get('name')
            field_value = next(
                (field['value'] for field in target_object['fields'] if field['name'] == field_name), None
            )

            if field_value is None or field_value == '':
                continue

            if first:
                summary_line += f' - {field_value}'
                first = False
            else:
                summary_line += f' | {field_value}'
    except Exception as err:
        LOGGER.debug(
            "Failed to build summary line for Object-ID: %s and Type-ID: %s. Error: %s!",
            target_object.get('public_id'),
            target_object_type.public_id,
            err
        )
        summary_line = default_line

    return summary_line
