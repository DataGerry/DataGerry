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
Required fields and field classes on an object write (phase 12, D7)

A required field carrying a field class is enforced only for a user who may write that class; a user who may not
saves without it and the write answer says so (``field_warnings``). A ``system`` field is never required of a user. The
warnings of one request are collected here and attached to the write answer: as the ``field_warnings`` key of an
enveloped JSON answer, and always as the ``X-Field-Warnings`` header (a create answers its bare id)
"""
import json
from typing import Any

from werkzeug import Response

from cmdb.utils import request_cache
from cmdb.models.access_model import SYSTEM_FIELD_CLASS, ScopeOperation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import classes_of_fields, unwritable_fields
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FIELD_WARNINGS_KEY',
    'FIELD_WARNINGS_HEADER',
    'required_exemptions',
    'record_field_warnings',
    'with_field_warnings',
]

FIELD_WARNINGS_KEY: str = 'field_warnings'
FIELD_WARNINGS_HEADER: str = 'X-Field-Warnings'
FIELD_WARNING_MESSAGE: str = "'{field}' is required for whoever may write the field class '{field_class}' - left empty"
_CACHE_KEY: str = 'object-field-warnings'
_WARNINGS: str = 'warnings'
_FIELD: str = 'field'
_MESSAGE: str = 'message'


def required_exemptions(request_user: CmdbUser | None, object_data: dict[str, Any], object_type: CmdbType,
                        required_names: set[str], operation: ScopeOperation) -> tuple[set[str], dict[str, str]]:
    """
    The required fields the writer is not held to: every ``system`` field, and the classed fields they may not write

    Args:
        request_user (CmdbUser | None): The writer; None judges no class (only ``system`` is exempt)
        object_data (dict[str, Any]): The candidate object
        object_type (CmdbType): Its Type
        required_names (set[str]): The Type's required field names
        operation (ScopeOperation): CREATE or EDIT

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the grants could not be read
        ScopeResolutionError: When a conditional assignment could not be evaluated

    Returns:
        tuple[set[str], dict[str, str]]: The exempt names, and of those the ones a writer of the class is held to,
            with their class (what a warning names)
    """
    classes: dict[str, str] = classes_of_fields(object_type.get_fields())
    classed: list[str] = sorted(name for name in required_names if name in classes)
    system: set[str] = {name for name in classed if classes[name] == SYSTEM_FIELD_CLASS}
    others: list[str] = [name for name in classed if name not in system]

    if not others or request_user is None:
        return system, {}

    unwritable: tuple[str, ...] = unwritable_fields(request_user, object_data, others, operation, classes)

    return system | set(unwritable), {name: classes[name] for name in unwritable}


def record_field_warnings(missing: set[str], classes: dict[str, str]) -> None:
    """
    Records a warning per required classed field left empty by a writer it does not hold

    Args:
        missing (set[str]): The required fields left empty
        classes (dict[str, str]): The exempt classed fields a writer of the class is held to, with their class
    """
    cache: dict[Any, Any] | None = request_cache(_CACHE_KEY)

    if cache is None:
        return

    warnings: list[dict[str, str]] = cache.setdefault(_WARNINGS, [])
    warnings.extend({_FIELD: name, _MESSAGE: FIELD_WARNING_MESSAGE.format(field=name, field_class=classes[name])}
                    for name in sorted(missing) if name in classes)


def with_field_warnings(response: Response) -> Response:
    """
    Attaches the request's field warnings to a write answer - nothing when there are none

    Args:
        response (Response): The answer

    Returns:
        Response: The same answer
    """
    cache: dict[Any, Any] | None = request_cache(_CACHE_KEY)
    warnings: list[dict[str, str]] = (cache or {}).get(_WARNINGS) or []

    if not warnings:
        return response

    response.headers[FIELD_WARNINGS_HEADER] = json.dumps(warnings)
    body: Any = response.get_json(silent=True)

    if isinstance(body, dict):
        body[FIELD_WARNINGS_KEY] = warnings
        response.set_data(json.dumps(body, default=str))

    return response
