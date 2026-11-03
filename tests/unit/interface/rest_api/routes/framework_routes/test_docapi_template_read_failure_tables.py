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
Unit tests for the manager-error tables of the DocapiTemplate routes that read a template (or an object) first

Read off the route module's source, so they hold without an app: every route that reads the addressed template
maps the template read's error, the render maps its object read's error too, and each message a table names is a
constant of the route constants whose placeholders are all arguments of that route - ``handle_manager_errors``
fills a message from the route's arguments, so a placeholder the route does not take would fail the 400 itself
"""
import ast
import inspect
from string import Formatter

import pytest

from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates import (
    docapi_template_constants,
    docapi_template_routes,
)
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_ERRORS_DECORATOR: str = 'handle_manager_errors'
TEMPLATE_GET_ERROR: str = 'DocapiTemplatesManagerGetError'
OBJECT_GET_ERROR: str = 'ObjectsManagerGetError'

# route function -> the error classes its table must name
EXPECTED_TABLES: dict[str, set[str]] = {
    'get_template': {TEMPLATE_GET_ERROR},
    'update_template': {TEMPLATE_GET_ERROR, 'DocapiTemplatesManagerUpdateError'},
    'delete_template': {TEMPLATE_GET_ERROR, 'DocapiTemplatesManagerDeleteError'},
    'render_object_template': {TEMPLATE_GET_ERROR, OBJECT_GET_ERROR},
}


def _route(name: str) -> ast.FunctionDef:
    """The route function ``name`` of the route module"""
    tree = ast.parse(inspect.getsource(docapi_template_routes))

    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _table(name: str) -> dict[str, str]:
    """The ``handle_manager_errors`` table of the route ``name``: error class name -> message constant name"""
    decorator = next(call for call in _route(name).decorator_list
                     if isinstance(call, ast.Call) and getattr(call.func, 'id', '') == MANAGER_ERRORS_DECORATOR)
    table = decorator.args[0]
    assert isinstance(table, ast.Dict)

    return {ast.unparse(key): ast.unparse(value) for key, value in zip(table.keys, table.values)}


def _placeholders(message: str) -> set[str]:
    """The named fields a message template formats"""
    return {field for _text, field, _spec, _conversion in Formatter().parse(message) if field}


@pytest.mark.parametrize('route, expected', EXPECTED_TABLES.items(), ids=list(EXPECTED_TABLES))
def test_the_table_names_the_route_s_read_errors(route: str, expected: set[str]) -> None:
    """A failed read is the route's 400, not the generic 500"""
    assert set(_table(route)) == expected


@pytest.mark.parametrize('route', EXPECTED_TABLES, ids=list(EXPECTED_TABLES))
def test_every_message_is_a_route_constant_the_route_can_fill(route: str) -> None:
    """No inline message, and no placeholder the route's arguments cannot fill"""
    arguments: set[str] = {argument.arg for argument in _route(route).args.args}

    for constant_name in _table(route).values():
        message = getattr(docapi_template_constants, constant_name, None)

        assert isinstance(message, str), f"{route}: '{constant_name}' is not a message constant"
        assert _placeholders(message) <= arguments, f"{route}: '{constant_name}' names a field it cannot fill"


def test_the_template_reads_share_one_message() -> None:
    """The same failure reads the same on every route that reads the addressed template"""
    messages: set[str] = {_table(route)[TEMPLATE_GET_ERROR] for route in EXPECTED_TABLES}

    assert messages == {'TEMPLATE_NOT_READABLE_MSG'}
