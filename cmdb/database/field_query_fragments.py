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
Query fragments over a CmdbObject's field entries - shared by the two compilers that filter objects by field values:
the report query builder (``mongo_query_builder``) and the access scope compiler (``framework.scope_compiler``)

A CmdbObject keeps its values as entries ``{name, value, type}`` in ``fields``; a condition on one field is an
``$elemMatch`` selecting the entry by name and testing its value. Two semantics both compilers rely on:

  * **An object without an entry for the field** (a field added to the Type after the object was created) is reached
    by no ``$elemMatch`` - ``no_entry`` matches it explicitly.
  * **Dates are day-granular**: a condition carries a day, the field a full timestamp, so a comparison is widened to
    the whole day (``day_granular_fragment``).

MongoDB operator names are written as bare literals, as in ``utils/builder.py``: they are the database's vocabulary
"""
import re
from datetime import datetime
from typing import Any

from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FIELDS_PATH',
    'FIELD_NAME_KEY',
    'FIELD_VALUE_KEY',
    'elem_match',
    'no_entry',
    'end_of_day',
    'day_granular_fragment',
    'contains_fragment',
    'starts_with_fragment',
]

FIELDS_PATH: str = CmdbObjectKey.FIELDS.value
FIELD_NAME_KEY: str = CmdbObjectFieldKey.NAME.value
FIELD_VALUE_KEY: str = CmdbObjectFieldKey.VALUE.value


def elem_match(field_name: str, value_fragment: dict[str, Any]) -> dict[str, Any]:
    """
    The ``$elemMatch`` selecting the named field entry and testing its value

    Args:
        field_name (str): The name of the field entry
        value_fragment (dict[str, Any]): The comparison applied to the entry's value

    Returns:
        dict[str, Any]: The fragment, to put under the entries' path
    """
    return {'$elemMatch': {FIELD_NAME_KEY: field_name, FIELD_VALUE_KEY: value_fragment}}


def no_entry(field_name: str, path: str = FIELDS_PATH) -> dict[str, Any]:
    """
    The condition matching an object that carries no entry for the field at all

    Args:
        field_name (str): The name of the field
        path (str): The entries' path

    Returns:
        dict[str, Any]: The filter document
    """
    return {path: {'$not': {'$elemMatch': {FIELD_NAME_KEY: field_name}}}}


def end_of_day(moment: datetime) -> datetime:
    """
    The last representable instant of the given day

    Args:
        moment (datetime): Any instant on the wanted day

    Returns:
        datetime: The same day at 23:59:59.999999
    """
    return moment.replace(hour=23, minute=59, second=59, microsecond=999999)


def day_granular_fragment(mongo_operator: str, day_start: datetime) -> dict[str, Any] | None:
    """
    The day-widened comparison of a date for the operators that need it

    ``$gte`` and ``$lt`` mean "from / before the start of the day" and need no widening; ``$eq``, ``$ne``, ``$lte``
    and ``$gt`` are widened to the whole day, or they would exclude everything after 00:00:00 on it

    Args:
        mongo_operator (str): The comparison's MongoDB operator (``$eq``, ``$ne``, ``$lte``, ``$gt``, ...)
        day_start (datetime): The day, at midnight

    Returns:
        dict[str, Any] | None: The widened fragment, or None when the operator needs no widening
    """
    day_end: datetime = end_of_day(day_start)

    if mongo_operator == '$eq':
        return {'$gte': day_start, '$lte': day_end}

    if mongo_operator == '$ne':
        return {'$not': {'$gte': day_start, '$lte': day_end}}

    if mongo_operator == '$lte':
        return {'$lte': day_end}

    if mongo_operator == '$gt':
        return {'$gt': day_end}

    return None


def contains_fragment(value: Any, case_insensitive: bool = False) -> dict[str, Any]:
    """
    The substring match of a text value - the input regex-escaped, so it is matched literally

    Args:
        value (Any): The text looked for
        case_insensitive (bool): Whether case is ignored

    Returns:
        dict[str, Any]: A ``$regex`` fragment
    """
    fragment: dict[str, Any] = {'$regex': re.escape(str(value))}

    if case_insensitive:
        fragment['$options'] = 'i'

    return fragment


def starts_with_fragment(value: Any) -> dict[str, Any]:
    """
    The prefix match of a text value - anchored, so an index on the value can serve it; the input regex-escaped

    Args:
        value (Any): The prefix

    Returns:
        dict[str, Any]: A ``$regex`` fragment
    """
    return {'$regex': f'^{re.escape(str(value))}'}
