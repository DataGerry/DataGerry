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
Unit tests for cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes

Covers the route-glue of the two sidebar-tree routes: each resolves the objects / types
manager pair, forwards it (plus the supernet public_id where applicable) to
its framework builder and wraps the builder's payload in a DefaultResponse. HTTPExceptions
raised below the route (e.g. the 400/404 aborts of the supernet loader) pass through
unwrapped, while unexpected errors convert to a 500. Substantive behavior belongs to the
framework-layer builders and is covered there; this module only exercises the transport
boundary. The builders and `read_ipam_managers` (the shared resolver of the objects / types
manager pair) are patched at the route module path, and each route is unwrapped past its auth
decorators.

The last sections pin what `GET /`'s 'unassigned' block holds, and that the blueprint registers no third route
"""
from typing import Any, Callable
from unittest.mock import ANY, MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.special_type_model.ipam_constants import SubnetField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.tree_overview import (
    build_ipam_tree,
    unassigned_subnet_nodes,
)
from cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes import (
    get_ipam_tree,
    get_supernet_subnet_tree,
    ipam_tree_blueprint,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes'
TREE_PATH: str = 'cmdb.framework.ipam.tree_overview'
SUPERNET_PUBLIC_ID: int = 7


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the @verify_api_access / @insert_request_user decorators off a route function."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Returns a minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_ipam_tree                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_ipam_tree_forwards_the_managers_to_the_builder(flask_app: Flask) -> None:
    """The route resolves both managers and passes them to build_ipam_tree"""
    bare = _unwrap(get_ipam_tree)
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{ROUTE_PATH}.build_ipam_tree', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(objects_manager, types_manager)), \
         flask_app.test_request_context('/'):
        bare(request_user=MagicMock())

    mock_build.assert_called_once_with(objects_manager, types_manager, ANY)


def test_get_ipam_tree_converts_unexpected_errors_to_500(flask_app: Flask) -> None:
    """A non-HTTP exception from the builder aborts with HTTP 500"""
    bare = _unwrap(get_ipam_tree)

    with patch(f'{ROUTE_PATH}.build_ipam_tree', side_effect=RuntimeError('boom')), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_supernet_subnet_tree                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_supernet_subnet_tree_forwards_managers_and_public_id(flask_app: Flask) -> None:
    """The route passes both managers and the supernet public_id to the subtree builder"""
    bare = _unwrap(get_supernet_subnet_tree)
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{ROUTE_PATH}.build_supernet_subnet_tree', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(objects_manager, types_manager)), \
         flask_app.test_request_context(f'/supernets/{SUPERNET_PUBLIC_ID}'):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    mock_build.assert_called_once_with(objects_manager, types_manager, SUPERNET_PUBLIC_ID, ANY)


def test_get_supernet_subnet_tree_passes_http_exceptions_through(flask_app: Flask) -> None:
    """A builder abort (e.g. 404 from the supernet loader) is re-raised, not wrapped into a 500"""
    bare = _unwrap(get_supernet_subnet_tree)

    with patch(f'{ROUTE_PATH}.build_supernet_subnet_tree', side_effect=NotFound('missing')), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context(f'/supernets/{SUPERNET_PUBLIC_ID}'):
        with pytest.raises(HTTPException) as exc_info:
            bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert exc_info.value.code == 404


# -------------------------------------------------------------------------------------------------------------------- #
#                        the shared error tail: an HTTPException propagates, anything else is a 500                    #
# -------------------------------------------------------------------------------------------------------------------- #
# These two `except Exception -> abort(500)` arms were the file's only uncovered statements. Each is
# paired with a propagation case, because the two arms are the whole difference between a client seeing
# the framework's own 404 for a missing supernet and seeing a generic server error
ERROR_TAIL_CASES: list[tuple[Callable[..., Any], str, str, dict[str, Any]]] = [
    (get_ipam_tree, 'build_ipam_tree', '/', {}),
    (get_supernet_subnet_tree, 'build_supernet_subnet_tree', f'/supernets/{SUPERNET_PUBLIC_ID}',
     {'public_id': SUPERNET_PUBLIC_ID}),
]


@pytest.mark.parametrize('route, builder_name, path, kwargs', ERROR_TAIL_CASES)
def test_an_unexpected_error_becomes_a_500(
    flask_app: Flask,
    route: Callable[..., Any],
    builder_name: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    """A builder blowing up is a 500, not a leaked traceback"""
    bare = _unwrap(route)

    with patch(f'{ROUTE_PATH}.{builder_name}', side_effect=RuntimeError('boom')), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context(path):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock(), **kwargs)

    assert exc_info.value.code == 500


@pytest.mark.parametrize('route, builder_name, path, kwargs', ERROR_TAIL_CASES)
def test_an_httpexception_from_a_builder_propagates_untouched(
    flask_app: Flask,
    route: Callable[..., Any],
    builder_name: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    """The framework layer's own aborts must reach the client as themselves, object identity included"""
    bare = _unwrap(route)
    raised = NotFound('Supernet with public_id 7 was not found!')

    with patch(f'{ROUTE_PATH}.{builder_name}', side_effect=raised), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context(path):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock(), **kwargs)

    assert exc_info.value is raised


