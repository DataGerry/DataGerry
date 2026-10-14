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
Integration tests for the reachability probe (``MongoConnector.is_connected``) against a real MongoDB

The probe answers True against the test database and False within its own budget against a server that is not
there - one bounded, unretried ``hello`` instead of ``connect()``'s server selection wait. The connector is the
process-wide singleton, so the unreachable case swaps its lazily built client for one pointing at a closed port
(monkeypatch puts the real one back)
"""
import time

import pytest
from pymongo import MongoClient

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_PROBE_TIMEOUT_S, MONGO_SERVER_SELECTION_TIMEOUT_MS
# -------------------------------------------------------------------------------------------------------------------- #

# A port nothing listens on: the driver is refused at once, so only its server selection keeps it waiting
UNREACHABLE_URI: str = 'mongodb://127.0.0.1:1'

# What the answer may take beyond the probe budget itself (a slow CI machine)
PROBE_ANSWER_MARGIN_S: float = 1.0


def test_the_test_database_answers_the_probe(database_manager: MongoDatabaseManager) -> None:
    """A real hello against the running server is acknowledged"""
    assert database_manager.connector.is_connected() is True
    assert database_manager.status() is True


def test_an_unreachable_server_is_false_within_the_probe_budget(
        database_manager: MongoDatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not the 10 s server selection wait of the shared client options: the probe's own budget, asked once"""
    unreachable = MongoClient(
        UNREACHABLE_URI, serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS, connect=False,
    )
    monkeypatch.setattr(database_manager.connector, '_client', unreachable)

    try:
        started: float = time.monotonic()
        connected: bool = database_manager.connector.is_connected()
        elapsed: float = time.monotonic() - started
    finally:
        unreachable.close()

    assert connected is False
    assert elapsed < MONGO_PROBE_TIMEOUT_S + PROBE_ANSWER_MARGIN_S


def test_the_probe_leaves_the_shared_client_options_alone(
        database_manager: MongoDatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """The budget is scoped to the probe: every other operation keeps the configured server selection timeout"""
    unreachable = MongoClient(
        UNREACHABLE_URI, serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS, connect=False,
    )
    monkeypatch.setattr(database_manager.connector, '_client', unreachable)

    try:
        database_manager.connector.is_connected()

        assert unreachable.options.server_selection_timeout == MONGO_SERVER_SELECTION_TIMEOUT_MS / 1000
    finally:
        unreachable.close()
