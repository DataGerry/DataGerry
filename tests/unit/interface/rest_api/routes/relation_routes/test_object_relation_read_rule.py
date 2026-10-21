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
Unit tests for the object-relation read rule at the route layer

Pins, without an app:

  - every read route of ``object_relation_routes`` - the two relation-tab routes included - asks for
    ``base.framework.objectRelation.view``
  - ``is_object_relation_readable``: a relation is readable when neither stamped type is denied
  - ``resolve_unreadable_type_ids_or_abort``: the caller's READ-denied types, a failed read a 400
  - ``read_tab_object_or_abort``: the tabs of a hidden object are a 403, of a missing one a 404, a failed read a 400
  - the default ``user`` group is seeded with both relation view rights the relation tab needs
"""
import ast
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.relation_routes import object_relation_routes, relations_helper
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE,
    ObjectRelationRight,
    RelationRight,
)
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    is_object_relation_readable,
    read_tab_object_or_abort,
    resolve_unreadable_type_ids_or_abort,
)
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.models.user_management_constants import __USER_GROUP_RIGHTS__ as USER_GROUP_RIGHTS
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import BaseManagerGetError, BaseManagerInitError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

PROTECT: str = 'protect'
ROUTE: str = 'route'
METHODS: str = 'methods'
GET: str = 'GET'
VIEW_RIGHT_SOURCE: str = 'ObjectRelationRight.VIEW.value'
TAB_ROUTES: set[str] = {'get_cmdb_object_relation_tabs', 'get_cmdb_object_relation_tab_instances'}

OBJECT_ID: int = 42
DENIED_TYPE_ID: int = 31
READABLE_TYPE_ID: int = 32


def _reader() -> CmdbUser:
    """The caller"""
    return CmdbUser(public_id=5, user_name='reader', active=True, group_id=9)


def _call_name(call: ast.Call) -> str:
    """`bp.protect(...)` -> 'protect'"""
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    """A call's keyword argument, or None"""
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _read_routes() -> dict[str, list[ast.Call]]:
    """Every route function answering GET, mapped to its decorator calls"""
    tree = ast.parse(inspect.getsource(object_relation_routes))
    routes: dict[str, list[ast.Call]] = {}

    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        calls = [decorator for decorator in function.decorator_list if isinstance(decorator, ast.Call)]
        route = next((call for call in calls if _call_name(call) == ROUTE), None)
        methods = _keyword(route, METHODS) if route is not None else None

        if methods is not None and GET in ast.literal_eval(methods):
            routes[function.name] = calls

    return routes

# ---------------------------------------------------- the right ----------------------------------------------------- #

class TestEveryReadRouteAsksForTheViewRight:
    """No object-relation read is right-less"""

    def test_the_tab_routes_are_among_the_read_routes(self) -> None:
        """The census below covers them"""
        assert TAB_ROUTES <= set(_read_routes())

    @pytest.mark.parametrize('function_name', sorted(_read_routes()))
    def test_the_route_protects_with_the_view_right(self, function_name: str) -> None:
        """Exactly one `.protect`, naming the view right"""
        rights = [ast.unparse(_keyword(call, 'right')) for call in _read_routes()[function_name]
                  if _call_name(call) == PROTECT]

        assert rights == [VIEW_RIGHT_SOURCE]

    def test_no_route_is_marked_as_ungated_any_more(self) -> None:
        """The placeholder comment went with the gap"""
        assert 'no .protect right yet' not in inspect.getsource(object_relation_routes)

# ------------------------------------------- is_object_relation_readable -------------------------------------------- #

class TestIsObjectRelationReadable:
    """Both stamped types must be readable"""

    @pytest.mark.parametrize('parent_type, child_type, readable', [
        (READABLE_TYPE_ID, READABLE_TYPE_ID, True),
        (DENIED_TYPE_ID, READABLE_TYPE_ID, False),
        (READABLE_TYPE_ID, DENIED_TYPE_ID, False),
        (DENIED_TYPE_ID, DENIED_TYPE_ID, False),
        (None, READABLE_TYPE_ID, True),
    ], ids=['both-readable', 'parent-denied', 'child-denied', 'both-denied', 'unstamped-side'])
    def test_judges_both_ends(self, parent_type: int | None, child_type: int, readable: bool) -> None:
        """A side with no stamped type is not refused for it, as the type ACL stage does"""
        object_relation: dict[str, Any] = {
            ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: parent_type,
            ObjectRelationKey.RELATION_CHILD_TYPE_ID.value: child_type,
        }

        assert is_object_relation_readable(object_relation, [DENIED_TYPE_ID]) is readable

    def test_nothing_denied_reads_everything(self) -> None:
        """The common case"""
        assert is_object_relation_readable({ObjectRelationKey.RELATION_PARENT_TYPE_ID.value: DENIED_TYPE_ID}, [])

# --------------------------------------- resolve_unreadable_type_ids_or_abort --------------------------------------- #

class TestResolveUnreadableTypeIds:
    """The caller's READ-denied types"""

    def test_answers_the_types_denied_for_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """READ, for the caller"""
        reader = _reader()
        resolver = MagicMock(return_value=[DENIED_TYPE_ID])
        monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', resolver)

        assert resolve_unreadable_type_ids_or_abort(reader) == [DENIED_TYPE_ID]
        resolver.assert_called_once_with(reader, AccessControlPermission.READ)

    @pytest.mark.parametrize('error', [BaseManagerGetError('down'), BaseManagerInitError('no tenant')],
                             ids=['read', 'init'])
    def test_a_failed_read_is_a_400(self, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
        """Named, not a 500 - and never read as 'nothing denied'"""
        monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', MagicMock(side_effect=error))

        with pytest.raises(HTTPException) as exc_info:
            resolve_unreadable_type_ids_or_abort(_reader())

        assert (exc_info.value.code, exc_info.value.description) == (400, OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE)

# --------------------------------------------- read_tab_object_or_abort --------------------------------------------- #

class TestReadTabObjectOrAbort:
    """The tabs are as readable as their object"""

    @pytest.mark.parametrize('found, error, status, message', [
        (None, AccessDeniedError('no'), 403, OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE),
        (None, None, 404, OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE),
        (None, ObjectsManagerGetError('down'), 400, OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE),
    ], ids=['hidden', 'missing', 'read-failed'])
    def test_refuses(self, found: Any, error: Exception | None, status: int, message: str) -> None:
        """Each refusal names the object"""
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = found
        objects_manager.get_object.side_effect = error

        with pytest.raises(HTTPException) as exc_info:
            read_tab_object_or_abort(OBJECT_ID, _reader(), objects_manager)

        assert (exc_info.value.code, exc_info.value.description) == (status, message.format(object_id=OBJECT_ID))

    def test_a_readable_object_passes(self) -> None:
        """Read once, as the caller, with READ"""
        reader = _reader()
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = {'public_id': OBJECT_ID}

        read_tab_object_or_abort(OBJECT_ID, reader, objects_manager)

        objects_manager.get_object.assert_called_once_with(OBJECT_ID, reader, AccessControlPermission.READ)

# ------------------------------------------------ the default group ------------------------------------------------- #

@pytest.mark.parametrize('right', [RelationRight.VIEW.value, ObjectRelationRight.VIEW.value])
def test_the_default_group_is_seeded_with_the_relation_view_rights(right: str) -> None:
    """The relation tab reads both the object relations and their CmdbRelation"""
    assert right in {seeded.name for seeded in USER_GROUP_RIGHTS}
