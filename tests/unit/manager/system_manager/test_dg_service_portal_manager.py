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
Unit tests for cmdb.manager.system_manager.dg_service_portal_manager

DB-free and HTTP-free: the module-level ``current_app``, ``time`` and the ``requests`` verbs
(``post``/``get``/``delete``) are patched. Instances are built via the ``_manager`` helper (which
skips the env-reading ``__init__`` branch and pre-sets the base URL/token). ``sync_config_items``
is exercised on a MagicMock-typed ``self``.

Covers: the cloud/local ``__init__`` gating, header/URL building, the three transport verbs, the
master-password check, the connector/connection/scheduler id triples (via the shared generic
helpers, including the empty-list-on-failure contract), the user-data lookup, the enriched
``sync_config_items`` payload, and the ``is_valid_response`` boundaries
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.system_manager.dg_service_portal_manager import (
    DgServicePortalManager,
    SYNC_CONFIG_ITEMS_URL,
    CHECK_MASTER_PW_URL,
    GET_USER_DATA_URL,
    CONNECTOR_ID_URL,
    GET_CONNECTOR_IDS,
    CONNECTION_ID_URL,
    GET_CONNECTION_IDS,
    SCHEDULER_ID_URL,
    GET_SCHEDULER_IDS,
)
from cmdb.open_celium.oc_constants import OC_REQUEST_TIMEOUT
from cmdb.errors.security import NoAccessTokenError
from cmdb.errors.dg_service_portal import DgServicePortalGetError
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.manager.system_manager.dg_service_portal_manager'

BASE_URL: str = 'http://service-portal'
ACCESS_TOKEN: str = 'access-token'


def _manager(base_url: str = BASE_URL, token: str = ACCESS_TOKEN) -> DgServicePortalManager:
    """Builds a manager instance without touching the environment, with the endpoint/token pre-set."""
    with patch(f'{PATH}.current_app') as current_app:
        current_app.cloud_mode = False
        current_app.local_mode = False
        manager = DgServicePortalManager()

    manager.base_url = base_url
    manager.x_access_token = token

    return manager


def _response(status_code: int = 200, text: str = '{}') -> MagicMock:
    """Builds a stand-in requests.Response with the given status code and body text."""
    response = MagicMock()
    response.status_code = status_code
    response.text = text

    return response


USER_EMAIL: str = 'user@acme.com'
USER_DATABASE: str = 'db_acme'
CONFIG_ITEM_COUNT: int = 42
FIXED_TIMESTAMP_MS: int = 1751932800000
TYPE_COUNTS: list[dict[str, object]] = [
    {'name': 'Server', 'count': 30},
    {'name': 'Client', 'count': 12},
]


