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
The validators and `read_ipam_managers` are patched at the route module path so no DB or business
logic runs. The supernet route is stateless (no managers), matching the production code.

The route functions carry auth decorators that abort outside a real session, so each test unwraps
the decorator chain via __wrapped__ and calls the bare handler inside a Flask test_request_context.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.utils import coerce_whole_number
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_helper import (
    parse_interface_rows_payload,
    read_optional_object_id,
    read_required_object_id,
    read_required_string,
)
from cmdb.interface.rest_api.routes.ipam_routes.ipam_validation_routes import (
    _build_validation_response,
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
#                                    the id coercion these routes now share                                            #
# -------------------------------------------------------------------------------------------------------------------- #
# The routes used to carry their own `_coerce_optional_int`; it was a third copy of the project-wide
# `coerce_whole_number` and disagreed with the others on booleans. These cases are the ones that
# matter to an IPAM id specifically - the caster's own behaviour is covered in the utils suite
@pytest.mark.parametrize('value, expected', [
    (None, None),
    (5, 5),
    ('7', 7),
    ('not-int', None),
    ([], None),
    (0, 0),
])
def test_the_shared_caster_keeps_the_old_accepted_cases(value: Any, expected: int | None) -> None:
    """Every case the routes' own coercion handled is handled the same way by the shared one"""
    assert coerce_whole_number(value) == expected


@pytest.mark.parametrize('value', [True, False])
def test_a_json_boolean_is_not_an_id(value: bool) -> None:
    """
    The bug the shared caster fixes

    bool is an int subclass in Python, so the routes' own `int(value)` turned `subnet_id: true` into
    the id 1 and validated a candidate against whichever object happens to be object 1.
    """
    assert coerce_whole_number(value) is None


@pytest.mark.parametrize('value, expected', [(42.0, 42), (42.5, None), ('42.0', 42), ('42.5', None)])
def test_a_fractional_value_is_not_an_id(value: Any, expected: int | None) -> None:
    """
    A float that is a whole number is an id; one with a fraction is refused, not truncated

    `int(42.5)` is 42, so the old coercion would have validated against a different object than the
    caller named.
    """
    assert coerce_whole_number(value) == expected


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
#                                           parse_interface_rows_payload                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parse_interface_rows_payload_maps_rows_to_tuples() -> None:
    """Each row dict maps to (row_index, subnet_ref, ip, interface_type); missing fields become None"""
    rows = parse_interface_rows_payload([
        {'row_index': 0, 'subnet_id': 200, 'ip_address': '2001:db8::5'},
        {'row_index': 1},
    ])

    assert rows == [(0, 200, '2001:db8::5', None), (1, None, None, None)]


def test_parse_interface_rows_payload_passes_interface_type_through() -> None:
    """A non-empty 'interface_type' lands in the fourth tuple slot; an empty one becomes None"""
    rows = parse_interface_rows_payload([
        {'row_index': 0, 'subnet_id': 200, 'ip_address': '2001:db8::5', 'interface_type': 'ipv6'},
        {'row_index': 1, 'interface_type': ''},
    ])

    assert rows == [(0, 200, '2001:db8::5', 'ipv6'), (1, None, None, None)]


def test_parse_interface_rows_payload_aborts_for_non_dict_entry() -> None:
    """A non-dict row entry aborts 400"""
    with pytest.raises(HTTPException) as exc_info:
        parse_interface_rows_payload(['not-a-dict'])

    assert exc_info.value.code == 400


def test_parse_interface_rows_payload_aborts_for_missing_row_index() -> None:
    """A row without an integer row_index aborts 400 (the index must echo back to the FE)"""
    with pytest.raises(HTTPException) as exc_info:
        parse_interface_rows_payload([{'subnet_id': 200, 'ip_address': '10.0.0.5'}])

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
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
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
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
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
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/vlan', method='POST', json={'subnet_id': '200'}):
        bare(request_user=MagicMock())

    assert mock_validate.call_args.args[2] == 200


@pytest.mark.parametrize('body', [{}, {'subnet_id': 'nope'}, {'subnet_id': None}])
def test_validate_vlan_route_aborts_400_for_missing_subnet_id(flask_app: Flask, body: dict[str, Any]) -> None:
    """A missing / non-integer subnet_id aborts 400"""
    bare = _unwrap(validate_vlan_route)

    with patch(f'{ROUTE_PATH}.validate_vlan') as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
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
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/interface', method='POST', json={
             'rows': [{'row_index': 0, 'subnet_id': 200, 'ip_address': '2001:db8::5'}],
             'exclude_object_id': '300',
         }):
        bare(request_user=MagicMock())

    args, kwargs = mock_validate.call_args
    assert args[2] == [(0, 200, '2001:db8::5', None)]
    assert kwargs == {'exclude_object_id': 300}


