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
Unit tests for cmdb.interface.rest_api.routes.config_routes.config_file_routes

Covers the OpenCelium config-status route and its two helpers. `SystemConfigReader` is patched at
the route module path, so no config file is read and no process-wide singleton is touched; the
route's own answer-shaping is what is pinned here.

The route carries auth decorators that abort outside a real session, so each test unwraps the
decorator chain via __wrapped__ and calls the bare handler inside a Flask test_request_context.
The hosting app carries a `cloud_mode` flag because the route branches on it, mirroring
`BaseCmdbApp`.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.config_routes.config_file_routes import (
    _is_configured,
    _is_valid_port,
    get_oc_config_status,
)
from cmdb.errors.system_config import ConfigNotLoaded, SectionError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.config_routes.config_file_routes'

COMPLETE_SECTION: dict[str, Any] = {
    'host': '127.0.0.1',
    'port': 9090,
    'protocol': 'http',
    'email': 'oc@example.com',
    'user': 'oc-user',
    'password': 'oc-password',
}

ALL_KEYS: tuple[str, ...] = ('host', 'port', 'protocol', 'email', 'user', 'password')


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the @verify_api_access / @insert_request_user decorators off a route function."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Returns a minimal Flask app carrying the cloud_mode flag the route reads."""
    app = Flask(__name__)
    app.cloud_mode = False

    return app


def _call_route(flask_app: Flask, section_values: dict[str, Any] | Exception) -> dict[str, Any]:
    """Runs the bare route against a patched reader and returns the decoded response body."""
    bare = _unwrap(get_oc_config_status)
    reader = MagicMock()

    if isinstance(section_values, Exception):
        reader.get_all_values_from_section.side_effect = section_values
    else:
        reader.get_all_values_from_section.return_value = section_values

    with patch(f'{ROUTE_PATH}.SystemConfigReader', return_value=reader), \
         flask_app.test_request_context('/status/opencelium'):
        response = bare(request_user=MagicMock())

    assert response.status_code == 200

    return response.get_json()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   _is_configured                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [
    (None, False),
    ('', False),
    ('   ', False),
    ('127.0.0.1', True),
    (9090, True),
    (0, True),
    (False, True),
])
def test_is_configured(value: Any, expected: bool) -> None:
    """Only an absent or blank value counts as unconfigured - a literal 0 / false is a real value"""
    assert _is_configured(value) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   _is_valid_port                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [
    (9090, True),
    ('9090', True),
    (9090.0, True),
    (1, True),
    (0, False),
    (-1, False),
    (None, False),
    ('', False),
    ('not-a-port', False),
    (80.5, False),
    (True, False),
])
def test_is_valid_port(value: Any, expected: bool) -> None:
    """A port must be a whole number of at least 1; bools and fractions are not ports"""
    assert _is_valid_port(value) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_oc_config_status                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_reports_ready_for_a_complete_section(flask_app: Flask) -> None:
    """A fully filled section reports every flag - and the overall status - as True"""
    body = _call_route(flask_app, COMPLETE_SECTION)

    assert body == {'status': True, 'section': True, **{key: True for key in ALL_KEYS}}


def test_reads_the_section_once(flask_app: Flask) -> None:
    """The whole section is read in a single call instead of one get_value per setting"""
    bare = _unwrap(get_oc_config_status)
    reader = MagicMock()
    reader.get_all_values_from_section.return_value = COMPLETE_SECTION

    with patch(f'{ROUTE_PATH}.SystemConfigReader', return_value=reader), \
         flask_app.test_request_context('/status/opencelium'):
        bare(request_user=MagicMock())

    reader.get_all_values_from_section.assert_called_once_with('OpenCelium')
    reader.get_value.assert_not_called()


def test_partial_section_reports_missing_keys_instead_of_failing(flask_app: Flask) -> None:
    """B1 regression: a half-filled section answers 200 with per-key flags, not a 500"""
    body = _call_route(flask_app, {'host': '127.0.0.1', 'port': 9090, 'protocol': 'http'})

    assert body == {
        'status': False,
        'section': True,
        'host': True,
        'port': True,
        'protocol': True,
        'email': False,
        'user': False,
        'password': False,
    }


def test_missing_port_key_reports_false(flask_app: Flask) -> None:
    """B2 regression: an absent port key is reported as unconfigured, not raised as a KeyError"""
    body = _call_route(flask_app, {key: value for key, value in COMPLETE_SECTION.items() if key != 'port'})

    assert body['port'] is False
    assert body['status'] is False
    assert body['section'] is True


@pytest.mark.parametrize('port_value', [0, -1, 'not-a-port', '', None])
def test_unusable_port_values_report_false(flask_app: Flask, port_value: Any) -> None:
    """A present but unusable port is reported as unconfigured and blocks the overall status"""
    body = _call_route(flask_app, {**COMPLETE_SECTION, 'port': port_value})

    assert body['port'] is False
    assert body['status'] is False


@pytest.mark.parametrize('empty_value', ['', '   '])
def test_empty_values_report_false(flask_app: Flask, empty_value: str) -> None:
    """A key present with an empty value counts as unconfigured"""
    body = _call_route(flask_app, {**COMPLETE_SECTION, 'user': empty_value})

    assert body['user'] is False
    assert body['status'] is False


def test_falsy_but_real_values_report_true(flask_app: Flask) -> None:
    """B6 regression: a password the reader cast to False / 0 is still a configured password"""
    body = _call_route(flask_app, {**COMPLETE_SECTION, 'password': False, 'user': 0})

    assert body['password'] is True
    assert body['user'] is True
    assert body['status'] is True


def test_missing_section_reports_section_false(flask_app: Flask) -> None:
    """A SectionError means the [OpenCelium] block itself is absent"""
    body = _call_route(flask_app, SectionError('no section'))

    assert body == {'status': False, 'section': False, **{key: False for key in ALL_KEYS}}


def test_unloaded_config_reports_section_false(flask_app: Flask) -> None:
    """B3 regression: a config-file-less process answers section=False instead of a 500"""
    body = _call_route(flask_app, ConfigNotLoaded('not loaded'))

    assert body == {'status': False, 'section': False, **{key: False for key in ALL_KEYS}}


def test_cloud_mode_reports_section_false_without_reading_the_config(flask_app: Flask) -> None:
    """B5: in cloud mode OpenCelium comes from the service portal, so nothing is read at all"""
    flask_app.cloud_mode = True
    bare = _unwrap(get_oc_config_status)

    with patch(f'{ROUTE_PATH}.SystemConfigReader') as mock_reader, \
         flask_app.test_request_context('/status/opencelium'):
        response = bare(request_user=MagicMock())

    mock_reader.assert_not_called()
    assert response.status_code == 200
    assert response.get_json() == {
        'status': False, 'section': False, **{key: False for key in ALL_KEYS}
    }


def test_unexpected_error_aborts_500(flask_app: Flask) -> None:
    """Any other reader failure is logged and surfaced as a 500"""
    bare = _unwrap(get_oc_config_status)

    with patch(f'{ROUTE_PATH}.SystemConfigReader', side_effect=RuntimeError('boom')), \
         flask_app.test_request_context('/status/opencelium'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500
