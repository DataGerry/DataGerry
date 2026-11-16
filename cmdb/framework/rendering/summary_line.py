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
The summary line of a rendered object: its summary values joined, or ``<type label> #<public_id>`` without any

Built by the renderer and rebuilt by the person pass once a person summary value has become its labels
"""
from typing import Any

from cmdb.models.type_model.field_key_enum import FieldKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['SUMMARY_LINE_SEPARATOR', 'default_summary_line', 'join_summary_line']

# Between two summary values of one line
SUMMARY_LINE_SEPARATOR: str = ' | '

# The line of an object whose Type has no summary, or whose summary values are all empty
DEFAULT_SUMMARY_LINE_FORMAT: str = '{label} #{public_id}'


def default_summary_line(type_label: Any, public_id: Any) -> str:
    """
    The summary line of an object without summary values

    Args:
        type_label (Any): The label of the object's Type
        public_id (Any): The object's public_id

    Returns:
        str: ``<type label> #<public_id>``
    """
    return DEFAULT_SUMMARY_LINE_FORMAT.format(label=type_label, public_id=public_id)


def join_summary_line(summaries: list[dict[str, Any]], default_line: str) -> str:
    """
    The summary line of rendered summary entries - their values joined, the default line when that is empty

    Args:
        summaries (list[dict[str, Any]]): The rendered summary entries, each carrying its ``value``
        default_line (str): The line answered when the joined values are empty

    Returns:
        str: The summary line
    """
    return SUMMARY_LINE_SEPARATOR.join(str(entry.get(FieldKey.VALUE, '')) for entry in summaries) or default_line