# -------------------------------------------------------------------------------------------------------------------- #
#                              what the initial payload's 'unassigned' block holds                                     #
# -------------------------------------------------------------------------------------------------------------------- #
# `GET /` carries the 'unassigned' block, built by `unassigned_subnet_nodes` out of the subnets the tree already loaded
SUBNET_TYPE_ID: int = 11


def _subnet_doc(public_id: int, name: str, cidr: str, parent: Any = None) -> dict[str, Any]:
    """Builds a projected SUBNET document, the shape TREE_NODE_PROJECTION returns."""
    fields: list[dict[str, Any]] = [
        {'name': SubnetField.NAME.value, 'value': name, 'type': 'text'},
        {'name': SubnetField.NETWORK_RANGE.value, 'value': cidr, 'type': 'text'},
    ]

    if parent is not None:
        fields.append({'name': SubnetField.PARENT_SUPERNET.value, 'value': parent, 'type': 'ref'})

    return {'public_id': public_id, 'fields': fields}


def test_the_tree_reports_the_parentless_subnets_as_unassigned() -> None:
    """
    Through the real builder rather than through mocks: the block is the parentless subnets, in CIDR order
    """
    subnets: list[dict[str, Any]] = [
        _subnet_doc(1, 'free-a', '10.0.0.0/24'),
        _subnet_doc(2, 'assigned', '10.1.0.0/24', parent=99),
        _subnet_doc(3, 'free-b', '10.2.0.0/24'),
    ]
    objects_manager = MagicMock()
    types_manager = MagicMock()

    def _load(_objects, _types, special_type, _projection=None, _denied=None):
        return subnets if special_type == SpecialType.SUBNET else []

    with patch(f'{TREE_PATH}.load_all_special_type_objects', side_effect=_load), \
         patch(f'{TREE_PATH}.resolve_special_type_icon', return_value=None):
        tree = build_ipam_tree(objects_manager, types_manager)

    assert [node['public_id'] for node in tree['unassigned']] == [1, 3]


def test_a_subnet_with_a_parent_is_not_unassigned() -> None:
    """A usable supernet reference takes the subnet out of the block"""
    nodes = unassigned_subnet_nodes([_subnet_doc(2, 'assigned', '10.1.0.0/24', parent=99)], None)

    assert nodes == []


@pytest.mark.parametrize('parent', [None, '', 0])
def test_an_empty_reference_still_counts_as_unassigned(parent: Any) -> None:
    """
    'No usable reference' covers the three ways a stored ref says nothing

    None, the empty string and 0 all mean "not assigned" to the IPAM enforcement layer, so the tree
    has to agree with it or a subnet would be missing from both blocks.
    """
    nodes = unassigned_subnet_nodes([_subnet_doc(1, 'free', '10.0.0.0/24', parent=parent)], None)

    assert [node['public_id'] for node in nodes] == [1]


def test_a_dangling_reference_is_in_no_block() -> None:
    """
    The documented gap, pinned so it is a decision rather than a surprise

    A subnet referencing a supernet that does not exist is not 'unassigned' (it has a reference) and
    is not under any supernet (its parent is gone), so it appears nowhere in the tree. Unreachable
    through the write and delete guards today.
    """
    subnets: list[dict[str, Any]] = [_subnet_doc(5, 'orphan', '10.9.0.0/24', parent=4242)]
    objects_manager = MagicMock()
    types_manager = MagicMock()

    def _load(_objects, _types, special_type, _projection=None, _denied=None):
        return subnets if special_type == SpecialType.SUBNET else []

    with patch(f'{TREE_PATH}.load_all_special_type_objects', side_effect=_load), \
         patch(f'{TREE_PATH}.resolve_special_type_icon', return_value=None):
        tree = build_ipam_tree(objects_manager, types_manager)

    assert tree['unassigned'] == []
    assert tree['supernets'] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the registered routes                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
TREE_ROUTES: set[str] = {'/', '/supernets/<int:public_id>'}


def test_the_blueprint_registers_the_two_tree_routes_only() -> None:
    """No separate 'unassigned' route: the block comes with `GET /`"""
    app = Flask(__name__)
    app.register_blueprint(ipam_tree_blueprint, url_prefix='/ipam/tree')

    rules: set[str] = {rule.rule.removeprefix('/ipam/tree') or '/'
                       for rule in app.url_map.iter_rules() if rule.endpoint.startswith('ipam_tree.')}

    assert rules == TREE_ROUTES
