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
Unit tests for cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes

Covers the route-glue of the SUBNET routes: get_subnet_overview reads page / page_size /
search / sort / order / status / type from the query string (applying the
IpamSearch.MAX_QUERY_LENGTH truncation) and forwards them; get_invalid_subnet_overview forwards
the page / search subset; unassign_ips_route forwards the body's 'ips' list and the request_user;
get_subnet_options forwards page / page_size / search / type and rejects invalid address-family
tokens with 400 before the builder runs.
Substantive behavior belongs to the framework-layer builders and is covered there; this module
only exercises the transport boundary. The framework helpers and ManagerProvider.get_manager are
patched at the route module path, and each route is unwrapped past its auth decorators.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.special_type_model.ipam_constants import IpAddressFamily, IpamPagination, IpamSearch
from cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes import (
    get_subnet_overview,
    get_subnet_options,
    get_invalid_subnet_overview,
    get_subnet_sector_ips,
    unassign_ips_route,
    export_subnet_ips,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes'
SUBNET_PUBLIC_ID: int = 5


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
#                                               get_subnet_overview                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_subnet_overview_forwards_all_query_params(flask_app: Flask) -> None:
    """Every query param is parsed and forwarded to build_subnet_overview under its keyword"""
    bare = _unwrap(get_subnet_overview)

    with patch(f'{ROUTE_PATH}.build_subnet_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(
             '/overview/5?page=2&page_size=10&search=db8&sort=ip&order=-1&status=assigned&type=50,51'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    args, kwargs = mock_build.call_args
    assert args[2] == SUBNET_PUBLIC_ID
    assert kwargs == {
        'page': 2, 'page_size': 10, 'search': 'db8', 'sort': 'ip',
        'order': '-1', 'status': 'assigned', 'type_filter': '50,51',
    }


def test_get_subnet_overview_applies_defaults_when_no_query_params(flask_app: Flask) -> None:
    """Absent params fall back to page 1 / default page size and empty filter strings"""
    bare = _unwrap(get_subnet_overview)

    with patch(f'{ROUTE_PATH}.build_subnet_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs == {
        'page': 1, 'page_size': IpamPagination.DEFAULT_PAGE_SIZE, 'search': '',
        'sort': '', 'order': '', 'status': '', 'type_filter': '',
    }


def test_get_subnet_overview_truncates_search_at_max_query_length(flask_app: Flask) -> None:
    """An over-long search is truncated to IpamSearch.MAX_QUERY_LENGTH at the route boundary"""
    bare = _unwrap(get_subnet_overview)
    long_search: str = 'a' * (IpamSearch.MAX_QUERY_LENGTH + 25)

    with patch(f'{ROUTE_PATH}.build_subnet_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/5?search={long_search}'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs['search'] == 'a' * IpamSearch.MAX_QUERY_LENGTH


# -------------------------------------------------------------------------------------------------------------------- #
#                                           get_invalid_subnet_overview                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_invalid_subnet_overview_forwards_page_size_and_search(flask_app: Flask) -> None:
    """The invalid-only route forwards the page / page_size / search subset"""
    bare = _unwrap(get_invalid_subnet_overview)

    with patch(f'{ROUTE_PATH}.build_invalid_ips_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/invalid?page=3&page_size=20&search=dead'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    args, kwargs = mock_build.call_args
    assert args[2] == SUBNET_PUBLIC_ID
    assert kwargs == {'page': 3, 'page_size': 20, 'search': 'dead'}


def test_get_invalid_subnet_overview_truncates_search_at_max_query_length(flask_app: Flask) -> None:
    """The invalid-only route applies the same search-length cap as the main overview"""
    bare = _unwrap(get_invalid_subnet_overview)
    long_search: str = 'b' * (IpamSearch.MAX_QUERY_LENGTH + 5)

    with patch(f'{ROUTE_PATH}.build_invalid_ips_overview', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/overview/5/invalid?search={long_search}'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs['search'] == 'b' * IpamSearch.MAX_QUERY_LENGTH


# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_subnet_sector_ips                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_subnet_sector_ips_forwards_sector_start_and_pagination(flask_app: Flask) -> None:
    """The sector route forwards public_id, sector_start and page/page_size to the builder"""
    bare = _unwrap(get_subnet_sector_ips)

    with patch(f'{ROUTE_PATH}.build_subnet_sector_ips', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/sector?sector_start=2001:db8::&page=2&page_size=10'):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    args, kwargs = mock_build.call_args
    assert args[2] == SUBNET_PUBLIC_ID
    assert args[3] == '2001:db8::'
    assert kwargs == {'page': 2, 'page_size': 10}


def test_get_subnet_sector_ips_aborts_400_when_sector_start_missing(flask_app: Flask) -> None:
    """A request without sector_start aborts 400 before the builder runs"""
    bare = _unwrap(get_subnet_sector_ips)

    with patch(f'{ROUTE_PATH}.build_subnet_sector_ips') as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/sector'):
        with pytest.raises(HTTPException) as exc_info:
            bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_build.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               unassign_ips_route                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_ips_route_forwards_public_id_ips_and_user(flask_app: Flask) -> None:
    """The route forwards public_id, the body's 'ips' list and the request_user to the unassigner"""
    bare = _unwrap(unassign_ips_route)
    request_user = MagicMock()

    with patch(f'{ROUTE_PATH}.unassign_ips_from_subnet', return_value={}) as mock_unassign, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/unassign', method='POST',
                                        json={'ips': ['2001:db8::5', '2001:db8::6']}):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=request_user)

    args = mock_unassign.call_args.args
    assert args[2] == SUBNET_PUBLIC_ID
    assert args[3] == ['2001:db8::5', '2001:db8::6']
    assert args[4] is request_user


def test_unassign_ips_route_forwards_none_when_ips_key_absent(flask_app: Flask) -> None:
    """A body without an 'ips' key forwards None so the unassigner emits its own 400"""
    bare = _unwrap(unassign_ips_route)

    with patch(f'{ROUTE_PATH}.unassign_ips_from_subnet', return_value={}) as mock_unassign, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/unassign', method='POST', json={}):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    assert mock_unassign.call_args.args[3] is None


def test_unassign_ips_route_forwards_mode_to_unassigner(flask_app: Flask) -> None:
    """The body's 'mode' is forwarded as raw_mode; absent it forwards None (unassigner defaults it)"""
    bare = _unwrap(unassign_ips_route)

    with patch(f'{ROUTE_PATH}.unassign_ips_from_subnet', return_value={}) as mock_unassign, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/unassign', method='POST',
                                        json={'ips': ['10.0.0.1'], 'mode': 'row'}):
        bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    assert mock_unassign.call_args.kwargs == {'raw_mode': 'row'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                               export_subnet_ips                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_export_subnet_ips_returns_csv_attachment(flask_app: Flask) -> None:
    """The route streams the builder's bytes as a .csv attachment with a filename"""
    bare = _unwrap(export_subnet_ips)

    with patch(f'{ROUTE_PATH}.build_subnet_ips_csv', return_value=b'csv-bytes') as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/export'):
        response = bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())

    assert mock_build.call_args.args[2] == SUBNET_PUBLIC_ID
    assert response.get_data() == b'csv-bytes'
    assert response.mimetype == 'text/csv'
    disposition: str = response.headers['Content-Disposition']
    assert 'attachment; filename=subnet_5_ips_' in disposition
    assert disposition.endswith('.csv')


def test_export_subnet_ips_propagates_too_big_abort(flask_app: Flask) -> None:
    """A 400 raised by the builder (subnet too big) propagates out instead of becoming a 500"""
    bare = _unwrap(export_subnet_ips)

    with patch(f'{ROUTE_PATH}.build_subnet_ips_csv', side_effect=HTTPException(), ), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/overview/5/export'):
        with pytest.raises(HTTPException):
            bare(public_id=SUBNET_PUBLIC_ID, request_user=MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                               get_subnet_options                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
INVALID_FAMILY_TOKEN: str = 'ipv5'


def test_get_subnet_options_forwards_all_query_params(flask_app: Flask) -> None:
    """page / page_size / search / type are parsed and forwarded to the builder as keywords"""
    bare = _unwrap(get_subnet_options)

    with patch(f'{ROUTE_PATH}.build_subnet_options_page', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/?page=3&page_size=20&search=db8&type={IpAddressFamily.IPV6.value}'):
        bare(request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs == {
        'page': 3, 'page_size': 20, 'search': 'db8', 'family': IpAddressFamily.IPV6.value,
    }


def test_get_subnet_options_applies_defaults_when_no_query_params(flask_app: Flask) -> None:
    """Absent params fall back to page 1, the default page size, empty search and no family"""
    bare = _unwrap(get_subnet_options)

    with patch(f'{ROUTE_PATH}.build_subnet_options_page', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/'):
        bare(request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs == {
        'page': 1, 'page_size': IpamPagination.DEFAULT_PAGE_SIZE, 'search': '', 'family': '',
    }


def test_get_subnet_options_truncates_search_at_max_query_length(flask_app: Flask) -> None:
    """An over-long search is truncated to IpamSearch.MAX_QUERY_LENGTH at the route boundary"""
    bare = _unwrap(get_subnet_options)
    long_search: str = 'd' * (IpamSearch.MAX_QUERY_LENGTH + 15)

    with patch(f'{ROUTE_PATH}.build_subnet_options_page', return_value={}) as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/?search={long_search}'):
        bare(request_user=MagicMock())

    _, kwargs = mock_build.call_args
    assert kwargs['search'] == 'd' * IpamSearch.MAX_QUERY_LENGTH


def test_get_subnet_options_aborts_400_on_invalid_family_token(flask_app: Flask) -> None:
    """A 'type' value outside IpAddressFamily aborts 400 before the builder runs"""
    bare = _unwrap(get_subnet_options)

    with patch(f'{ROUTE_PATH}.build_subnet_options_page') as mock_build, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context(f'/?type={INVALID_FAMILY_TOKEN}'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_build.assert_not_called()


def test_get_subnet_options_accepts_both_valid_family_tokens(flask_app: Flask) -> None:
    """Both IpAddressFamily values pass validation and reach the builder"""
    bare = _unwrap(get_subnet_options)

    for token in (IpAddressFamily.IPV4.value, IpAddressFamily.IPV6.value):
        with patch(f'{ROUTE_PATH}.build_subnet_options_page', return_value={}) as mock_build, \
             patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
             flask_app.test_request_context(f'/?type={token}'):
            bare(request_user=MagicMock())

        assert mock_build.call_args.kwargs['family'] == token
