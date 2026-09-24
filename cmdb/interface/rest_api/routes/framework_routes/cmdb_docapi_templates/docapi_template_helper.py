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
Request helpers for the DocapiTemplate REST routes

`parse_template_searchfilter` turns the JSON filter of `GET /docapi/template/by/<searchfilter>` into
the query the manager runs. That filter is handed to MongoDB as the query document itself, so it is
checked here before it gets there: a plain equality match on the keys `SEARCHFILTER_KEYS` names, with
JSON scalar values - and, for `template_parameters`, an object of scalars. Every MongoDB operator
(`$where`, `$expr` + `$function`, `$regex`, ...) is refused, because `$where` and `$function` run
JavaScript on the database server.
"""
import json
from typing import Any

from flask import abort

from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    SEARCHFILTER_KEYS,
    SEARCHFILTER_NESTED_KEYS,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'check_nested_searchfilter_value',
    'is_searchfilter_scalar',
    'parse_template_searchfilter',
]

# What marks a MongoDB operator key; a document key never starts with it
MONGO_OPERATOR_PREFIX: str = '$'

# How the refusal messages name the values an equality match can use
SCALAR_DESCRIPTION: str = 'string, number, boolean or null'


def is_searchfilter_scalar(value: Any) -> bool:
    """
    Reports whether a searchfilter value is a JSON scalar an equality match can use

    Args:
        value (Any): A value out of the parsed searchfilter

    Returns:
        bool: True for a string, a number, a boolean or null
    """
    return value is None or isinstance(value, (str, int, float, bool))


def check_nested_searchfilter_value(key: str, value: dict[str, Any]) -> None:
    """
    Refuses a nested searchfilter object that carries an operator or a non-scalar value

    Args:
        key (str): The top-level searchfilter key the object belongs to
        value (dict[str, Any]): The object given for that key

    Raises:
        HTTPException: 400 naming the offending key
    """
    for nested_key, nested_value in value.items():
        if str(nested_key).startswith(MONGO_OPERATOR_PREFIX):
            abort(400, f"The searchfilter may not use the operator '{nested_key}' in '{key}'!")

        if not is_searchfilter_scalar(nested_value):
            abort(400, f"The searchfilter value of '{key}.{nested_key}' must be a {SCALAR_DESCRIPTION}!")


def parse_template_searchfilter(raw_filter: str) -> dict[str, Any]:
    """
    Parses and checks the JSON filter of the DocapiTemplate searchfilter route

    The result is an equality match on declared DocapiTemplate keys and nothing else, so it can be
    handed to MongoDB as a query document. An empty object is allowed and matches every template

    Args:
        raw_filter (str): The searchfilter as it arrived in the URL

    Raises:
        HTTPException: 400 when the filter is not valid JSON, is not an object, names a key that is
            not searchable (an operator such as ``$where`` included), or carries a value an equality
            match cannot use

    Returns:
        dict[str, Any]: The checked filter
    """
    try:
        parsed: Any = json.loads(raw_filter)
    except ValueError:
        abort(400, f"The searchfilter is not valid JSON: {raw_filter}")

    if not isinstance(parsed, dict):
        abort(400, "The searchfilter must be a JSON object!")

    for key, value in parsed.items():
        if key not in SEARCHFILTER_KEYS:
            abort(400, f"The searchfilter may not use the key '{key}'! "
                       f"Allowed: {', '.join(sorted(SEARCHFILTER_KEYS))}")

        if key in SEARCHFILTER_NESTED_KEYS and isinstance(value, dict):
            check_nested_searchfilter_value(key, value)
        elif not is_searchfilter_scalar(value):
            abort(400, f"The searchfilter value of '{key}' must be a {SCALAR_DESCRIPTION}!")

    return parsed