def _request_user() -> SimpleNamespace:
    """A stand-in CmdbUser exposing only the email + database attributes the method reads."""
    return SimpleNamespace(email=USER_EMAIL, database=USER_DATABASE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                current_timestamp                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCurrentTimestamp:
    """current_timestamp returns the Unix time in milliseconds as an int."""

    def test_returns_milliseconds_as_int(self) -> None:
        """The seconds-based clock value is converted to a 13-digit millisecond integer."""
        with patch(f'{PATH}.time', return_value=1751932800.123):
            result = DgServicePortalManager.current_timestamp()

        assert result == 1751932800123
        assert isinstance(result, int)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                sync_config_items                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyncConfigItems:
    """sync_config_items ships the enriched payload in cloud mode and short-circuits in local mode."""

    def test_local_mode_returns_true_without_request(self) -> None:
        """In local mode the method returns True and never contacts the Service Portal."""
        mock_self = MagicMock()

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = True

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is True
        mock_self.sp_post.assert_not_called()

    def test_sends_enriched_payload_and_returns_true_on_success(self) -> None:
        """A cloud-mode call posts email/db/count plus timestamp and the per-type breakdown."""
        mock_self = MagicMock()
        mock_self.current_timestamp.return_value = FIXED_TIMESTAMP_MS
        mock_self.is_valid_response.return_value = True

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is True
        target, payload = mock_self.sp_post.call_args.args
        assert target == SYNC_CONFIG_ITEMS_URL
        assert payload == {
            'email': USER_EMAIL,
            'database_name': USER_DATABASE,
            'config_item_count': CONFIG_ITEM_COUNT,
            'timestamp': FIXED_TIMESTAMP_MS,
            'types': TYPE_COUNTS,
        }

    def test_returns_false_on_invalid_response(self) -> None:
        """A non-2xx Service Portal response makes the method return False."""
        mock_self = MagicMock()
        mock_self.is_valid_response.return_value = False

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is False

    def test_returns_false_when_request_raises(self) -> None:
        """A transport error is swallowed and reported as a failed sync (False)."""
        mock_self = MagicMock()
        mock_self.sp_post.side_effect = RuntimeError('boom')

        with patch(f'{PATH}.current_app') as current_app:
            current_app.local_mode = False

            result = DgServicePortalManager.sync_config_items(
                mock_self, _request_user(), CONFIG_ITEM_COUNT, TYPE_COUNTS,
            )

        assert result is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     __init__                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """The constructor reads the Service Portal env vars only in cloud (non-local) mode."""

    def test_cloud_non_local_reads_env(self) -> None:
        """In cloud+non-local mode the access token and base URL are read from the environment."""
        with patch(f'{PATH}.current_app') as current_app, \
             patch(f'{PATH}.os.getenv', side_effect=lambda k: {'X-ACCESS-TOKEN': 't', 'DG_SP_BASE_URL': 'u'}[k]):
            current_app.cloud_mode = True
            current_app.local_mode = False
            manager = DgServicePortalManager()

        assert manager.x_access_token == 't'
        assert manager.base_url == 'u'

    def test_missing_access_token_raises(self) -> None:
        """A missing X-ACCESS-TOKEN raises NoAccessTokenError."""
        with patch(f'{PATH}.current_app') as current_app, \
             patch(f'{PATH}.os.getenv', return_value=None):
            current_app.cloud_mode = True
            current_app.local_mode = False
            with pytest.raises(NoAccessTokenError):
                DgServicePortalManager()

    def test_missing_base_url_raises(self) -> None:
        """A present token but missing base URL raises NoAccessTokenError."""
        with patch(f'{PATH}.current_app') as current_app, \
             patch(f'{PATH}.os.getenv', side_effect=lambda k: 't' if k == 'X-ACCESS-TOKEN' else None):
            current_app.cloud_mode = True
            current_app.local_mode = False
            with pytest.raises(NoAccessTokenError):
                DgServicePortalManager()

    def test_local_mode_leaves_attrs_none(self) -> None:
        """In local mode neither the token nor the base URL is read."""
        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = True
            current_app.local_mode = True
            manager = DgServicePortalManager()

        assert manager.x_access_token is None
        assert manager.base_url is None

    def test_non_cloud_leaves_attrs_none(self) -> None:
        """Outside cloud mode neither the token nor the base URL is read."""
        with patch(f'{PATH}.current_app') as current_app:
            current_app.cloud_mode = False
            current_app.local_mode = False
            manager = DgServicePortalManager()

        assert manager.x_access_token is None
        assert manager.base_url is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                            headers / url / transport verbs                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHeadersAndUrl:
    """get_headers and create_full_url build the request headers and full endpoint URL."""

    def test_headers_without_password(self) -> None:
        """Without a password only the access token header is present."""
        assert _manager().get_headers() == {'x-access-token': ACCESS_TOKEN}

    def test_headers_with_password(self) -> None:
        """A password adds the x-master-password header."""
        headers = _manager().get_headers('secret')
        assert headers == {'x-access-token': ACCESS_TOKEN, 'x-master-password': 'secret'}

    def test_create_full_url(self) -> None:
        """The full URL concatenates the base URL and the endpoint."""
        assert _manager().create_full_url('/some/endpoint') == f'{BASE_URL}/some/endpoint'


class TestTransportVerbs:
    """sp_post / sp_get / sp_delete forward the built URL, headers, payload and timeout."""

    def test_sp_post(self) -> None:
        """sp_post posts to the full URL with the headers, payload and configured timeout."""
        payload = {'k': 'v'}
        with patch(f'{PATH}.post', return_value=_response()) as post:
            response = _manager().sp_post('/target', payload, 'pw')

        assert response.status_code == 200
        post.assert_called_once_with(
            f'{BASE_URL}/target',
            headers={'x-access-token': ACCESS_TOKEN, 'x-master-password': 'pw'},
            json=payload,
            timeout=OC_REQUEST_TIMEOUT,
        )

    def test_sp_get(self) -> None:
        """sp_get gets the full URL with headers and the configured timeout."""
        with patch(f'{PATH}.get', return_value=_response()) as get:
            _manager().sp_get('/target')

        get.assert_called_once_with(
            f'{BASE_URL}/target',
            headers={'x-access-token': ACCESS_TOKEN},
            timeout=OC_REQUEST_TIMEOUT,
        )

    def test_sp_delete(self) -> None:
        """sp_delete deletes the full URL with headers, payload and the configured timeout."""
        payload = {'k': 'v'}
        with patch(f'{PATH}.delete', return_value=_response()) as delete:
            _manager().sp_delete('/target', payload)

        delete.assert_called_once_with(
            f'{BASE_URL}/target',
            headers={'x-access-token': ACCESS_TOKEN},
            json=payload,
            timeout=OC_REQUEST_TIMEOUT,
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 check_master_pw                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCheckMasterPw:
    """check_master_pw posts the master password and returns the validity of the response."""

    def test_valid_password_returns_true(self) -> None:
        """A 2xx response means the master password is correct."""
        with patch(f'{PATH}.post', return_value=_response(200)) as post:
            assert _manager().check_master_pw('pw', 'a@b.c', 'db') is True

        target, kwargs = post.call_args.args[0], post.call_args.kwargs
        assert target == f'{BASE_URL}{CHECK_MASTER_PW_URL}'
        assert kwargs['headers']['x-master-password'] == 'pw'
        assert kwargs['json'] == {'userEmail': 'a@b.c', 'databaseName': 'db'}

    def test_invalid_password_returns_false(self) -> None:
        """A non-2xx response means the master password is wrong."""
        with patch(f'{PATH}.post', return_value=_response(401)):
            assert _manager().check_master_pw('pw', 'a@b.c', 'db') is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                        connector / connection / scheduler triples                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConnectorEntityFullPath:
    """The connector methods exercise the shared generic helpers end-to-end (post/get/delete)."""

    def test_save_connector_id_success(self) -> None:
        """A saved connector id posts the id payload and returns True on 2xx."""
        with patch(f'{PATH}.post', return_value=_response(200)) as post:
            assert _manager().save_connector_id(7, 'a@b.c', 'db') is True

        assert post.call_args.args[0] == f'{BASE_URL}{CONNECTOR_ID_URL}'
        assert post.call_args.kwargs['json'] == {'id': 7, 'userEmail': 'a@b.c', 'databaseName': 'db'}

    def test_save_connector_id_failure(self) -> None:
        """A non-2xx save returns False."""
        with patch(f'{PATH}.post', return_value=_response(500)):
            assert _manager().save_connector_id(7, 'a@b.c', 'db') is False

    def test_get_connector_ids_parses_and_filters(self) -> None:
        """Valid responses parse the ids and coerce/filter the raw values to ints."""
        with patch(f'{PATH}.get', return_value=_response(200, '{"ids": ["1", 2, null, {}]}')) as get:
            assert _manager().get_connector_ids('a@b.c', 'db') == [1, 2]

        assert get.call_args.args[0] == f'{BASE_URL}{GET_CONNECTOR_IDS}?userEmail=a@b.c&databaseName=db'

    def test_get_connector_ids_invalid_returns_empty_list(self) -> None:
        """An invalid response yields an empty list (not False) so callers can iterate safely."""
        with patch(f'{PATH}.get', return_value=_response(500, '')):
            assert _manager().get_connector_ids('a@b.c', 'db') == []

    def test_delete_connector_id(self) -> None:
        """Deleting a connector id appends the id to the URL and returns the response validity."""
        with patch(f'{PATH}.delete', return_value=_response(200)) as delete:
            assert _manager().delete_connector_id(7, 'a@b.c', 'db') is True

        assert delete.call_args.args[0] == f'{BASE_URL}{CONNECTOR_ID_URL}/7'

    def test_check_connector_in_sub_present(self) -> None:
        """A connector id contained in the subscription list returns True."""
        with patch(f'{PATH}.get', return_value=_response(200, '{"ids": [7, 8]}')):
            assert _manager().check_connector_in_sub(7, 'a@b.c', 'db') is True

    def test_check_connector_in_sub_absent(self) -> None:
        """A connector id not in the subscription list returns False."""
        with patch(f'{PATH}.get', return_value=_response(200, '{"ids": [8, 9]}')):
            assert _manager().check_connector_in_sub(7, 'a@b.c', 'db') is False

    def test_check_connector_in_sub_invalid_response_returns_false(self) -> None:
        """A failed lookup returns False instead of raising (regression guard for the []-vs-False fix)."""
        with patch(f'{PATH}.get', return_value=_response(500, '')):
            assert _manager().check_connector_in_sub(7, 'a@b.c', 'db') is False


class TestConnectionAndSchedulerDelegation:
    """The connection/scheduler public methods delegate to the shared helpers with the right URLs."""

    @pytest.mark.parametrize('method, helper, url_const', [
        ('save_connection_id', '_save_entity_id', CONNECTION_ID_URL),
        ('delete_connection_id', '_delete_entity_id', CONNECTION_ID_URL),
        ('save_scheduler_id', '_save_entity_id', SCHEDULER_ID_URL),
        ('delete_scheduler_id', '_delete_entity_id', SCHEDULER_ID_URL),
    ])
    def test_save_delete_delegate_with_url(self, method: str, helper: str, url_const: str) -> None:
        """save_/delete_ pass their entity URL plus the id/email/db through to the generic helper."""
        manager = _manager()
        with patch.object(manager, helper, return_value=True) as mocked:
            assert getattr(manager, method)(5, 'a@b.c', 'db') is True

        mocked.assert_called_once_with(url_const, 5, 'a@b.c', 'db')

    @pytest.mark.parametrize('method, list_url', [
        ('get_connection_ids', GET_CONNECTION_IDS),
        ('get_scheduler_ids', GET_SCHEDULER_IDS),
    ])
    def test_get_ids_delegate_with_list_url(self, method: str, list_url: str) -> None:
        """get_*_ids pass their list URL plus email/db to _get_entity_ids."""
        manager = _manager()
        with patch.object(manager, '_get_entity_ids', return_value=[1]) as mocked:
            assert getattr(manager, method)('a@b.c', 'db') == [1]

        mocked.assert_called_once_with(list_url, 'a@b.c', 'db')

    @pytest.mark.parametrize('method, list_url', [
        ('check_connection_in_sub', GET_CONNECTION_IDS),
        ('check_scheduler_in_sub', GET_SCHEDULER_IDS),
    ])
    def test_check_in_sub_delegate_with_list_url(self, method: str, list_url: str) -> None:
        """check_*_in_sub pass their list URL plus the id/email/db to _check_entity_in_sub."""
        manager = _manager()
        with patch.object(manager, '_check_entity_in_sub', return_value=True) as mocked:
            assert getattr(manager, method)(5, 'a@b.c', 'db') is True

        mocked.assert_called_once_with(list_url, 5, 'a@b.c', 'db')


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_dg_sp_user_data                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetUserData:
    """get_dg_sp_user_data returns the parsed body or raises on a failed lookup."""

    def test_success_returns_parsed_body(self) -> None:
        """A 2xx response returns the parsed user data and posts to the lookup endpoint."""
        with patch(f'{PATH}.post', return_value=_response(200, '{"email": "a@b.c"}')) as post:
            assert _manager().get_dg_sp_user_data('a@b.c') == {'email': 'a@b.c'}

        assert post.call_args.args[0] == f'{BASE_URL}{GET_USER_DATA_URL}'
        assert post.call_args.kwargs['json'] == {'email': 'a@b.c'}

    def test_failure_raises_get_error(self) -> None:
        """A non-2xx response raises DgServicePortalGetError."""
        with patch(f'{PATH}.post', return_value=_response(404, 'nope')):
            with pytest.raises(DgServicePortalGetError):
                _manager().get_dg_sp_user_data('a@b.c')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                is_valid_response                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsValidResponse:
    """is_valid_response treats 2xx status codes as success."""

    @pytest.mark.parametrize('status_code, expected', [
        (199, False),
        (200, True),
        (299, True),
        (300, False),
    ])
    def test_status_code_boundaries(self, status_code: int, expected: bool) -> None:
        """Only status codes in the inclusive 200-299 range are valid."""
        assert _manager().is_valid_response(_response(status_code)) is expected
