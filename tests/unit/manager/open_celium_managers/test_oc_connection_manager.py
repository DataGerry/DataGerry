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
Unit tests for cmdb.manager.open_celium_managers.oc_connection_manager.OcConnectionManager

The manager is a thin wrapper over an OcApiConnector that talks to OpenCelium over HTTP. The
connector is patched out at the OcBaseManager module path, so each test stubs the connector verb
(oc_post / oc_get / oc_put / oc_delete) with a fake response and asserts: the right endpoint + payload
were sent, a 2xx body is parsed and returned, and a non-2xx response raises the operation's OC error
(or, for delete, returns False). No HTTP, no Mongo.
"""
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.open_celium_managers.oc_connection_manager import (
    OcConnectionManager,
    CONNECTION_URL,
    CONNECTION_REMOTE_API_URL,
    CONNECTIONS_BY_IDS_URL,
    CON_UNIQUE_CHECK_URL,
    CONNECTION_TEST_URL,
)
from cmdb.open_celium.oc_constants import UNIQUE_POSITIVE
from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
    OcConnectionUpdateError,
    OcConnectionTestError,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.manager.open_celium_managers.oc_base_manager'

CONNECTION_ID: int = 5
CHANNEL_ID: int = 3

OK_STATUS: int = HTTPStatus.OK.value
ERROR_STATUS: int = HTTPStatus.INTERNAL_SERVER_ERROR.value


def _response(status_code: int, payload: Any = None) -> SimpleNamespace:
    """A minimal stand-in for a requests.Response (status code + JSON text body)."""
    return SimpleNamespace(status_code=status_code, text=json.dumps(payload) if payload is not None else '')


@pytest.fixture(name='connection_manager')
def fixture_connection_manager() -> OcConnectionManager:
    """An OcConnectionManager whose OcApiConnector is a MagicMock (no HTTP)."""
    with patch(f'{BASE_PATH}.OcApiConnector'):
        return OcConnectionManager(MagicMock(), 'db_test')


# --------------------------------------------------- create_connection ---------------------------------------------- #

class TestCreateConnection:
    """``create_connection`` POSTs to /connection and returns the parsed body."""

    def test_posts_and_returns_created(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx response body is parsed and returned; the payload hits the connection endpoint."""
        connection_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'connectionId': CONNECTION_ID})

        result = connection_manager.create_connection({'title': 'conn'})

        assert result == {'connectionId': CONNECTION_ID}
        connection_manager.oc_connector.oc_post.assert_called_once_with({'title': 'conn'}, CONNECTION_URL)

    def test_non_2xx_raises_create_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionCreateError."""
        connection_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionCreateError):
            connection_manager.create_connection({'title': 'conn'})


# --------------------------------------------------- send_to_remote_api --------------------------------------------- #

class TestSendToRemoteApi:
    """``send_to_remote_api`` POSTs to the remote-api endpoint."""

    def test_posts_and_returns_response(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx response body is parsed and returned from the remote-api endpoint."""
        connection_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'echo': 'ok'})

        result = connection_manager.send_to_remote_api({'payload': 1})

        assert result == {'echo': 'ok'}
        connection_manager.oc_connector.oc_post.assert_called_once_with({'payload': 1}, CONNECTION_REMOTE_API_URL)

    def test_non_2xx_raises_create_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionCreateError (what the route maps to 400)."""
        connection_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionCreateError):
            connection_manager.send_to_remote_api({'payload': 1})


# ------------------------------------------------- get_connections_by_ids ------------------------------------------- #

class TestGetConnectionsByIds:
    """``get_connections_by_ids`` POSTs the id list and guards an empty list."""

    def test_empty_ids_raises_get_error_without_http(self, connection_manager: OcConnectionManager) -> None:
        """An empty id list raises OcConnectionGetError before any HTTP call."""
        with pytest.raises(OcConnectionGetError):
            connection_manager.get_connections_by_ids([])

        connection_manager.oc_connector.oc_post.assert_not_called()

    def test_posts_identifiers_and_returns_body(self, connection_manager: OcConnectionManager) -> None:
        """The ids are sent under 'identifiers' to the by-ids endpoint and the body is returned."""
        connection_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, [{'connectionId': CONNECTION_ID}])

        result = connection_manager.get_connections_by_ids([CONNECTION_ID])

        assert result == [{'connectionId': CONNECTION_ID}]
        connection_manager.oc_connector.oc_post.assert_called_once_with(
            {'identifiers': [CONNECTION_ID]}, CONNECTIONS_BY_IDS_URL
        )

    def test_non_2xx_raises_get_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionGetError."""
        connection_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionGetError):
            connection_manager.get_connections_by_ids([CONNECTION_ID])


# ---------------------------------------------------- test_connection ----------------------------------------------- #

