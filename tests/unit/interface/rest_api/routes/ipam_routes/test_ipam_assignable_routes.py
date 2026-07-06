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
Unit tests for cmdb.interface.rest_api.routes.ipam_routes.ipam_assignable_routes

Covers the route-glue responsibilities of get_assignable_objects: reading page / page_size /
search from the query string under their IpamOverviewKey constants, applying the
IpamSearch.MAX_QUERY_LENGTH truncation cap, and forwarding the values to the framework-layer
orchestrator. Substantive behavior (capable-type discovery, search filter, pagination) belongs
to build_assignable_objects_page and is covered in the framework-layer tests; this module only
exercises the transport boundary

The route function carries auth decorators that abort outside a real session, so each test
unwraps the decorator chain via __wrapped__ and calls the bare handler inside a Flask
test_request_context. build_assignable_objects_page and ManagerProvider.get_manager are
patched at the route module path so no DB or business logic runs
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.special_type_model.ipam_constants import IpamPagination, IpamSearch, IpamOverviewKey
from cmdb.interface.rest_api.routes.ipam_routes.ipam_assignable_routes import get_assignable_objects
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_assignable_routes'


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the @verify_api_access / @insert_request_user decorators off a route function."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='bare_get_assignable_objects')
def fixture_bare_get_assignable_objects() -> Callable[..., Any]:
    """Returns the undecorated get_assignable_objects handler, callable inside a request context."""
    return _unwrap(get_assignable_objects)


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Returns a minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='patched_orchestrator')
def fixture_patched_orchestrator() -> Any:
    """
    Patches build_assignable_objects_page and ManagerProvider.get_manager at the route module path

    The orchestrator returns a sentinel payload so the route's DefaultResponse wrapper has
    something to serialise; tests assert against the captured kwargs on the orchestrator mock
    """
    payload: dict[str, Any] = {'sentinel': True}

    with patch(f'{ROUTE_PATH}.build_assignable_objects_page', return_value=payload) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()):
        yield mock_build


# -------------------------------------------------------------------------------------------------------------------- #
#                                            search query-param forwarding                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_forwards_search_query_param_to_orchestrator(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A 'search=router' query param is read under IpamOverviewKey.SEARCH and forwarded verbatim"""
    with flask_app.test_request_context('/?search=router'):
        bare_get_assignable_objects(request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == 'router'


def test_route_forwards_empty_search_when_query_param_missing(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """Missing 'search' query param → empty string forwarded so the framework restores the unfiltered view"""
    with flask_app.test_request_context('/'):
        bare_get_assignable_objects(request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == ''


def test_route_truncates_search_at_max_query_length(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A search longer than IpamSearch.MAX_QUERY_LENGTH is truncated at the route boundary"""
    oversized: str = 'x' * (IpamSearch.MAX_QUERY_LENGTH + 50)

    with flask_app.test_request_context(f'/?search={oversized}'):
        bare_get_assignable_objects(request_user=MagicMock())

    forwarded: str = patched_orchestrator.call_args.kwargs['search']
    assert len(forwarded) == IpamSearch.MAX_QUERY_LENGTH
    assert forwarded == 'x' * IpamSearch.MAX_QUERY_LENGTH


def test_route_passes_through_search_at_or_below_max_query_length(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A search exactly at MAX_QUERY_LENGTH is forwarded unchanged - truncation is open-ended only"""
    at_limit: str = 'a' * IpamSearch.MAX_QUERY_LENGTH

    with flask_app.test_request_context(f'/?search={at_limit}'):
        bare_get_assignable_objects(request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == at_limit


# -------------------------------------------------------------------------------------------------------------------- #
#                                          page / page_size forwarding                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_forwards_default_page_and_page_size_when_not_provided(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """Missing page / page_size query params → 1 and IpamPagination.DEFAULT_PAGE_SIZE forwarded"""
    with flask_app.test_request_context('/'):
        bare_get_assignable_objects(request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['page'] == 1
    assert patched_orchestrator.call_args.kwargs['page_size'] == IpamPagination.DEFAULT_PAGE_SIZE


def test_route_reads_page_and_page_size_from_request_args_under_enum_keys(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """page / page_size are read under their IpamOverviewKey constants and forwarded as integers"""
    assert IpamOverviewKey.PAGE == 'page'
    assert IpamOverviewKey.PAGE_SIZE == 'page_size'

    with flask_app.test_request_context('/?page=3&page_size=25'):
        bare_get_assignable_objects(request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['page'] == 3
    assert patched_orchestrator.call_args.kwargs['page_size'] == 25


# -------------------------------------------------------------------------------------------------------------------- #
#                                       manager wiring + return value                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_forwards_resolved_managers_as_positional_arguments(
    bare_get_assignable_objects: Callable[..., Any],
    flask_app: Flask,
) -> None:
    """The objects + types managers come from ManagerProvider and arrive as positional args"""
    objects_manager_mock = MagicMock(name='objects_manager')
    types_manager_mock = MagicMock(name='types_manager')

    def _resolve(manager_type: Any, _user: Any) -> MagicMock:
        if manager_type == ManagerType.OBJECTS:
            return objects_manager_mock
        if manager_type == ManagerType.TYPES:
            return types_manager_mock
        return MagicMock()

    with patch(f'{ROUTE_PATH}.build_assignable_objects_page', return_value={'sentinel': True}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=_resolve):
        with flask_app.test_request_context('/'):
            bare_get_assignable_objects(request_user=MagicMock())

    args: tuple[Any, ...] = mock_build.call_args.args
    assert args[0] is objects_manager_mock
    assert args[1] is types_manager_mock
