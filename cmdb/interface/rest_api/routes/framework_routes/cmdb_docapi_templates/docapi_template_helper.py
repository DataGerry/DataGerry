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

The template list (``GET /docapi/template/``) narrows by two server-owned query parameters besides its
collection parameters: ``type_id`` (the templates for objects of one CmdbType) and ``active``. Both are read
strictly - a value that is not what the parameter takes is a 400, never a silently dropped filter - and turned
into one equality condition the route adds ahead of the caller's ``?filter=``.

The type is matched on the dotted path ``template_parameters.type``, so a template whose parameters carry more
keys than the type still matches. ``active`` follows what the model reads and the render refuses: a template stored
without the flag, or with ``null``, is active (``DocapiTemplate``), and only ``true`` renders - so "active" is
``true``, missing or ``null``, and "deactivated" is everything else.
"""
from typing import Any

from flask import abort, request

from cmdb.utils import Builder
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey, TemplateParameterKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    TYPE_ID_INVALID_MSG,
    TemplateListParam,
)
from cmdb.interface.rest_api.routes.routes_helper import read_boolean_query_param
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ACTIVE_FLAG_VALUES',
    'TEMPLATE_TYPE_PATH',
    'build_template_list_condition',
    'read_template_active_param',
    'read_template_type_id_param',
]

#: Where a DocapiTemplate names the CmdbType its documents are rendered for
TEMPLATE_TYPE_PATH: str = f'{DocapiTemplateKey.TEMPLATE_PARAMETERS.value}.{TemplateParameterKey.TYPE.value}'

#: The stored ``active`` values a template reads as active by - ``None`` in an ``$in`` also matches a missing key
ACTIVE_FLAG_VALUES: list[bool | None] = [True, None]


def read_template_type_id_param() -> int | None:
    """
    Reads the template list's ``type_id`` query parameter

    Raises:
        HTTPException: 400 when the value is not a positive integer

    Returns:
        int | None: The CmdbType's public_id, or None when the parameter is absent
    """
    raw_value: str | None = request.args.get(TemplateListParam.TYPE_ID.value)

    if raw_value is None:
        return None

    stripped: str = raw_value.strip()

    # ASCII digits only: isdecimal() alone also takes other scripts' digits, which int() reads as numbers
    if not (stripped.isascii() and stripped.isdecimal()) or int(stripped) < 1:
        abort(400, TYPE_ID_INVALID_MSG.format(value=raw_value))

    return int(stripped)


def read_template_active_param() -> bool | None:
    """
    Reads the template list's ``active`` query parameter

    Absent, the list keeps active and deactivated templates alike, so there is no default to pick

    Raises:
        HTTPException: 400 when the value is not ``true`` or ``false`` (``read_boolean_query_param``)

    Returns:
        bool | None: The flag, or None when the parameter is absent
    """
    if TemplateListParam.ACTIVE.value not in request.args:
        return None

    return read_boolean_query_param(TemplateListParam.ACTIVE.value, default=False)


def build_template_list_condition(type_id: int | None, active: bool | None) -> dict[str, Any]:
    """
    Builds the condition the template list adds for its ``type_id`` and ``active`` parameters

    ``active=True`` keeps the templates the render accepts - stored ``true``, ``null`` or without the key;
    ``active=False`` keeps every other one

    Args:
        type_id (int | None): The CmdbType the templates are rendered for, None for any type
        active (bool | None): Active (True) or deactivated (False) templates, None for both

    Returns:
        dict[str, Any]: The condition, empty when neither parameter was given
    """
    condition: dict[str, Any] = {}

    if type_id is not None:
        condition[TEMPLATE_TYPE_PATH] = type_id

    if active is True:
        condition.update(Builder.in_(DocapiTemplateKey.ACTIVE.value, ACTIVE_FLAG_VALUES))
    elif active is False:
        condition[DocapiTemplateKey.ACTIVE.value] = {'$nin': ACTIVE_FLAG_VALUES}

    return condition