class TestTestConnection:
    """``test_connection`` POSTs to the execution-test endpoint with the channelId query."""

    def test_posts_with_channel_and_returns_body(self, connection_manager: OcConnectionManager) -> None:
        """The channelId is appended to the endpoint and the result body is returned."""
        connection_manager.oc_connector.oc_post.return_value = _response(OK_STATUS, {'success': True})

        result = connection_manager.test_connection({'data': 1}, CHANNEL_ID)

        assert result == {'success': True}
        connection_manager.oc_connector.oc_post.assert_called_once_with(
            {'data': 1}, f"{CONNECTION_TEST_URL}?channelId={CHANNEL_ID}"
        )

    def test_non_2xx_raises_test_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionTestError."""
        connection_manager.oc_connector.oc_post.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionTestError):
            connection_manager.test_connection({'data': 1}, CHANNEL_ID)


# ----------------------------------------------------- get_connection ----------------------------------------------- #

class TestGetConnection:
    """``get_connection`` GETs /connection/<id> and guards a falsy id."""

    def test_falsy_id_raises_get_error_without_http(self, connection_manager: OcConnectionManager) -> None:
        """A falsy connection id raises OcConnectionGetError before any HTTP call."""
        with pytest.raises(OcConnectionGetError):
            connection_manager.get_connection(0)

        connection_manager.oc_connector.oc_get.assert_not_called()

    def test_gets_and_returns_body(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx response body is parsed and returned from /connection/<id>."""
        connection_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'connectionId': CONNECTION_ID})

        result = connection_manager.get_connection(CONNECTION_ID)

        assert result == {'connectionId': CONNECTION_ID}
        connection_manager.oc_connector.oc_get.assert_called_once_with(f"{CONNECTION_URL}/{CONNECTION_ID}")

    def test_non_2xx_raises_get_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionGetError."""
        connection_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionGetError):
            connection_manager.get_connection(CONNECTION_ID)


# ----------------------------------------------- check_connection_name_exists --------------------------------------- #

class TestCheckConnectionNameExists:
    """``check_connection_name_exists`` maps the uniqueness message to a bool."""

    def test_unique_message_means_not_exists(self, connection_manager: OcConnectionManager) -> None:
        """The UNIQUE_POSITIVE message means the name is free, so the method returns False."""
        connection_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'message': UNIQUE_POSITIVE})

        assert connection_manager.check_connection_name_exists('my-connection') is False
        connection_manager.oc_connector.oc_get.assert_called_once_with(f"{CON_UNIQUE_CHECK_URL}/my-connection")

    def test_other_message_means_exists(self, connection_manager: OcConnectionManager) -> None:
        """Any other message means the name is taken, so the method returns True."""
        connection_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {'message': 'EXISTS'})

        assert connection_manager.check_connection_name_exists('my-connection') is True

    def test_missing_message_key_means_exists(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx body without a 'message' key returns True instead of raising KeyError (uses .get)."""
        connection_manager.oc_connector.oc_get.return_value = _response(OK_STATUS, {})

        assert connection_manager.check_connection_name_exists('my-connection') is True

    def test_non_2xx_raises_get_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionGetError."""
        connection_manager.oc_connector.oc_get.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionGetError):
            connection_manager.check_connection_name_exists('my-connection')


# --------------------------------------------------- update_connection ---------------------------------------------- #

class TestUpdateConnection:
    """``update_connection`` PUTs to /connection/<id>."""

    def test_puts_and_returns_body(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx response body is parsed and returned from the PUT."""
        connection_manager.oc_connector.oc_put.return_value = _response(OK_STATUS, {'connectionId': CONNECTION_ID})

        result = connection_manager.update_connection({'title': 'renamed'}, CONNECTION_ID)

        assert result == {'connectionId': CONNECTION_ID}
        connection_manager.oc_connector.oc_put.assert_called_once_with(
            {'title': 'renamed'}, f"{CONNECTION_URL}/{CONNECTION_ID}"
        )

    def test_non_2xx_raises_update_error(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx response raises OcConnectionUpdateError."""
        connection_manager.oc_connector.oc_put.return_value = _response(ERROR_STATUS)

        with pytest.raises(OcConnectionUpdateError):
            connection_manager.update_connection({'title': 'renamed'}, CONNECTION_ID)


# --------------------------------------------------- delete_connection ---------------------------------------------- #

class TestDeleteConnection:
    """``delete_connection`` DELETEs /connection/<id> and returns a bool (never raises)."""

    def test_2xx_returns_true(self, connection_manager: OcConnectionManager) -> None:
        """A 2xx delete returns True."""
        connection_manager.oc_connector.oc_delete.return_value = _response(OK_STATUS)

        assert connection_manager.delete_connection(CONNECTION_ID) is True
        connection_manager.oc_connector.oc_delete.assert_called_once_with(f"{CONNECTION_URL}/{CONNECTION_ID}")

    def test_non_2xx_returns_false(self, connection_manager: OcConnectionManager) -> None:
        """A non-2xx delete returns False rather than raising."""
        connection_manager.oc_connector.oc_delete.return_value = _response(ERROR_STATUS)

        assert connection_manager.delete_connection(CONNECTION_ID) is False
