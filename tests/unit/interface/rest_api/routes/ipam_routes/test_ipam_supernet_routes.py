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
Unit tests for cmdb.interface.rest_api.routes.ipam_routes.ipam_supernet_routes

Covers the route-glue responsibilities of all five SUPERNET routes: get_supernet_overview and
get_invalid_subnet_overview read page / page_size / search from the query string under their
IpamOverviewKey constants and apply the IpamSearch.MAX_QUERY_LENGTH truncation cap;
get_supernet_subnet_children forwards both path ids; unassign_subnets_route forwards the
body's 'subnet_ids' list (None when absent); export_supernet_subnets streams the workbook as
an attachment. Substantive behavior (top-level vs. flat list, minimum query length, KPI
computation, containment, detach semantics) belongs to the framework-layer builders and is
covered in the framework-layer tests; this module only exercises the transport boundary

The route function carries auth decorators that abort outside a real session, so each test
unwraps the decorator chain via __wrapped__ and calls the bare handler inside a Flask
test_request_context. build_supernet_overview and ManagerProvider.get_manager are patched at
the route module path so no DB or business logic runs
"""
from typing import Any, Callable
import csv
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.models.special_type_model.ipam_constants import (
    IpamPagination,
    IpamSearch,
    IpamOverviewKey,
    IpamExport,
    IpamUnassignKey,
    IpAddressFamily,
)
from cmdb.interface.rest_api.routes.ipam_routes.ipam_supernet_routes import (
    get_supernet_overview,
    get_supernet_subnet_children,
    get_invalid_subnet_overview,
    unassign_subnets_route,
    export_supernet_subnets,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_supernet_routes'
SUPERNET_PUBLIC_ID: int = 42
SUBNET_PUBLIC_ID: int = 7


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the @verify_api_access / @insert_request_user decorators off a route function."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='bare_get_supernet_overview')
def fixture_bare_get_supernet_overview() -> Callable[..., Any]:
    """Returns the undecorated get_supernet_overview handler, callable inside a request context."""
    return _unwrap(get_supernet_overview)


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Returns a minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='patched_orchestrator')
def fixture_patched_orchestrator() -> Any:
    """
    Patches build_supernet_overview and ManagerProvider.get_manager at the route module path

    The orchestrator returns a sentinel payload so the route's DefaultResponse wrapper has
    something to serialise; tests assert against the captured kwargs on the orchestrator mock
    """
    payload: dict[str, Any] = {'sentinel': True}

    with patch(f'{ROUTE_PATH}.build_supernet_overview', return_value=payload) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()):
        yield mock_build


# -------------------------------------------------------------------------------------------------------------------- #
#                                            search query-param forwarding                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_forwards_search_query_param_to_orchestrator(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A 'search=10.0' query param is read under IpamOverviewKey.SEARCH and forwarded verbatim"""
    with flask_app.test_request_context('/?search=10.0'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == '10.0'


def test_route_forwards_empty_search_when_query_param_missing(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """Missing 'search' query param → empty string forwarded so the framework restores top-level view"""
    with flask_app.test_request_context('/'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == ''


def test_route_truncates_search_at_max_query_length(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A search longer than IpamSearch.MAX_QUERY_LENGTH is truncated at the route boundary"""
    oversized: str = 'x' * (IpamSearch.MAX_QUERY_LENGTH + 50)

    with flask_app.test_request_context(f'/?search={oversized}'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    forwarded: str = patched_orchestrator.call_args.kwargs['search']
    assert len(forwarded) == IpamSearch.MAX_QUERY_LENGTH
    assert forwarded == 'x' * IpamSearch.MAX_QUERY_LENGTH


def test_route_passes_through_search_at_or_below_max_query_length(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """A search exactly at MAX_QUERY_LENGTH is forwarded unchanged - truncation is open-ended only"""
    at_limit: str = 'a' * IpamSearch.MAX_QUERY_LENGTH

    with flask_app.test_request_context(f'/?search={at_limit}'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['search'] == at_limit


# -------------------------------------------------------------------------------------------------------------------- #
#                                          page / page_size forwarding                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_route_forwards_default_page_and_page_size_when_not_provided(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """Missing page / page_size query params → 1 and IpamPagination.DEFAULT_PAGE_SIZE forwarded"""
    with flask_app.test_request_context('/'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['page'] == 1
    assert patched_orchestrator.call_args.kwargs['page_size'] == IpamPagination.DEFAULT_PAGE_SIZE


def test_route_reads_page_and_page_size_from_request_args_under_enum_keys(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """page / page_size are read under their IpamOverviewKey constants and forwarded as integers"""
    assert IpamOverviewKey.PAGE == 'page'
    assert IpamOverviewKey.PAGE_SIZE == 'page_size'

    with flask_app.test_request_context('/?page=3&page_size=25'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.kwargs['page'] == 3
    assert patched_orchestrator.call_args.kwargs['page_size'] == 25


def test_route_forwards_public_id_argument_to_orchestrator(
    bare_get_supernet_overview: Callable[..., Any],
    flask_app: Flask,
    patched_orchestrator: Any,
) -> None:
    """The path's public_id flows through to build_supernet_overview as the third positional arg"""
    with flask_app.test_request_context('/'):
        bare_get_supernet_overview(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert patched_orchestrator.call_args.args[2] == SUPERNET_PUBLIC_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                          export_supernet_subnets                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='bare_export_supernet_subnets')
def fixture_bare_export_supernet_subnets() -> Callable[..., Any]:
    """Returns the undecorated export_supernet_subnets handler."""
    return _unwrap(export_supernet_subnets)


def test_export_route_returns_csv_attachment_download(
    bare_export_supernet_subnets: Callable[..., Any],
    flask_app: Flask,
) -> None:
    """The route returns the builder's bytes as a .csv attachment with the CSV mimetype"""
    content: bytes = b'fake-csv-bytes'

    with patch(f'{ROUTE_PATH}.build_supernet_subnets_csv', return_value=content) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/'):
        response = bare_export_supernet_subnets(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert response.mimetype == IpamExport.MIMETYPE
    assert response.data == content

    disposition: str = response.headers['Content-Disposition']
    assert disposition.startswith('attachment; filename=')
    assert f'supernet_{SUPERNET_PUBLIC_ID}_subnets_' in disposition
    assert disposition.endswith('.csv')

    mock_build.assert_called_once()


def test_export_route_body_parses_as_valid_csv(
    bare_export_supernet_subnets: Callable[..., Any],
    flask_app: Flask,
) -> None:
    """End-to-end: with the real builder, the route's body is parseable CSV with the expected rows"""
    rows: list[dict[str, Any]] = [{
        IpamOverviewKey.CIDR: '10.0.0.0/24',
        IpamOverviewKey.IP_RANGE: {IpamOverviewKey.FIRST: '10.0.0.0', IpamOverviewKey.LAST: '10.0.0.255'},
        IpamOverviewKey.USED_IPS: 3,
        IpamOverviewKey.FREE_IPS: 253,
        IpamOverviewKey.USAGE_PERCENT: 1.17,
    }]

    # Patch the data source + the family resolver (IPv4) so the real build runs and emits real bytes
    with patch('cmdb.framework.ipam.subnet_export.load_assigned_subnet_rows', return_value=rows), \
         patch('cmdb.framework.ipam.subnet_export.resolve_supernet_family', return_value=IpAddressFamily.IPV4), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/'):
        response = bare_export_supernet_subnets(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    csv_rows: list[list[str]] = list(csv.reader(StringIO(response.data.decode('utf-8'))))

    # IPv4 supernet export keeps the trailing 'Usage (%)' column; CSV cells are text
    assert csv_rows[0] == IpamExport.HEADERS + [IpamExport.USAGE_HEADER]
    assert csv_rows[1] == ['10.0.0.0/24', '10.0.0.0 - 10.0.0.255', '3', '253', '1.17']


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_supernet_subnet_children                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_children_route_forwards_both_path_ids_to_the_builder(flask_app: Flask) -> None:
    """The route passes the supernet and subnet public_ids (after the managers) to the builder"""
    bare = _unwrap(get_supernet_subnet_children)

    with patch(f'{ROUTE_PATH}.build_supernet_subnet_children', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/children/{SUBNET_PUBLIC_ID}'):
        bare(public_id=SUPERNET_PUBLIC_ID, subnet_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    args = mock_build.call_args.args
    assert args[2] == SUPERNET_PUBLIC_ID
    assert args[3] == SUBNET_PUBLIC_ID


def test_children_route_passes_builder_aborts_through(flask_app: Flask) -> None:
    """An HTTPException from the builder (e.g. 400 for a foreign subnet) is re-raised, not wrapped"""
    bare = _unwrap(get_supernet_subnet_children)

    with patch(f'{ROUTE_PATH}.build_supernet_subnet_children', side_effect=BadRequest('foreign')), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/children/{SUBNET_PUBLIC_ID}'):
        with pytest.raises(HTTPException) as exc_info:
            bare(public_id=SUPERNET_PUBLIC_ID, subnet_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                           get_invalid_subnet_overview                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_invalid_route_forwards_page_page_size_and_search(flask_app: Flask) -> None:
    """The invalid-only route forwards public_id plus the page / page_size / search subset"""
    bare = _unwrap(get_invalid_subnet_overview)

    with patch(f'{ROUTE_PATH}.build_invalid_subnets_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(
             f'/overview/{SUPERNET_PUBLIC_ID}/subnets/invalid?page=2&page_size=25&search=10.0'):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    args, kwargs = mock_build.call_args
    assert args[2] == SUPERNET_PUBLIC_ID
    assert kwargs == {'page': 2, 'page_size': 25, 'search': '10.0'}


def test_invalid_route_applies_defaults_when_no_query_params(flask_app: Flask) -> None:
    """Absent params fall back to page 1, the default page size and an empty search"""
    bare = _unwrap(get_invalid_subnet_overview)

    with patch(f'{ROUTE_PATH}.build_invalid_subnets_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/invalid'):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs == {'page': 1, 'page_size': IpamPagination.DEFAULT_PAGE_SIZE, 'search': ''}


def test_invalid_route_truncates_search_at_max_query_length(flask_app: Flask) -> None:
    """The invalid-only route applies the same search-length cap as the main overview"""
    bare = _unwrap(get_invalid_subnet_overview)
    long_search: str = 'c' * (IpamSearch.MAX_QUERY_LENGTH + 10)

    with patch(f'{ROUTE_PATH}.build_invalid_subnets_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/invalid?search={long_search}'):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs['search'] == 'c' * IpamSearch.MAX_QUERY_LENGTH


# -------------------------------------------------------------------------------------------------------------------- #
#                                             unassign_subnets_route                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_route_forwards_public_id_and_subnet_ids(flask_app: Flask) -> None:
    """The route forwards the supernet public_id and the body's 'subnet_ids' list verbatim"""
    bare = _unwrap(unassign_subnets_route)
    subnet_ids: list[int] = [SUBNET_PUBLIC_ID, SUBNET_PUBLIC_ID + 1]

    with patch(f'{ROUTE_PATH}.unassign_subnets_from_supernet', return_value={}) as mock_unassign, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/unassign', method='POST',
                                        json={IpamUnassignKey.SUBNET_IDS: subnet_ids}):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    args = mock_unassign.call_args.args
    assert args[2] == SUPERNET_PUBLIC_ID
    assert args[3] == subnet_ids


def test_unassign_route_forwards_none_when_subnet_ids_key_absent(flask_app: Flask) -> None:
    """A body without 'subnet_ids' (or no JSON body at all) forwards None so the detacher emits its own 400"""
    bare = _unwrap(unassign_subnets_route)

    with patch(f'{ROUTE_PATH}.unassign_subnets_from_supernet', return_value={}) as mock_unassign, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/unassign', method='POST', json={}):
        bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert mock_unassign.call_args.args[3] is None


def test_unassign_route_passes_builder_aborts_through(flask_app: Flask) -> None:
    """An HTTPException from the detacher (e.g. 400 for foreign ids) is re-raised, not wrapped"""
    bare = _unwrap(unassign_subnets_route)

    with patch(f'{ROUTE_PATH}.unassign_subnets_from_supernet', side_effect=BadRequest('foreign')), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/{SUPERNET_PUBLIC_ID}/subnets/unassign', method='POST',
                                        json={IpamUnassignKey.SUBNET_IDS: [SUBNET_PUBLIC_ID]}):
        with pytest.raises(HTTPException) as exc_info:
            bare(public_id=SUPERNET_PUBLIC_ID, request_user=MagicMock())

    assert exc_info.value.code == 400
