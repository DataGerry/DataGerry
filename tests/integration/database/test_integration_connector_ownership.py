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
Integration tests: each MongoDatabaseManager owns its connector, against a real MongoDB

The connector is no singleton. Two managers hold two connectors with two clients; closing one leaves the other
working; a reset closes the connector it replaces; and a manager a test builds of its own (``own_database_manager``)
leaves no pymongo thread behind once it is closed
"""
import threading
import time

from pymongo.errors import InvalidOperation
import pytest

from cmdb.database import MongoDatabaseManager
from tests.utils.own_database_manager import own_database_manager
# -------------------------------------------------------------------------------------------------------------------- #

PYMONGO_THREAD_PREFIX: str = 'pymongo'
# How long the driver may take to wind its threads down after a close
THREAD_WIND_DOWN_SECONDS: float = 5.0
THREAD_POLL_SECONDS: float = 0.1
PING_COMMAND: str = 'ping'


def _pymongo_threads() -> set[threading.Thread]:
    """The live driver threads of this process"""
    return {thread for thread in threading.enumerate() if thread.name.startswith(PYMONGO_THREAD_PREFIX)}


def _wait_for_threads(expected: set[threading.Thread]) -> set[threading.Thread]:
    """The driver threads once they are down to `expected`, or whatever is left when the wind-down time is up"""
    deadline: float = time.monotonic() + THREAD_WIND_DOWN_SECONDS
    threads = _pymongo_threads()

    while threads - expected and time.monotonic() < deadline:
        time.sleep(THREAD_POLL_SECONDS)
        threads = _pymongo_threads()

    return threads


def test_two_managers_hold_two_connectors_and_two_clients(mongodb_parameters: tuple,
                                                          database_manager: MongoDatabaseManager) -> None:
    """A second manager re-points nothing of the session's"""
    host, port, database = mongodb_parameters
    session_connector = database_manager.connector
    session_client = session_connector.client

    with own_database_manager(host, port, database) as second:
        assert second.connector is not session_connector
        assert second.connector.client is not session_client
        assert database_manager.connector is session_connector
        assert session_connector.client is session_client


def test_closing_one_manager_leaves_the_other_working(mongodb_parameters: tuple,
                                                      database_manager: MongoDatabaseManager) -> None:
    """Before: the second manager's construction dropped the session's client, its close closed the shared one"""
    host, port, database = mongodb_parameters

    with own_database_manager(host, port, database) as second:
        second.connector.client.admin.command(PING_COMMAND)

    assert database_manager.connector.client.admin.command(PING_COMMAND)


def test_a_closed_manager_leaves_no_driver_thread(mongodb_parameters: tuple,
                                                  database_manager: MongoDatabaseManager) -> None:
    """The test-owned manager's monitor threads end with it - the session's stay"""
    host, port, database = mongodb_parameters
    database_manager.connector.client.admin.command(PING_COMMAND)
    before = _pymongo_threads()

    with own_database_manager(host, port, database) as second:
        second.connector.client.admin.command(PING_COMMAND)
        assert _pymongo_threads() - before

    assert not _wait_for_threads(before) - before


def test_a_reset_closes_the_connector_it_replaces(mongodb_parameters: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """The old connector's client is closed, the new connector builds its own"""
    host, port, database = mongodb_parameters
    # The reset starts the keep-alive; this test is about the connector, so none runs
    monkeypatch.setattr(MongoDatabaseManager, '_start_keepalive', lambda _self: None)

    with own_database_manager(host, port, database) as manager:
        old_connector = manager.connector
        old_client = old_connector.client
        old_client.admin.command(PING_COMMAND)

        manager.reset_connection()

        assert manager.connector is not old_connector
        assert manager.connector.client.admin.command(PING_COMMAND)
        with pytest.raises(InvalidOperation):
            old_client.admin.command(PING_COMMAND)
