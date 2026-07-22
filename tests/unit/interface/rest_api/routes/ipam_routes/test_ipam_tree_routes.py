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

Covers the route-glue of the three sidebar-tree routes: each resolves the objects / types
managers via ManagerProvider, forwards them (plus the supernet public_id where applicable) to
its framework builder and wraps the builder's payload in a DefaultResponse. HTTPExceptions
raised below the route (e.g. the 400/404 aborts of the supernet loader) pass through
unwrapped, while unexpected errors convert to a 500. Substantive behavior belongs to the
framework-layer builders and is covered there; this module only exercises the transport
boundary. The builders and ManagerProvider.get_manager are patched at the route module path,
and each route is unwrapped past its auth decorators
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes import (
    get_ipam_tree,
    get_supernet_subnet_tree,
    get_unassigned_subnets,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_tree_routes'
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
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]), \
         flask_app.test_request_context('/'):
        bare(request_user=MagicMock())

    mock_build.assert_called_once_with(objects_manager, types_manager)


def test_get_ipam_tree_converts_unexpected_errors_to_500(flask_app: Flask) -> None:
    """A non-HTTP exception from the builder aborts with HTTP 500"""
    bare = _unwrap(get_ipam_tree)

    with patch(f'{ROUTE_PATH}.build_ipam_tree', side_effect=RuntimeError('boom')), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
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
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]), \
         flask_app.test_request_context(f'/supernets/{SUPERNET_PUBLIC_ID}'):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    mock_build.assert_called_once_with(objects_manager, types_manager, SUPERNET_PUBLIC_ID)


def test_get_supernet_subnet_tree_passes_http_exceptions_through(flask_app: Flask) -> None:
    """A builder abort (e.g. 404 from the supernet loader) is re-raised, not wrapped into a 500"""
    bare = _unwrap(get_supernet_subnet_tree)

    with patch(f'{ROUTE_PATH}.build_supernet_subnet_tree', side_effect=NotFound('missing')), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/supernets/{SUPERNET_PUBLIC_ID}'):
        with pytest.raises(HTTPException) as exc_info:
            bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert exc_info.value.code == 404


# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_unassigned_subnets                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_unassigned_subnets_forwards_the_managers_to_the_builder(flask_app: Flask) -> None:
    """The route resolves both managers and passes them to build_unassigned_subnets"""
    bare = _unwrap(get_unassigned_subnets)
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{ROUTE_PATH}.build_unassigned_subnets', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=[objects_manager, types_manager]), \
         flask_app.test_request_context('/unassigned'):
        bare(request_user=MagicMock())

    mock_build.assert_called_once_with(objects_manager, types_manager)
