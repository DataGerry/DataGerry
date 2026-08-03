# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.open_celium.oc_api_connector

The connector is the HTTP transport towards OpenCelium. Every test builds it through the local
(config-reader) path and patches `requests.request` / `SettingsManager` / `SystemConfigReader` /
`current_app` / `os.getenv` at the module path - no real HTTP, no Mongo. Covers config resolution
(cloud env + on-prem config), header/token handling, url building, the request verbs, the 403
token-refresh retry, and authenticate (success / no-token / failure).
"""
# pylint: disable=protected-access,no-member  # no-member: settings_manager is a MagicMock in tests
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.open_celium.oc_api_connector import OcApiConnector
from cmdb.open_celium.oc_constants import OC_REQUEST_TIMEOUT, OC_TOKEN_SECTION
from cmdb.errors.open_celium import AuthError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.open_celium.oc_api_connector'

_LOCAL_CONFIG: dict[str, str] = {
    'host': 'oc.local', 'port': '9090', 'protocol': 'http',
    'email': 'a@b.c', 'user': 'u', 'password': 'pw',
}


def _make_connector(token: str | None = 'jwt') -> OcApiConnector:
    """Builds a connector via the local config path; its SettingsManager returns the given token."""
    current = SimpleNamespace(cloud_mode=False, local_mode=True)
    scr = MagicMock()
    scr.get_value.side_effect = lambda key, section: _LOCAL_CONFIG[key]
    settings_manager = MagicMock()
    settings_manager.get_all_values_from_section.return_value = {'token': token}

    with patch(f'{MODULE}.current_app', current), \
         patch(f'{MODULE}.SystemConfigReader', return_value=scr), \
         patch(f'{MODULE}.SettingsManager', return_value=settings_manager):
        return OcApiConnector(MagicMock(), 'db')


def _resp(status: int, token: str | None = None, text: str = 'error') -> MagicMock:
    """Builds a fake requests.Response with a status code and optional Authorization header."""
    response = MagicMock()
    response.status_code = status
    response.headers = {'Authorization': token} if token is not None else {}
    response.text = text
    return response


class TestConfigResolution:
    """__init__ resolves the OpenCelium connection config from env (cloud) or config (on-prem)."""

    def test_local_config_builds_api_base_url(self) -> None:
        """The on-prem path reads the config section and appends /api to the base url."""
        connector = _make_connector()

        assert connector.base_url == 'http://oc.local:9090/api'
        assert connector.get_email() == 'a@b.c'
        assert connector.get_password() == 'pw'
        assert connector.get_base_url() == 'http://oc.local:9090/api'

    def test_cloud_config_from_env(self) -> None:
        """The cloud path reads env vars and builds the base url without the /api suffix."""
        env = {
            'OC_HOST': 'oc.host', 'OC_PORT': '443', 'OC_PROTOCOL': 'https',
            'OC_EMAIL': 'a@b.c', 'OC_USER': 'u', 'OC_PASSWORD': 'pw',
        }
        current = SimpleNamespace(cloud_mode=True, local_mode=False)

        with patch(f'{MODULE}.current_app', current), \
             patch(f'{MODULE}.os.getenv', side_effect=env.get), \
             patch(f'{MODULE}.SettingsManager', return_value=MagicMock()):
            connector = OcApiConnector(MagicMock(), 'db')

        assert connector.base_url == 'https://oc.host:443'

    def test_cloud_config_missing_env_raises_value_error(self) -> None:
        """A missing OpenCelium env variable in cloud mode raises ValueError."""
        env = {  # OC_PASSWORD missing
            'OC_HOST': 'oc.host', 'OC_PORT': '443', 'OC_PROTOCOL': 'https',
            'OC_EMAIL': 'a@b.c', 'OC_USER': 'u',
        }
        current = SimpleNamespace(cloud_mode=True, local_mode=False)

        with patch(f'{MODULE}.current_app', current), \
             patch(f'{MODULE}.os.getenv', side_effect=env.get), \
             patch(f'{MODULE}.SettingsManager', return_value=MagicMock()):
            with pytest.raises(ValueError):
                OcApiConnector(MagicMock(), 'db')


class TestTokenHelpers:
    """get_jwt_token / token_is_set read the cached token from the settings."""

    def test_get_jwt_token_returns_cached_token(self) -> None:
        """The token stored in the settings section is returned."""
        assert _make_connector(token='jwt-abc').get_jwt_token() == 'jwt-abc'

    def test_get_jwt_token_none_on_read_error(self) -> None:
        """A settings read error yields None instead of raising."""
        connector = _make_connector()
        connector.settings_manager.get_all_values_from_section.side_effect = RuntimeError('boom')

        assert connector.get_jwt_token() is None

    def test_token_is_set(self) -> None:
        """token_is_set reflects whether a token is cached."""
        assert _make_connector(token='jwt').token_is_set() is True
        assert _make_connector(token=None).token_is_set() is False

    def test_build_url(self) -> None:
        """build_url concatenates the base url and the endpoint."""
        assert _make_connector().build_url('/x') == 'http://oc.local:9090/api/x'


class TestGetHeaders:
    """get_headers assembles the Content-Type, Authorization and master-password headers."""

    def test_with_auth_includes_token(self) -> None:
        """An authenticated request carries the Authorization token and the JSON content type."""
        headers = _make_connector(token='jwt-abc').get_headers(with_auth=True)

        assert headers['Content-Type'] == 'application/json'
        assert headers['Authorization'] == 'jwt-abc'

    def test_token_none_omits_authorization(self) -> None:
        """B2: a None token does not attach an Authorization header (would break requests)."""
        headers = _make_connector(token=None).get_headers(with_auth=True)

        assert 'Authorization' not in headers
        assert headers['Content-Type'] == 'application/json'

    def test_without_auth_omits_authorization(self) -> None:
        """A non-authenticated request carries no Authorization header."""
        assert 'Authorization' not in _make_connector().get_headers(with_auth=False)

    def test_master_password_header(self) -> None:
        """A supplied master password is sent as the X-Master-Password header."""
        headers = _make_connector().get_headers(password='master-pw')

        assert headers['X-Master-Password'] == 'master-pw'


class TestRequestVerbs:
    """The verb wrappers dispatch the right HTTP method/url via requests.request."""

    def test_oc_get_dispatches_get(self) -> None:
        """oc_get sends a GET to the built url with the auth headers and no body."""
        connector = _make_connector(token='jwt')

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK)) as req:
            connector.oc_get('/list')

        method, url = req.call_args.args
        assert method == 'GET'
        assert url == 'http://oc.local:9090/api/list'
        assert req.call_args.kwargs['json'] is None
        assert req.call_args.kwargs['timeout'] == OC_REQUEST_TIMEOUT
        assert req.call_args.kwargs['headers']['Authorization'] == 'jwt'

    def test_oc_post_dispatches_post_with_payload(self) -> None:
        """oc_post sends a POST carrying the JSON payload."""
        connector = _make_connector(token='jwt')
        payload = {'a': 1}

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK)) as req:
            connector.oc_post(payload, '/create')

        assert req.call_args.args[0] == 'POST'
        assert req.call_args.kwargs['json'] == payload

    def test_oc_put_dispatches_put_with_payload(self) -> None:
        """oc_put sends a PUT carrying the JSON payload."""
        connector = _make_connector(token='jwt')

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK)) as req:
            connector.oc_put({'a': 1}, '/update')

        assert req.call_args.args[0] == 'PUT'
        assert req.call_args.kwargs['json'] == {'a': 1}

    def test_oc_delete_dispatches_delete(self) -> None:
        """oc_delete sends a DELETE to the built url."""
        connector = _make_connector(token='jwt')

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK)) as req:
            connector.oc_delete('/remove/5')

        assert req.call_args.args[0] == 'DELETE'
        assert req.call_args.args[1] == 'http://oc.local:9090/api/remove/5'

    def test_missing_token_authenticates_before_send(self) -> None:
        """When no token is cached, an authenticated request logs in first, then sends."""
        connector = _make_connector(token=None)  # token_is_set() -> False

        responses = [
            _resp(HTTPStatus.OK, token='fresh-jwt'),   # authenticate() login POST
            _resp(HTTPStatus.OK),                      # the actual GET
        ]

        with patch(f'{MODULE}.request', side_effect=responses) as req:
            connector.oc_get('/list')

        assert req.call_count == 2
        connector.settings_manager.write.assert_called_once()

    def test_unexpected_error_propagates(self) -> None:
        """A non-transport error inside the request flow is logged and re-raised."""
        connector = _make_connector(token='jwt')

        with patch(f'{MODULE}.request', side_effect=ValueError('boom')):
            with pytest.raises(ValueError):
                connector.oc_get('/list')

    def test_403_triggers_token_refresh_and_retry(self) -> None:
        """B3: a 403 re-authenticates (writing a fresh token) and re-sends the request once."""
        connector = _make_connector(token='jwt')

        responses = [
            _resp(HTTPStatus.FORBIDDEN),               # initial GET -> token rejected
            _resp(HTTPStatus.OK, token='fresh-jwt'),   # login POST inside authenticate()
            _resp(HTTPStatus.OK),                      # retried GET succeeds
        ]

        with patch(f'{MODULE}.request', side_effect=responses) as req:
            result = connector.oc_get('/list')

        assert result.status_code == HTTPStatus.OK
        assert req.call_count == 3
        connector.settings_manager.write.assert_called_once()  # token refreshed

    def test_timeout_propagates(self) -> None:
        """A transport timeout propagates out of the verb wrapper."""
        from requests.exceptions import Timeout  # pylint: disable=import-outside-toplevel
        connector = _make_connector(token='jwt')

        with patch(f'{MODULE}.request', side_effect=Timeout('slow')):
            with pytest.raises(Timeout):
                connector.oc_get('/list')


class TestAuthenticate:
    """authenticate exchanges the credentials for a JWT and caches it (or raises AuthError)."""

    def test_success_writes_token(self) -> None:
        """A 200 login response's Authorization token is written to the settings."""
        connector = _make_connector()

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK, token='new-jwt')):
            connector.authenticate()

        _, kwargs = connector.settings_manager.write.call_args
        assert kwargs['_id'] == OC_TOKEN_SECTION
        assert kwargs['data']['token'] == 'new-jwt'

    def test_success_without_token_raises(self) -> None:
        """B1: a 200 login response that carries no Authorization token raises AuthError."""
        connector = _make_connector()

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.OK, token=None)):
            with pytest.raises(AuthError):
                connector.authenticate()

        connector.settings_manager.write.assert_not_called()

    def test_failed_login_raises(self) -> None:
        """A non-OK login response raises AuthError."""
        connector = _make_connector()

        with patch(f'{MODULE}.request', return_value=_resp(HTTPStatus.UNAUTHORIZED)):
            with pytest.raises(AuthError):
                connector.authenticate()
