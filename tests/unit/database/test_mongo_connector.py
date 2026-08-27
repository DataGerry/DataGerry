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
Unit tests for cmdb.database.mongo_connector

DB-free: `MongoClient` is patched at the module path and the lazily-created client is replaced with a
MagicMock, so nothing here talks to a server.

**The singleton is shared with the test session.** `MongoConnector._instance` is a class attribute and
the session-scoped `database_manager` fixture already populated it; constructing a connector in a test
overwrites that instance's host / port / options / client. An autouse fixture therefore saves and
restores `_instance` around every test - without it these tests would break every later DB-touching
test in the session.

Several tests pin behaviour the audit flagged as wrong and that was deliberately left unchanged: the
'ssl' option being dropped without carrying its value into 'tls' (discussion-backlog #139), the
caller's options dict being mutated in place (#140), `is_connected` raising instead of returning False
(#141), the `retry_operation` wrappers never retrying (#142) and `disconnect` swallowing a failed close
(#143). They are regression pins for the CURRENT contract, not endorsements - each names its item so a
fix knows which test to rewrite.
"""
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import ConnectionFailure, InvalidURI

from cmdb.database.connection_status import ConnectionStatus
from cmdb.database.database_constants import (
    MONGO_COMMAND_OK_KEY,
    MONGO_CONNECTION_STRING_ENV,
    MONGO_HELLO_COMMAND,
    MONGO_SSL_OPTION,
    MONGO_TLS_OPTION,
)
from cmdb.database.mongo_connector import MongoConnector
from cmdb.errors.database import DatabaseConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTOR_PATH: str = 'cmdb.database.mongo_connector'

HOST: str = 'db.example.test'
PORT: int = 27017

SRV_STRING: str = 'mongodb+srv://cluster.example.test'
PLAIN_STRING: str = 'mongodb://db.example.test:27017'


@pytest.fixture(autouse=True, name='isolated_singleton')
def fixture_isolated_singleton(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Restores the shared MongoConnector singleton and the connection-string env around each test."""
    previous_instance = MongoConnector._instance  # pylint: disable=protected-access
    monkeypatch.delenv(MONGO_CONNECTION_STRING_ENV, raising=False)
    MongoConnector._instance = None  # pylint: disable=protected-access

    yield

    MongoConnector._instance = previous_instance  # pylint: disable=protected-access


def _connector(client_options: dict[str, Any] | None = None, host: str = HOST, port: int = PORT) -> MongoConnector:
    """Builds a fresh connector against the isolated singleton."""
    return MongoConnector(host, port, client_options)


def _with_client(connector: MongoConnector, client: MagicMock) -> MongoConnector:
    """Injects an already-built client so the lazy property does not construct one."""
    connector._client = client  # pylint: disable=protected-access

    return connector


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    singleton                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_second_construction_returns_the_same_instance() -> None:
    """The class caches its first instance and hands it back to every later construction"""
    assert _connector({}) is _connector({})


def test_a_later_construction_overwrites_host_and_port() -> None:
    """The cached instance is re-pointed by a later construction (discussion-backlog #145)"""
    _connector({}, host='first.example.test', port=1111)
    connector = _connector({}, host='second.example.test', port=2222)

    assert (connector.host, connector.port) == ('second.example.test', 2222)


def test_a_later_construction_drops_the_cached_client_without_closing_it() -> None:
    """__init__ resets the lazy client on the shared instance; the old one is not closed (#144)"""
    client = MagicMock()
    connector = _with_client(_connector({}), client)

    _connector({})

    assert connector._client is None  # pylint: disable=protected-access
    client.close.assert_not_called()


def test_port_is_coerced_to_int() -> None:
    """A port given as a string is stored as an int"""
    assert _connector({}, port='27018').port == 27018


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 TLS / ssl handling                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ssl_option_is_dropped_without_carrying_its_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """#139: an explicit ssl=True over host/port ends up as tls=False, NOT tls=True"""
    monkeypatch.delenv(MONGO_CONNECTION_STRING_ENV, raising=False)

    options = _connector({MONGO_SSL_OPTION: True}).client_options

    assert MONGO_SSL_OPTION not in options
    assert options[MONGO_TLS_OPTION] is False


def test_srv_connection_string_enables_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mongodb+srv:// connection string is the one input that turns TLS on"""
    monkeypatch.setenv(MONGO_CONNECTION_STRING_ENV, SRV_STRING)

    assert _connector({}).client_options[MONGO_TLS_OPTION] is True


def test_plain_connection_string_does_not_enable_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """#139: a plain mongodb:// string gets tls=False injected, overriding what the URI may ask for"""
    monkeypatch.setenv(MONGO_CONNECTION_STRING_ENV, PLAIN_STRING)

    assert _connector({}).client_options[MONGO_TLS_OPTION] is False


@pytest.mark.parametrize('provided', [True, False])
def test_a_caller_supplied_tls_option_is_respected(provided: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit 'tls' is the only way for a caller to decide TLS itself"""
    monkeypatch.setenv(MONGO_CONNECTION_STRING_ENV, SRV_STRING)

    assert _connector({MONGO_TLS_OPTION: provided}).client_options[MONGO_TLS_OPTION] is provided


def test_the_callers_options_dict_is_mutated_in_place() -> None:
    """#140: the caller's dict is stored by reference and loses 'ssl' / gains 'tls'"""
    options: dict[str, Any] = {'retryReads': True, MONGO_SSL_OPTION: True}

    connector = _connector(options)

    assert connector.client_options is options
    assert options == {'retryReads': True, MONGO_TLS_OPTION: False}


def test_options_default_to_a_fresh_dict() -> None:
    """No options given means only the injected tls flag"""
    assert _connector(None).client_options == {MONGO_TLS_OPTION: False}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  client property                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_client_is_built_from_host_and_port_without_connecting() -> None:
    """Without a connection string the client is built lazily with connect=False (pre-fork safety)"""
    connector = _connector({})

    with patch(f'{CONNECTOR_PATH}.MongoClient') as mock_client:
        built = connector.client

    mock_client.assert_called_once_with(host=HOST, port=PORT, connect=False, **connector.client_options)
    assert built is mock_client.return_value


def test_client_is_built_from_the_connection_string_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection string replaces the host/port pair"""
    monkeypatch.setenv(MONGO_CONNECTION_STRING_ENV, SRV_STRING)
    connector = _connector({})

    with patch(f'{CONNECTOR_PATH}.MongoClient') as mock_client:
        assert connector.client is mock_client.return_value

    mock_client.assert_called_once_with(SRV_STRING, **connector.client_options)


def test_client_is_cached_after_the_first_access() -> None:
    """The client is created once and reused"""
    connector = _connector({})

    with patch(f'{CONNECTOR_PATH}.MongoClient') as mock_client:
        first = connector.client
        second = connector.client

    assert first is second
    assert mock_client.call_count == 1


def test_client_creation_failure_raises_a_database_connection_error() -> None:
    """A pymongo option conflict surfaces as a generic DatabaseConnectionError with the cause chained"""
    connector = _connector({})
    cause = InvalidURI('Can not specify conflicting values for URI options ssl and tls.')

    with patch(f'{CONNECTOR_PATH}.MongoClient', side_effect=cause):
        with pytest.raises(DatabaseConnectionError) as exc_info:
            connector.client  # pylint: disable=pointless-statement

    assert exc_info.value.__cause__ is cause


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_database                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_database_delegates_to_the_client() -> None:
    """The database is looked up on the cached client"""
    client = MagicMock()
    connector = _with_client(_connector({}), client)

    assert connector.get_database('cmdb') is client.get_database.return_value
    client.get_database.assert_called_once_with('cmdb')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      connect                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_connect_reports_connected_on_an_acknowledged_hello() -> None:
    """An ok:1 response to the 'hello' command is a connected status carrying the raw response"""
    client = MagicMock()
    client.admin.command.return_value = {MONGO_COMMAND_OK_KEY: 1, 'setName': 'rs0'}
    connector = _with_client(_connector({}), client)

    status: ConnectionStatus = connector.connect()

    client.admin.command.assert_called_once_with(MONGO_HELLO_COMMAND)
    assert status.get_status() is True
    assert 'setName' in status.message


@pytest.mark.parametrize('response', [{MONGO_COMMAND_OK_KEY: 0}, {}, {MONGO_COMMAND_OK_KEY: '1'}])
def test_connect_raises_on_an_unacknowledged_response(response: dict[str, Any]) -> None:
    """Anything but ok:1 is raised, never returned as a disconnected status"""
    client = MagicMock()
    client.admin.command.return_value = response
    connector = _with_client(_connector({}), client)

    with pytest.raises(DatabaseConnectionError):
        connector.connect()


def test_connect_raises_when_the_server_is_unreachable() -> None:
    """A pymongo failure is converted into DatabaseConnectionError with the cause chained"""
    client = MagicMock()
    cause = ConnectionFailure('server down')
    client.admin.command.side_effect = cause
    connector = _with_client(_connector({}), client)

    with pytest.raises(DatabaseConnectionError) as exc_info:
        connector.connect()

    assert exc_info.value.__cause__ is cause


def test_connect_does_not_retry_a_pymongo_failure() -> None:
    """#142: the retry wrapper never fires, because connect converts the error before it can escape"""
    client = MagicMock()
    client.admin.command.side_effect = ConnectionFailure('server down')
    connector = _with_client(_connector({}), client)

    with pytest.raises(DatabaseConnectionError):
        connector.connect()

    assert client.admin.command.call_count == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    disconnect                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_disconnect_closes_and_clears_the_client() -> None:
    """An active client is closed and dropped so the next access builds a new one"""
    client = MagicMock()
    connector = _with_client(_connector({}), client)

    status = connector.disconnect()

    client.close.assert_called_once_with()
    assert connector._client is None  # pylint: disable=protected-access
    assert (status.get_status(), status.message) == (False, "Successfully disconnected from the database.")


def test_disconnect_without_a_client_is_a_no_op() -> None:
    """Nothing to close is reported as its own message, not as an error"""
    status = _connector({}).disconnect()

    assert (status.get_status(), status.message) == (False, "No active database connection to close.")


def test_disconnect_swallows_a_failing_close_and_keeps_the_client() -> None:
    """#143: a failed close reports the same connected=False and leaves the broken client in place"""
    client = MagicMock()
    client.close.side_effect = RuntimeError('boom')
    connector = _with_client(_connector({}), client)

    status = connector.disconnect()

    assert status.get_status() is False
    assert status.message == 'Error while disconnecting: boom'
    assert connector._client is client  # pylint: disable=protected-access


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   is_connected                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_is_connected_is_true_when_the_server_answers() -> None:
    """A successful probe is reported as True"""
    client = MagicMock()
    client.admin.command.return_value = {MONGO_COMMAND_OK_KEY: 1}
    connector = _with_client(_connector({}), client)

    assert connector.is_connected() is True


def test_is_connected_raises_instead_of_returning_false() -> None:
    """#141: the documented 'False otherwise' never happens - callers have to catch"""
    client = MagicMock()
    client.admin.command.side_effect = ConnectionFailure('server down')
    connector = _with_client(_connector({}), client)

    with pytest.raises(DatabaseConnectionError):
        connector.is_connected()