def test_validate_interface_route_aborts_400_when_rows_not_a_list(flask_app: Flask) -> None:
    """A 'rows' value that is not a list aborts 400"""
    bare = _unwrap(validate_interface_route)

    with patch(f'{ROUTE_PATH}.validate_interface_rows') as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/interface', method='POST', json={'rows': 'not-a-list'}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                 the body readers these four routes share                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadRequiredString:
    """read_required_string refuses everything a validator could not parse a CIDR out of."""

    def test_returns_the_value(self) -> None:
        """A non-empty string is handed back unchanged"""
        assert read_required_string({'network_range': '10.0.0.0/24'}, 'network_range') == '10.0.0.0/24'

    @pytest.mark.parametrize('payload', [{}, {'network_range': None}, {'network_range': ''},
                                         {'network_range': 24}, {'network_range': ['10.0.0.0/24']}])
    def test_aborts_400_for_anything_else(self, payload: dict[str, Any]) -> None:
        """Absent, null, empty and non-string are one refusal - none of them is a candidate"""
        with pytest.raises(HTTPException) as exc_info:
            read_required_string(payload, 'network_range')

        assert exc_info.value.code == 400
        assert 'network_range' in exc_info.value.description


class TestReadRequiredObjectId:
    """read_required_object_id refuses an absent or unusable id."""

    @pytest.mark.parametrize('raw, expected', [(42, 42), ('42', 42), (42.0, 42), (0, 0)])
    def test_returns_the_id(self, raw: Any, expected: int) -> None:
        """Whatever the id was serialised as, it comes back as a number"""
        assert read_required_object_id({'subnet_id': raw}, 'subnet_id') == expected

    @pytest.mark.parametrize('payload', [{}, {'subnet_id': None}, {'subnet_id': 'abc'},
                                         {'subnet_id': True}, {'subnet_id': 4.5}])
    def test_aborts_400_for_anything_else(self, payload: dict[str, Any]) -> None:
        """Absent and unusable are the same refusal here, because the field is required either way"""
        with pytest.raises(HTTPException) as exc_info:
            read_required_object_id(payload, 'subnet_id')

        assert exc_info.value.code == 400


class TestReadOptionalObjectId:
    """
    read_optional_object_id separates "not sent" from "sent as something unusable".

    That separation is the fix for the wrong-answer bug: on a pre-check route an unreadable
    exclude id read as "nothing to exclude" makes the validator compare a candidate against
    itself and answer "invalid" for an edit that is fine.
    """

    @pytest.mark.parametrize('raw, expected', [(42, 42), ('42', 42), (42.0, 42), (0, 0)])
    def test_returns_the_id(self, raw: Any, expected: int) -> None:
        """A usable id comes back as a number"""
        assert read_optional_object_id({'exclude_subnet_id': raw}, 'exclude_subnet_id') == expected

    @pytest.mark.parametrize('payload', [{}, {'exclude_subnet_id': None}])
    def test_absent_or_null_means_none(self, payload: dict[str, Any]) -> None:
        """Omitting the field is legal and means 'nothing to exclude'"""
        assert read_optional_object_id(payload, 'exclude_subnet_id') is None

    @pytest.mark.parametrize('raw', ['', 'abc', True, False, 4.5, [], {}])
    def test_aborts_400_when_present_but_unusable(self, raw: Any) -> None:
        """
        Sent-but-unreadable is refused rather than silently read as absent

        This is the whole point of the helper: `''` from a form field and `'abc'` from a typo used
        to become None, which changed the validator's ANSWER instead of failing the request.
        """
        with pytest.raises(HTTPException) as exc_info:
            read_optional_object_id({'exclude_subnet_id': raw}, 'exclude_subnet_id')

        assert exc_info.value.code == 400
        assert 'exclude_subnet_id' in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                        an unusable id changes the ANSWER, so the route refuses it                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('field', ['parent_supernet_id', 'exclude_subnet_id'])
@pytest.mark.parametrize('raw', ['', 'abc', True])
def test_validate_subnet_route_aborts_400_for_an_unusable_id(
    flask_app: Flask,
    field: str,
    raw: Any,
) -> None:
    """
    The subnet pre-check refuses an unreadable id instead of validating without it

    With `exclude_subnet_id` dropped the candidate is compared against its own stored row, so the
    route would answer "overlaps" for an edit that changes nothing - a wrong answer, from a request
    that was never usable.
    """
    bare = _unwrap(validate_subnet_route)

    with patch(f'{ROUTE_PATH}.validate_subnet') as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/subnet', method='POST', json={
             'network_range': '10.0.0.0/24', 'subnet_type': 'ipv4', field: raw,
         }):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


