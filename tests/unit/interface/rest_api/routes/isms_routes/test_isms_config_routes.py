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
Unit tests for the shape of GET /isms/config/status, read off the route module's source

The route needs no right, by ruling: every ISMS screen reads it. That only stays acceptable while it writes
nothing, so both halves are pinned - no ``.protect`` on it, and none of the matrix helpers or manager methods
that write is reachable from the module
"""
import ast
import inspect

import pytest

from cmdb.interface.rest_api.routes.isms_routes import isms_config_routes
# -------------------------------------------------------------------------------------------------------------------- #

STATUS_FUNCTION: str = 'get_isms_config_status'
PROTECT: str = 'protect'
WRITING_NAMES: list[str] = [
    'ensure_default_risk_matrix', 'ensure_risk_matrix_matches_scales', 'calculate_risk_matrix',
    'insert_item', 'update_item', 'delete_item', 'insert', 'update', 'delete',
]


def _module_tree() -> ast.Module:
    """The parsed route module"""
    return ast.parse(inspect.getsource(isms_config_routes))


def _decorator_names() -> list[str]:
    """The decorator names of the status route, outermost first"""
    function = next(node for node in ast.walk(_module_tree())
                    if isinstance(node, ast.FunctionDef) and node.name == STATUS_FUNCTION)
    names: list[str] = []

    for decorator in function.decorator_list:
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(call.attr if isinstance(call, ast.Attribute) else getattr(call, 'id', ''))

    return names


def test_the_status_route_carries_no_right() -> None:
    """Ruled: any logged-in ISMS user reads the five flags"""
    assert PROTECT not in _decorator_names()


def test_the_status_route_maps_manager_errors_below_its_tail() -> None:
    """handle_manager_errors directly below handle_route_errors, as on every ISMS route"""
    names = _decorator_names()

    assert names.index('handle_manager_errors') == names.index('handle_route_errors') + 1


@pytest.mark.parametrize('name', WRITING_NAMES)
def test_the_module_reaches_nothing_that_writes(name: str) -> None:
    """A route no right guards only reads"""
    used: set[str] = {node.id for node in ast.walk(_module_tree()) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(_module_tree()) if isinstance(node, ast.Attribute)}

    assert name not in used
