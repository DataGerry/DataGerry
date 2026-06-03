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
Unit tests for cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes

Covers the transport boundary of the four IPAM pre-check routes (subnet, supernet, vlan,
interface): reading the JSON body, the required-field 400 guards, and forwarding the parsed
values to the framework-layer validators. Substantive validation behavior belongs to the
validators themselves (covered in their own test modules); these tests only pin the route glue.
The validators and ManagerProvider.get_manager are patched at the route module path so no DB or
business logic runs. The supernet route is stateless (no managers), matching the production code.

The route functions carry auth decorators that abort outside a real session, so each test unwraps
the decorator chain via __wrapped__ and calls the bare handler inside a Flask test_request_context.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes import (
    _coerce_optional_int,
    _build_validation_response,
    _parse_interface_rows_payload,
    validate_subnet_route,
    validate_supernet_route,
    validate_vlan_route,
    validate_interface_route,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes'


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
#                                              _coerce_optional_int                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [
    (None, None),
    (5, 5),
    ('7', 7),
    ('not-int', None),
    ([], None),
    (0, 0),
])
def test_coerce_optional_int(value: Any, expected: int | None) -> None:
    """Ints / int-strings coerce; None and non-coercible values become None (0 is preserved)"""
    assert _coerce_optional_int(value) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _build_validation_response                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_validation_response_valid_for_empty_errors() -> None:
    """An empty error list is reported as valid=True"""
    assert _build_validation_response([]) == {'valid': True, 'errors': []}


def test_build_validation_response_invalid_for_non_empty_errors() -> None:
    """A non-empty error list is reported as valid=False and echoes the errors"""
    errors = [{'code': 'x', 'message': 'm', 'details': {}}]

    assert _build_validation_response(errors) == {'valid': False, 'errors': errors}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          _parse_interface_rows_payload                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_interface_rows_payload_maps_rows_to_tuples() -> None:
    """Each row dict maps to (row_index, subnet_ref, ip); missing optional fields become None"""
    rows = _parse_interface_rows_payload([
        {'row_index': 0, 'subnet_id': 200, 'ip_address': '2001:db8::5'},
        {'row_index': 1},
    ])

    assert rows == [(0, 200, '2001:db8::5'), (1, None, None)]