@pytest.mark.parametrize('raw', ['', 'abc', True])
def test_validate_interface_route_aborts_400_for_an_unusable_exclude_id(flask_app: Flask, raw: Any) -> None:
    """The interface pre-check refuses an unreadable exclude_object_id for the same reason"""
    bare = _unwrap(validate_interface_route)

    with patch(f'{ROUTE_PATH}.validate_interface_rows') as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/interface', method='POST', json={
             'rows': [], 'exclude_object_id': raw,
         }):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


@pytest.mark.parametrize('raw', [True, False])
def test_validate_vlan_route_aborts_400_for_a_boolean_subnet_id(flask_app: Flask, raw: bool) -> None:
    """
    `subnet_id: true` used to validate against object 1

    bool is an int subclass, so the route's own `int(value)` accepted it and the `is None` guard
    never fired - the customer got a confident answer about a subnet they never named.
    """
    bare = _unwrap(validate_vlan_route)

    with patch(f'{ROUTE_PATH}.validate_vlan') as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/vlan', method='POST', json={'subnet_id': raw}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    mock_validate.assert_not_called()


def test_validate_interface_route_tolerates_an_unusable_row_subnet_id(flask_app: Flask) -> None:
    """
    A row's own subnet_id is deliberately NOT refused - the asymmetry is intentional

    The caller is a form being typed into, so a half-filled row reads as "not filled in yet" and is
    skipped by the per-row check, exactly as it is at save time. Only the request-level ids are
    strict.
    """
    bare = _unwrap(validate_interface_route)

    with patch(f'{ROUTE_PATH}.validate_interface_rows', return_value=[]) as mock_validate, \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context('/interface', method='POST', json={
             'rows': [{'row_index': 0, 'subnet_id': 'not-an-id', 'ip_address': '10.0.0.5'}],
         }):
        bare(request_user=MagicMock())

    assert mock_validate.call_args.args[2] == [(0, None, '10.0.0.5', None)]


def test_parse_interface_rows_payload_aborts_for_a_boolean_row_index() -> None:
    """A row_index of `true` is not row 1 - it is a refusal, for the same reason as the ids"""
    with pytest.raises(HTTPException) as exc_info:
        parse_interface_rows_payload([{'row_index': True, 'subnet_id': 1, 'ip_address': '10.0.0.5'}])

    assert exc_info.value.code == 400


def test_parse_interface_rows_payload_aborts_for_a_fractional_row_index() -> None:
    """A fractional row_index would silently truncate onto a neighbouring row"""
    with pytest.raises(HTTPException) as exc_info:
        parse_interface_rows_payload([{'row_index': 1.5, 'subnet_id': 1, 'ip_address': '10.0.0.5'}])

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                         the shared error tail: a 400/404 propagates, anything else is a 500                          #
# -------------------------------------------------------------------------------------------------------------------- #
# One case per route: these four `except Exception -> abort(500)` arms were the file's only uncovered
# statements, and they are the whole difference between a client seeing the framework's own message and
# seeing a generic server error
ERROR_TAIL_CASES: list[tuple[Callable[..., Any], str, str, dict[str, Any]]] = [
    (validate_subnet_route, 'validate_subnet', '/subnet',
     {'network_range': '10.0.0.0/24', 'subnet_type': 'ipv4'}),
    (validate_supernet_route, 'validate_supernet', '/supernet',
     {'network_range': '10.0.0.0/8', 'supernet_type': 'ipv4'}),
    (validate_vlan_route, 'validate_vlan', '/vlan', {'subnet_id': 200}),
    (validate_interface_route, 'validate_interface_rows', '/interface', {'rows': []}),
]


@pytest.mark.parametrize('route, validator_name, path, body', ERROR_TAIL_CASES)
def test_an_unexpected_error_becomes_a_500(
    flask_app: Flask,
    route: Callable[..., Any],
    validator_name: str,
    path: str,
    body: dict[str, Any],
) -> None:
    """A validator blowing up is a 500, not a leaked traceback or a misleading 400"""
    bare = _unwrap(route)

    with patch(f'{ROUTE_PATH}.{validator_name}', side_effect=RuntimeError('boom')), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context(path, method='POST', json=body):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500


@pytest.mark.parametrize('route, validator_name, path, body', ERROR_TAIL_CASES)
def test_an_httpexception_from_a_validator_propagates_untouched(
    flask_app: Flask,
    route: Callable[..., Any],
    validator_name: str,
    path: str,
    body: dict[str, Any],
) -> None:
    """
    The framework layer's own aborts must reach the client as themselves

    Without the `except HTTPException: raise` arm in front of the catch-all, a 404 raised by a
    validator would be reported as an internal server error.
    """
    bare = _unwrap(route)
    raised = NotFound('Subnet with public_id 200 was not found!')

    with patch(f'{ROUTE_PATH}.{validator_name}', side_effect=raised), \
         patch(f'{ROUTE_PATH}.read_ipam_managers', return_value=(MagicMock(), MagicMock())), \
         flask_app.test_request_context(path, method='POST', json=body):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value is raised
