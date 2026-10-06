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
Unit tests for the gate in front of the DocAPI render route

Read off the route module's source, so they hold without an app: the render stacks two `.protect` decorators -
the object right, then the template right - inside the authentication block and ahead of the licence gate; both
rights are real entries of the rights catalogue (a misspelt right never raises, it just refuses everyone); and
the deactivated-template message names the template
"""
import ast
import inspect

from cmdb.manager.rights_manager import RightsManager
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates import docapi_template_routes
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_RIGHT,
    RENDER_TEMPLATE_DEACTIVATED_MSG,
    DocapiTemplateRight,
)
# -------------------------------------------------------------------------------------------------------------------- #

RENDER_FUNCTION: str = 'render_object_template'
PROTECT: str = 'protect'
LICENCE_GATE: str = 'requires_feature'
TEMPLATE_ID: int = 4711


def _render_decorators() -> list[ast.Call]:
    """The decorator calls of the render route, outermost first"""
    tree = ast.parse(inspect.getsource(docapi_template_routes))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == RENDER_FUNCTION)

    return [decorator for decorator in function.decorator_list if isinstance(decorator, ast.Call)]


def _name(call: ast.Call) -> str:
    """`bp.protect(...)` -> 'protect', `requires_feature(...)` -> 'requires_feature'"""
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')


def _right_argument(call: ast.Call) -> str:
    """The source text of a `.protect` call's `right=` argument"""
    return next(ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg == 'right')


class TestTheStackedGate:
    """Two `.protect` decorators, object right first"""

    def test_the_render_asks_for_both_rights(self) -> None:
        """The object right, then the template right"""
        rights = [_right_argument(call) for call in _render_decorators() if _name(call) == PROTECT]

        assert rights == ['RENDER_OBJECT_RIGHT', 'DocapiTemplateRight.VIEW.value']

    def test_both_gates_run_before_the_licence_gate(self) -> None:
        """An unlicensed edition still answers the caller's rights first, as every DocAPI route does"""
        names = [_name(call) for call in _render_decorators()]

        assert max(index for index, name in enumerate(names) if name == PROTECT) < names.index(LICENCE_GATE)


class TestTheRights:
    """Both rights exist in the catalogue"""

    def test_the_object_half_is_object_view(self) -> None:
        """Taken from ObjectRightName, not spelt out"""
        assert RENDER_OBJECT_RIGHT == ObjectRightName.VIEW.value

    def test_both_rights_are_catalogue_entries(self) -> None:
        """A right missing from the catalogue would refuse every caller without an error"""
        rights_manager = RightsManager()

        assert rights_manager.get_right(RENDER_OBJECT_RIGHT) is not None
        assert rights_manager.get_right(DocapiTemplateRight.VIEW.value) is not None


class TestTheDeactivatedMessage:
    """The refusal names the template"""

    def test_it_names_the_template_id(self) -> None:
        """So the toast says which template is switched off"""
        assert str(TEMPLATE_ID) in RENDER_TEMPLATE_DEACTIVATED_MSG.format(public_id=TEMPLATE_ID)
