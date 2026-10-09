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
Unit tests for cmdb.interface.rest_api.routes.settings_routes.system_routes

Guards the blueprint contract established when these routes were promoted off the last NestedBlueprint
(which hung under a now-deleted `/settings` root blueprint) onto their own APIBlueprint: the module must
stay importable in a bare interpreter, and mounting it at '/settings/system' must still yield exactly
the two URLs the frontend's SystemService calls. Read off the module's source: both routes ask for
``base.system.view`` below the authentication decorators, and both end in ``handle_route_errors`` rather than a
hand-written ``except Exception`` tail.
"""
import ast
import inspect
import subprocess
import sys

import pytest

from flask import Flask

from cmdb.interface.rest_api.routes.settings_routes import system_routes
from cmdb.interface.rest_api.routes.settings_routes.system_routes import system_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.settings_routes.system_routes'
URL_PREFIX: str = '/settings/system'

EXPECTED_RULES: set[str] = {'/settings/system/', '/settings/system/config/'}


def _mounted_app() -> Flask:
    """Builds a bare Flask app with the system blueprint mounted at its production prefix."""
    app = Flask(__name__)
    app.register_blueprint(system_blueprint, url_prefix=URL_PREFIX)

    return app


class TestModuleIsSelfContained:
    """The routes module carries no import-time application context or parent-blueprint dependency."""

    def test_imports_in_a_bare_interpreter(self) -> None:
        """A fresh interpreter can import the module with no Flask application context pushed."""
        result = subprocess.run(
            [sys.executable, '-c', f'import {MODULE_PATH}'],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestBlueprintUrls:
    """Mounting the blueprint reproduces the frontend-facing URLs exactly."""

    def test_registers_the_expected_rules(self) -> None:
        """The blueprint exposes only the information and config URLs, both with a trailing slash."""
        rules = {
            str(rule) for rule in _mounted_app().url_map.iter_rules() if str(rule).startswith(URL_PREFIX)
        }

        assert rules == EXPECTED_RULES

    def test_rules_accept_get_only(self) -> None:
        """Both system URLs are read-only."""
        for rule in _mounted_app().url_map.iter_rules():
            if str(rule) in EXPECTED_RULES:
                assert 'GET' in rule.methods
                assert rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'} == set()


# ----------------------------------------------------- the gate ----------------------------------------------------- #

ROUTE_FUNCTIONS: list[str] = ['get_datagerry_information', 'get_config_information']
EXPECTED_ORDER: list[str] = ['route', 'insert_request_user', 'verify_api_access', 'protect', 'handle_route_errors']


def _decorators(function_name: str) -> list[ast.expr]:
    """The decorators of one route function, outermost first"""
    tree = ast.parse(inspect.getsource(system_routes))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)

    return function.decorator_list


def _name(decorator: ast.expr) -> str:
    """`bp.protect(...)` -> 'protect', `insert_request_user` -> 'insert_request_user'"""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    return target.attr if isinstance(target, ast.Attribute) else getattr(target, 'id', '')


@pytest.mark.parametrize('function_name', ROUTE_FUNCTIONS)
def test_the_route_asks_for_the_system_view_right(function_name: str) -> None:
    """One `.protect`, naming SYSTEM_VIEW_RIGHT"""
    rights = [ast.unparse(keyword.value) for decorator in _decorators(function_name)
              if _name(decorator) == 'protect' for keyword in decorator.keywords if keyword.arg == 'right']

    assert rights == ['SYSTEM_VIEW_RIGHT']


@pytest.mark.parametrize('function_name', ROUTE_FUNCTIONS)
def test_the_decorators_keep_the_house_order(function_name: str) -> None:
    """Authentication, level, right, then the error tail"""
    assert [_name(decorator) for decorator in _decorators(function_name)] == EXPECTED_ORDER


def test_no_route_writes_its_own_catch_all_tail() -> None:
    """The tail is the decorator - no `except Exception` in the module"""
    tree = ast.parse(inspect.getsource(system_routes))
    caught = [ast.unparse(handler.type) for handler in ast.walk(tree)
              if isinstance(handler, ast.ExceptHandler) and handler.type is not None]

    assert 'Exception' not in caught
