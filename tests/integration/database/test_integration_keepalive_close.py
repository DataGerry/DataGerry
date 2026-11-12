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
Integration tests: a closed manager stays closed, against a real MongoDB

A manager is built WITH its keep-alive, the ping interval shortened so several pings fit into a test:

  - while it runs, the keep-alive keeps a client open
  - after ``close()`` the keep-alive thread has ended, the client stays released over many ping intervals, and no
    driver thread of the manager is left
  - ``reset_connection`` after a close reopens it: a new keep-alive builds a client again
  - a ``with`` block closes it the same way
"""
import threading
import time
from collections.abc import Iterator

import pytest

import cmdb.database.mongo_database_manager as mdm
from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

PING_INTERVAL_SECONDS: float = 0.05
# Long enough for several pings had the keep-alive survived the close
SEVERAL_INTERVALS_SECONDS: float = 0.5
PYMONGO_THREAD_PREFIX: str = 'pymongo'
THREAD_WIND_DOWN_SECONDS: float = 5.0
THREAD_POLL_SECONDS: float = 0.05
PING_COMMAND: str = 'ping'


def _pymongo_threads() -> set[threading.Thread]:
    """The live driver threads of this process"""
    return {thread for thread in threading.enumerate() if thread.name.startswith(PYMONGO_THREAD_PREFIX)}


def _wait_until(condition, timeout: float = THREAD_WIND_DOWN_SECONDS) -> bool:
    """Polls a condition until it holds or the time is up; answers whether it held"""
    deadline: float = time.monotonic() + timeout

    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(THREAD_POLL_SECONDS)

    return True


@pytest.fixture(name='baseline_threads')
def fixture_baseline_threads(database_manager: MongoDatabaseManager) -> set[threading.Thread]:
    """The driver threads before the test's manager exists: the session manager's, connected first"""
    database_manager.connector.client.admin.command(PING_COMMAND)

    return _pymongo_threads()


@pytest.fixture(name='manager')
def fixture_manager(mongodb_parameters: tuple, monkeypatch: pytest.MonkeyPatch,
                    baseline_threads: set[threading.Thread]) -> Iterator[MongoDatabaseManager]:
    """A manager of the test's own WITH its keep-alive, pinging every PING_INTERVAL_SECONDS; closed after"""
    del baseline_threads
    monkeypatch.setattr(mdm, 'KEEPALIVE_PING_INTERVAL_SECONDS', PING_INTERVAL_SECONDS)
    host, port, database = mongodb_parameters
    manager = MongoDatabaseManager(host, port, database)

    yield manager

    manager.close()


def _client_held(manager: MongoDatabaseManager) -> bool:
    """Whether the manager's connector holds a client right now - without building one"""
    return manager.connector._client is not None  # pylint: disable=protected-access


def _keepalive_alive(manager: MongoDatabaseManager) -> bool:
    """Whether the manager's keep-alive thread runs"""
    thread = manager._keepalive_thread  # pylint: disable=protected-access
    return bool(thread and thread.is_alive())


def test_the_keepalive_keeps_a_client_open(manager: MongoDatabaseManager) -> None:
    """The control: a running keep-alive builds the client on its own"""
    assert _wait_until(lambda: _client_held(manager))
    assert _keepalive_alive(manager)


def test_a_closed_manager_stays_closed(manager: MongoDatabaseManager, baseline_threads: set[threading.Thread]) -> None:
    """The keep-alive has ended, many intervals later the client is still released, and its driver threads are gone"""
    manager.connector.client.admin.command(PING_COMMAND)
    assert _pymongo_threads() - baseline_threads

    manager.close()
    time.sleep(SEVERAL_INTERVALS_SECONDS)

    assert not _keepalive_alive(manager)
    assert not _client_held(manager)
    assert _wait_until(lambda: not _pymongo_threads() - baseline_threads)


def test_a_reset_reopens_a_closed_manager(manager: MongoDatabaseManager) -> None:
    """reset_connection starts a keep-alive again, which builds a client"""
    manager.close()

    manager.reset_connection()

    assert _keepalive_alive(manager)
    assert _wait_until(lambda: _client_held(manager))


def test_a_with_block_closes_the_manager(manager: MongoDatabaseManager) -> None:
    """Leaving the block stops the keep-alive and releases the client for good"""
    with manager:
        manager.connector.client.admin.command(PING_COMMAND)

    time.sleep(SEVERAL_INTERVALS_SECONDS)

    assert not _keepalive_alive(manager)
    assert not _client_held(manager)
