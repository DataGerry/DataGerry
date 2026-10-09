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
Unit census of the OpenCelium routes' gates, read off the route modules' source

  - every OpenCelium route carries exactly one ``.protect``, naming the ``OcRight`` this module expects of it
  - every route keeps the house order: route, ``insert_request_user``, ``verify_api_access``, ``protect``,
    (``requires_feature`` on the licence routes), and the ``handle_oc_errors`` tail last
  - every ``OcRight`` is a right of the tree; the scheduler update body is read by ``read_scheduler_update_body``
"""
import ast
import inspect
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes import (
    oc_connection_log_routes,
    oc_connection_routes,
    oc_connector_routes,
    oc_invoker_routes,
    oc_license_routes,
    oc_scheduler_routes,
    oc_template_routes,
)
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcAutomationMessage, OcRight
from cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_helper import read_scheduler_update_body
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
# -------------------------------------------------------------------------------------------------------------------- #

V, A, E, D = 'CONNECTION_VIEW', 'CONNECTION_ADD', 'CONNECTION_EDIT', 'CONNECTION_DELETE'

EXPECTED: dict[ModuleType, dict[str, str]] = {
    oc_scheduler_routes: {
        'create_oc_scheduler': A, 'get_oc_scheduler': V, 'get_all_oc_schedulers': V, 'get_oc_running_schedulers': V,
        'get_oc_scheduler_logs': V, 'execute_oc_scheduler': E, 'update_oc_scheduler': E, 'delete_oc_scheduler': D,
    },
    oc_connection_log_routes: {
        'oc_get_method_or_operator_details': V, 'oc_get_operator_children': V, 'oc_get_flowcharts': V,
        'oc_get_first_level_logs': V, 'oc_get_log_list': V, 'oc_delete_logs': D,
    },
    oc_template_routes: {
        'create_oc_template': A, 'get_oc_template': V, 'get_all_oc_templates': V, 'get_all_oc_templates_detailed': V,
    },
    oc_invoker_routes: {
        'get_all_oc_invokers': 'CONNECTOR_VIEW', 'get_oc_invoker_by_name': 'CONNECTOR_VIEW',
        'check_oc_invoker_exists': 'CONNECTOR_VIEW',
    },
    oc_license_routes: {'get_oc_license_activation': V, 'get_oc_license_info': V},
    oc_connection_routes: {
        'create_oc_connection': A, 'test_oc_connection': A, 'oc_send_to_remote_api': A, 'get_oc_connection': V,
        'update_oc_connection': E,
    },
    oc_connector_routes: {
        'create_oc_connector': 'CONNECTOR_ADD', 'check_oc_connector': 'CONNECTOR_ADD',
        'check_oc_connector_master_pw': 'CONNECTOR_VIEW', 'get_oc_connector': 'CONNECTOR_VIEW',
        'check_master_password': 'CONNECTOR_VIEW', 'check_master_password_exists': 'CONNECTOR_VIEW',
        'get_all_oc_connectors': 'CONNECTOR_VIEW', 'check_oc_connector_exists': 'CONNECTOR_VIEW',
        'update_oc_connector': 'CONNECTOR_EDIT', 'delete_oc_connector': 'CONNECTOR_DELETE',
        'create_oc_internal_connector': 'CONNECTOR_ADD', 'update_internal_oc_connector': 'CONNECTOR_EDIT',
        'get_internal_oc_connector': 'CONNECTOR_VIEW',
    },
}
CASES: list[tuple[ModuleType, str, str]] = [
    (module, function_name, right) for module, routes in EXPECTED.items() for function_name, right in routes.items()
]
CASE_IDS: list[str] = [f'{module.__name__.rsplit(".", 1)[1]}.{name}' for module, name, _right in CASES]

ROUTE_ORDER: list[str] = ['route', 'insert_request_user', 'verify_api_access', 'protect', 'handle_oc_errors']
LICENCE_ROUTE_ORDER: list[str] = [
    'route', 'insert_request_user', 'verify_api_access', 'protect', 'requires_feature', 'handle_oc_errors',
]


def _route_functions(module: ModuleType) -> dict[str, list[ast.expr]]:
    """Every route function of a module, mapped to its decorators"""
    tree = ast.parse(inspect.getsource(module))

    return {node.name: node.decorator_list for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and any(_name(d) == 'route' for d in node.decorator_list)}


def _name(decorator: ast.expr) -> str:
    """`bp.protect(...)` -> 'protect', `insert_request_user` -> 'insert_request_user'"""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    return target.attr if isinstance(target, ast.Attribute) else getattr(target, 'id', '')


@pytest.mark.parametrize('module', list(EXPECTED), ids=[m.__name__.rsplit('.', 1)[1] for m in EXPECTED])
def test_the_census_names_every_route(module: ModuleType) -> None:
    """A new route has to be added here, with its right"""
    assert set(_route_functions(module)) == set(EXPECTED[module])


@pytest.mark.parametrize('module, function_name, right', CASES, ids=CASE_IDS)
def test_the_route_asks_for_its_right(module: ModuleType, function_name: str, right: str) -> None:
    """One `.protect`, naming the OcRight member"""
    rights = [ast.unparse(keyword.value) for decorator in _route_functions(module)[function_name]
              if _name(decorator) == 'protect' for keyword in decorator.keywords if keyword.arg == 'right']

    assert rights == [f'OcRight.{right}.value']


@pytest.mark.parametrize('module, function_name, right', CASES, ids=CASE_IDS)
def test_the_route_keeps_the_house_order(module: ModuleType, function_name: str, right: str) -> None:
    """Authentication, level, right, licence (licence routes), then the error tail"""
    del right
    expected = LICENCE_ROUTE_ORDER if module is oc_license_routes else ROUTE_ORDER

    assert [_name(d) for d in _route_functions(module)[function_name]] == expected


def test_every_oc_right_is_a_right_of_the_tree() -> None:
    """A misspelt right would refuse everyone"""
    assert {right.value for right in OcRight} <= {right.name for right in flat_rights_tree(ALL_RIGHTS)}

# -------------------------------------------- read_scheduler_update_body -------------------------------------------- #

@pytest.fixture(name='flask_app')
def fixture_flask_app() -> BaseCmdbApp:
    """A bare app, for abort()"""
    with patch.object(BaseCmdbApp, '__init__', lambda self, *a, **k: None):
        return BaseCmdbApp.__new__(BaseCmdbApp)


class TestReadSchedulerUpdateBody:
    """An object; a title, when sent or required, is a non-blank text"""

    @pytest.mark.parametrize('body', [None, [], 'text', 5], ids=['none', 'list', 'string', 'number'])
    def test_anything_but_an_object_is_a_400(self, body: Any) -> None:
        """The body is forwarded as it is, so it has to be one"""
        with pytest.raises(HTTPException) as exc_info:
            read_scheduler_update_body(body, title_required=False)

        assert (exc_info.value.code, exc_info.value.description) == (
            400, OcAutomationMessage.UPDATE_BODY_NOT_AN_OBJECT.value)

    @pytest.mark.parametrize('title', ['', '   ', 5, None], ids=['empty', 'blank', 'number', 'missing'])
    def test_a_required_title_must_be_text(self, title: Any) -> None:
        """Cloud mode maps it to the tenant"""
        body: dict[str, Any] = {} if title is None else {'title': title}

        with pytest.raises(HTTPException) as exc_info:
            read_scheduler_update_body(body, title_required=True)

        assert (exc_info.value.code, exc_info.value.description) == (
            400, OcAutomationMessage.UPDATE_TITLE_INVALID.value)

    @pytest.mark.parametrize('title', ['', 5], ids=['empty', 'number'])
    def test_a_sent_title_must_be_text_even_when_optional(self, title: Any) -> None:
        """On premise it is optional - but not unusable"""
        with pytest.raises(HTTPException):
            read_scheduler_update_body({'title': title}, title_required=False)

    @pytest.mark.parametrize('body, required', [
        ({'title': 'Nightly sync'}, True), ({'title': 'Nightly sync'}, False), ({'cronExp': '0 0 * * * ?'}, False),
    ], ids=['title-required', 'title-optional', 'no-title-optional'])
    def test_a_usable_body_is_answered_as_it_is(self, body: dict[str, Any], required: bool) -> None:
        """The same object, untouched"""
        assert read_scheduler_update_body(body, title_required=required) is body
