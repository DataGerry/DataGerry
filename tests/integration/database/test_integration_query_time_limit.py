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
Integration tests for the server-side time budget of an aggregation, against a real MongoDB

What the unit tests cannot show: the server stops an aggregation on its ``maxTimeMS`` and leaves no operation
behind, the driver's answer is sorted into the typed ``DocumentQueryTimeLimitError``, a pager read is held to the
budget its BuilderParameters carry - and, the bound there was before the budget, a client whose socket times out
leaves no operation behind either (the server stops it on the disconnect)
"""
import time
from typing import Any

import pymongo
import pytest
from pymongo.errors import NetworkTimeout

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_model import CmdbObject
from cmdb.utils import find_cause
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_COLLECTION: str = 'test.query_time_limit'
# Many documents, each cheap: the server checks the budget between documents, so it is the count that lets it stop
DOCUMENT_COUNT: int = 1000
FIRST_OBJECT_ID: int = 92070
# A budget far below what the burn costs, and far below the socket timeout
BUDGET_MS: int = 200
# What the burn may cost at most before the test calls the budget unenforced
WALL_CLOCK_CEILING_S: float = 1.5
# Each document's $reduce walks this many numbers: about 3 ms of server CPU per document, 3 s for them all
BURN_LENGTH: int = 30000
SOCKET_TIMEOUT_MS: int = 500
# How long the server takes to notice a closed socket and stop the operation
DISCONNECT_GRACE_S: float = 3.0
COMMENT: str = 'query-time-limit-test'


def _burn() -> list[dict[str, Any]]:
    """A stage the client filter guard accepts that costs server CPU per document - and is not constant-folded"""
    return [{'$addFields': {'burn': {'$reduce': {
        'input': {'$range': [0, {'$add': [BURN_LENGTH, '$public_id']}]},
        'initialValue': 0,
        'in': {'$add': ['$$value', '$$this']},
    }}}}]


def _running(database_manager: MongoDatabaseManager) -> list[dict[str, Any]]:
    """The operations this module started that the server is still running"""
    in_progress = database_manager.connector.client.admin.command('currentOp', {'active': True})['inprog']

    return [operation for operation in in_progress if operation.get('command', {}).get('comment') == COMMENT]


def _wait_until_gone(database_manager: MongoDatabaseManager) -> list[dict[str, Any]]:
    """The module's operations still running once the grace period is over (or as soon as there are none)"""
    deadline = time.monotonic() + DISCONNECT_GRACE_S

    while (running := _running(database_manager)) and time.monotonic() < deadline:
        time.sleep(0.1)

    return running


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds DOCUMENT_COUNT documents into a scratch collection, dropped afterwards."""
    collection = database_manager.get_collection(SCRATCH_COLLECTION, database_name)
    collection.drop()
    collection.insert_many([{'public_id': public_id} for public_id in range(DOCUMENT_COUNT)])
    yield SCRATCH_COLLECTION
    collection.drop()


@pytest.fixture(name='seeded_objects')
def fixture_seeded_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds bare CmdbObjects for the pager, removed afterwards."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ids: list[int] = list(range(FIRST_OBJECT_ID, FIRST_OBJECT_ID + DOCUMENT_COUNT))
    collection.delete_many({'public_id': {'$in': ids}})
    collection.insert_many([{'public_id': public_id, 'type_id': 0, 'fields': []} for public_id in ids])
    yield ids
    collection.delete_many({'public_id': {'$in': ids}})


class TestTheDatabaseLayer:
    """MongoDatabaseManager.aggregate_within_time_limit against the server."""

    def test_past_the_budget_the_server_stops_and_the_error_is_typed(
            self, database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> None:
        """The burn would take seconds: it stops near the budget, typed, naming it"""
        started = time.monotonic()

        with pytest.raises(DocumentQueryTimeLimitError) as exc_info:
            database_manager.aggregate_within_time_limit(scratch, database_name, _burn(), BUDGET_MS, comment=COMMENT)

        assert time.monotonic() - started < WALL_CLOCK_CEILING_S
        assert exc_info.value.time_limit_ms == BUDGET_MS

    def test_no_operation_is_left_running(
            self, database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> None:
        """The server stopped it - nothing is still burning a core after the answer"""
        with pytest.raises(DocumentQueryTimeLimitError):
            database_manager.aggregate_within_time_limit(scratch, database_name, _burn(), BUDGET_MS, comment=COMMENT)

        assert not _wait_until_gone(database_manager)

    def test_within_the_budget_every_row_is_answered(
            self, database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> None:
        """A cheap pipeline is untouched by the budget"""
        rows = database_manager.aggregate_within_time_limit(
            scratch, database_name, [{'$sort': {'public_id': 1}}], BUDGET_MS,
        )

        assert [row['public_id'] for row in rows] == list(range(DOCUMENT_COUNT))


class TestThePager:
    """A list route's read, through ObjectsManager.iterate_query."""

    def test_a_burning_filter_is_stopped_on_the_parameters_budget(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded_objects: list[int]) -> None:
        """The client's ?filter= reaches the rows and the count, both under the budget"""
        manager = ObjectsManager(database_manager, database_name)
        criteria = [{'$match': {'public_id': {'$in': seeded_objects}}}, *_burn()]
        started = time.monotonic()

        with pytest.raises(BaseManagerIterationError) as exc_info:
            manager.iterate_query(BuilderParameters(criteria=criteria, time_limit_ms=BUDGET_MS))

        assert time.monotonic() - started < WALL_CLOCK_CEILING_S
        timeout = find_cause(exc_info.value, DocumentQueryTimeLimitError)
        assert timeout is not None and timeout.time_limit_ms == BUDGET_MS

    def test_a_plain_filter_answers_its_rows_and_total(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded_objects: list[int]) -> None:
        """The budget changes nothing for a read that fits in it"""
        manager = ObjectsManager(database_manager, database_name)

        rows, total = manager.iterate_query(BuilderParameters(
            criteria={'public_id': {'$in': seeded_objects}}, limit=3, time_limit_ms=BUDGET_MS,
        ))

        assert len(rows) == 3
        assert total == DOCUMENT_COUNT


class TestTheSocketTimeout:
    """The bound the socket timeout already set - the claim the docs make about it."""

    def test_a_timed_out_socket_leaves_no_operation_behind(
            self, database_manager: MongoDatabaseManager, mongodb_parameters: tuple, scratch: str) -> None:
        """The driver gives up, closes the connection, and the server stops the aggregation on the disconnect"""
        host, port, database_name = mongodb_parameters
        client = pymongo.MongoClient(host, int(port), socketTimeoutMS=SOCKET_TIMEOUT_MS)

        try:
            with pytest.raises(NetworkTimeout):
                list(client[database_name][scratch].aggregate(_burn(), comment=COMMENT))
        finally:
            client.close()

        assert not _wait_until_gone(database_manager)