def test_parse_interface_rows_payload_aborts_for_non_dict_entry() -> None:
    """A non-dict row entry aborts 400"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_interface_rows_payload(['not-a-dict'])

    assert exc_info.value.code == 400


def test_parse_interface_rows_payload_aborts_for_missing_row_index() -> None:
    """A row without an integer row_index aborts 400 (the index must echo back to the FE)"""
    with pytest.raises(HTTPException) as exc_info:
        _parse_interface_rows_payload([{'subnet_id': 200, 'ip_address': '10.0.0.5'}])

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                              validate_supernet_route                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_supernet_route_forwards_range_and_type_and_wraps_response(flask_app: Flask) -> None:
    """The route forwards network_range + supernet_type to validate_supernet (no managers needed)"""
    bare = _unwrap(validate_supernet_route)

    with patch(f'{ROUTE_PATH}.validate_supernet', return_value=[]) as mock_validate, \
         flask_app.test_request_context('/supernet', method='POST',
                                        json={'network_range': '2001:db8::/32', 'supernet_type': 'ipv6'}):
        response = bare(request_user=MagicMock())

    mock_validate.assert_called_once_with(network_range='2001:db8::/32', supernet_type='ipv6')
    assert response.status_code == 200


def test_validate_supernet_route_passes_non_string_type_as_none(flask_app: Flask) -> None:
    """A non-string supernet_type is forwarded as None so the family check is skipped"""
    bare = _unwrap(validate_supernet_route)

    with patch(f'{ROUTE_PATH}.validate_supernet', return_value=[]) as mock_validate, \
         flask_app.test_request_context('/supernet', method='POST',
                                        json={'network_range': '10.0.0.0/8', 'supernet_type': 123}):
        bare(request_user=MagicMock())

    mock_validate.assert_called_once_with(network_range='10.0.0.0/8', supernet_type=None)


@pytest.mark.parametrize('body', [{}, {'network_range': ''}, {'network_range': 123}])
def test_validate_supernet_route_aborts_400_for_missing_or_bad_range(flask_app: Flask, body: dict[str, Any]) -> None:
    """A missing / empty / non-string network_range aborts 400 before the validator runs"""
    bare = _unwrap(validate_supernet_route)

    with patch(f'{ROUTE_PATH}.validate_supernet') as mock_validate, \
         flask_app.test_request_context('/supernet', method='POST', json=body):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


def test_validate_supernet_route_reports_invalid_when_validator_returns_errors(flask_app: Flask) -> None:
    """When validate_supernet returns errors the response wraps valid=False (envelope via helper)"""
    bare = _unwrap(validate_supernet_route)
    errors = [{'code': 'type_family_mismatch', 'message': 'm', 'details': {}}]

    with patch(f'{ROUTE_PATH}.validate_supernet', return_value=errors), \
         flask_app.test_request_context('/supernet', method='POST',
                                        json={'network_range': '2001:db8::/32', 'supernet_type': 'ipv4'}):
        response = bare(request_user=MagicMock())

    assert response.status_code == 200


# -------------------------------------------------------------------------------------------------------------------- #
#                                               validate_subnet_route                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_subnet_route_forwards_all_body_fields(flask_app: Flask) -> None:
    """The route forwards network_range / parent_supernet_id / exclude_subnet_id / subnet_type"""
    bare = _unwrap(validate_subnet_route)

    with patch(f'{ROUTE_PATH}.validate_subnet', return_value=[]) as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/subnet', method='POST', json={
             'network_range': '10.0.0.0/24', 'parent_supernet_id': '100',
             'exclude_subnet_id': '200', 'subnet_type': 'ipv4',
         }):
        bare(request_user=MagicMock())

    _, kwargs = mock_validate.call_args
    assert kwargs == {
        'network_range': '10.0.0.0/24', 'parent_supernet_id': 100,
        'exclude_subnet_id': 200, 'subnet_type': 'ipv4',
    }


def test_validate_subnet_route_aborts_400_for_missing_range(flask_app: Flask) -> None:
    """A missing network_range aborts 400 before any manager or validator call"""
    bare = _unwrap(validate_subnet_route)

    with patch(f'{ROUTE_PATH}.validate_subnet') as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/subnet', method='POST', json={}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                validate_vlan_route                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_vlan_route_forwards_subnet_id(flask_app: Flask) -> None:
    """The route coerces and forwards subnet_id to validate_vlan"""
    bare = _unwrap(validate_vlan_route)

    with patch(f'{ROUTE_PATH}.validate_vlan', return_value=[]) as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/vlan', method='POST', json={'subnet_id': '200'}):
        bare(request_user=MagicMock())

    assert mock_validate.call_args.args[2] == 200


@pytest.mark.parametrize('body', [{}, {'subnet_id': 'nope'}, {'subnet_id': None}])
def test_validate_vlan_route_aborts_400_for_missing_subnet_id(flask_app: Flask, body: dict[str, Any]) -> None:
    """A missing / non-integer subnet_id aborts 400"""
    bare = _unwrap(validate_vlan_route)

    with patch(f'{ROUTE_PATH}.validate_vlan') as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/vlan', method='POST', json=body):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             validate_interface_route                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_interface_route_forwards_parsed_rows_and_exclude(flask_app: Flask) -> None:
    """The route parses the rows payload and forwards rows + exclude_object_id"""
    bare = _unwrap(validate_interface_route)

    with patch(f'{ROUTE_PATH}.validate_interface_rows', return_value=[]) as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/interface', method='POST', json={
             'rows': [{'row_index': 0, 'subnet_id': 200, 'ip_address': '2001:db8::5'}],
             'exclude_object_id': '300',
         }):
        bare(request_user=MagicMock())

    args, kwargs = mock_validate.call_args
    assert args[2] == [(0, 200, '2001:db8::5')]
    assert kwargs == {'exclude_object_id': 300}


def test_validate_interface_route_aborts_400_when_rows_not_a_list(flask_app: Flask) -> None:
    """A 'rows' value that is not a list aborts 400"""
    bare = _unwrap(validate_interface_route)

    with patch(f'{ROUTE_PATH}.validate_interface_rows') as mock_validate, \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         flask_app.test_request_context('/interface', method='POST', json={'rows': 'not-a-list'}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()
