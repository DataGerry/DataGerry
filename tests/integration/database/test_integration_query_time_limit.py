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
while its aggregation is still computing the first reply leaves no operation behind either: the server stops the
command in flight on the disconnect.

Only the command in flight. A ``getMore`` the driver gives up on is not stopped - the server finishes its batch
(measured on 7.0.34) - so the socket test makes the first reply carry the whole burn, and the burn last far longer
than the test waits: an operation that merely FINISHED inside the wait would otherwise pass for a stopped one
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
# A stopped burn ends before this fraction of what the whole burn costs, measured in the same run: a fixed ceiling
# fails on a loaded machine, where the stop and the burn slow down together
STOPPED_COST_FRACTION: float = 0.5
# Each document's $reduce walks this many numbers: about 3 ms of server CPU per document, 3 s for them all
BURN_LENGTH: int = 30000
# How long a stopped operation may take to leave currentOp after the budget's error reached the client - well
# below the burn's ~3 s, so an operation the budget did not stop would still be seen
MAX_TIME_STOP_WAIT_S: float = 1.0
SOCKET_TIMEOUT_MS: int = 500
# The socket test's burn: about 25 ms per document, 25 s for them all - so long that only a stop ends it in the wait
DISCONNECT_BURN_LENGTH: int = 250000
# How long the server may take to notice the closed socket and stop the command (it takes well under a second)
DISCONNECT_STOP_WAIT_S: float = 5.0
# The burn must outlast the wait by this factor, or finishing would look like being stopped
BURN_TO_WAIT_FACTOR: int = 4
# The documents a burn's cost is sampled on: enough for a stable estimate, few enough to stay cheap
SHORT_BURN_SAMPLE_SIZE: int = 100
LONG_BURN_SAMPLE_SIZE: int = 20
COMMENT: str = 'query-time-limit-test'


def _burn(length: int = BURN_LENGTH) -> list[dict[str, Any]]:
    """
    A stage that costs server CPU per document - and is not constant-folded

    The client filter guard refuses ``$range``; this module goes to the database directly, below the guard, because
    what it tests is the server's budget, not what a client may send

    Args:
        length (int): How many numbers each document's $reduce walks

    Returns:
        list[dict[str, Any]]: The one $addFields stage
    """
    return [{'$addFields': {'burn': {'$reduce': {
        'input': {'$range': [0, {'$add': [length, '$public_id']}]},
        'initialValue': 0,
        'in': {'$add': ['$$value', '$$this']},
    }}}}]


def _running(database_manager: MongoDatabaseManager) -> list[dict[str, Any]]:
    """The operations this module started that the server is still running"""
    in_progress = database_manager.connector.client.admin.command('currentOp', {'active': True})['inprog']

    return [operation for operation in in_progress if operation.get('command', {}).get('comment') == COMMENT]


def _wait_until_gone(database_manager: MongoDatabaseManager, wait_s: float) -> list[dict[str, Any]]:
    """
    The module's operations still running once the wait is over - or none, as soon as they are gone

    Args:
        database_manager (MongoDatabaseManager): The connection currentOp is read through
        wait_s (float): The longest the operations may take to go

    Returns:
        list[dict[str, Any]]: The operations still running; empty when they went in time
    """
    deadline = time.monotonic() + wait_s

    while (running := _running(database_manager)) and time.monotonic() < deadline:
        time.sleep(0.1)

    return running


@pytest.fixture(name='leftovers_killed')
def fixture_leftovers_killed(database_manager: MongoDatabaseManager):
    """Kills whatever the test left running, so a failing run does not keep a mongod core busy for the next tests"""
    yield

    for operation in _running(database_manager):
        database_manager.connector.client.admin.command('killOp', op=operation['opid'])


def _burn_cost_s(database_manager: MongoDatabaseManager, database_name: str, scratch: str, length: int,
                 sample_size: int) -> float:
    """
    What a burn of the given length costs over DOCUMENT_COUNT documents, extrapolated from a small sample

    Args:
        database_manager (MongoDatabaseManager): The connection the sample runs through
        database_name (str): The database owning the scratch collection
        scratch (str): The scratch collection
        length (int): The burn's length
        sample_size (int): How many documents the sample burns

    Returns:
        float: The estimated cost, in seconds
    """
    collection = database_manager.get_collection(scratch, database_name)
    started = time.monotonic()
    list(collection.aggregate([{'$limit': sample_size}, *_burn(length)]))

    return (time.monotonic() - started) * DOCUMENT_COUNT / sample_size


def _stopped_ceiling_s(database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> float:
    """
    How long a stopped burn may have taken: a fraction of what the whole burn costs right now

    Args:
        database_manager (MongoDatabaseManager): The connection the sample runs through
        database_name (str): The database owning the scratch collection
        scratch (str): The scratch collection

    Returns:
        float: The ceiling, in seconds
    """
    cost_s = _burn_cost_s(database_manager, database_name, scratch, BURN_LENGTH, SHORT_BURN_SAMPLE_SIZE)

    return STOPPED_COST_FRACTION * cost_s


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
        ceiling_s = _stopped_ceiling_s(database_manager, database_name, scratch)
        started = time.monotonic()

        with pytest.raises(DocumentQueryTimeLimitError) as exc_info:
            database_manager.aggregate_within_time_limit(scratch, database_name, _burn(), BUDGET_MS, comment=COMMENT)

        assert time.monotonic() - started < ceiling_s
        assert exc_info.value.time_limit_ms == BUDGET_MS

    def test_no_operation_is_left_running(
            self, database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> None:
        """The server stopped it - nothing is still burning a core after the answer"""
        with pytest.raises(DocumentQueryTimeLimitError):
            database_manager.aggregate_within_time_limit(scratch, database_name, _burn(), BUDGET_MS, comment=COMMENT)

        assert not _wait_until_gone(database_manager, MAX_TIME_STOP_WAIT_S)

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
            self, database_manager: MongoDatabaseManager, database_name: str, seeded_objects: list[int],
            scratch: str) -> None:
        """The client's ?filter= reaches the rows and the count, both under the budget"""
        ceiling_s = _stopped_ceiling_s(database_manager, database_name, scratch)
        manager = ObjectsManager(database_manager, database_name)
        criteria = [{'$match': {'public_id': {'$in': seeded_objects}}}, *_burn()]
        started = time.monotonic()

        with pytest.raises(BaseManagerIterationError) as exc_info:
            manager.iterate_query(BuilderParameters(criteria=criteria, time_limit_ms=BUDGET_MS))

        assert time.monotonic() - started < ceiling_s
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


@pytest.mark.usefixtures('leftovers_killed')
class TestTheSocketTimeout:
    """The bound the socket timeout already set - the claim the docs make about it."""

    def test_the_burn_outlasts_the_wait(
            self, database_manager: MongoDatabaseManager, database_name: str, scratch: str) -> None:
        """
        The oracle's precondition: a burn that could finish inside the wait would pass without being stopped

        A faster server shortens the burn; this fails before the socket test turns vacuous
        """
        cost_s = _burn_cost_s(database_manager, database_name, scratch, DISCONNECT_BURN_LENGTH, LONG_BURN_SAMPLE_SIZE)

        assert cost_s > BURN_TO_WAIT_FACTOR * DISCONNECT_STOP_WAIT_S, f'the burn costs only {cost_s:.1f} s'

    def test_a_timed_out_socket_leaves_no_operation_behind(
            self, database_manager: MongoDatabaseManager, mongodb_parameters: tuple, scratch: str) -> None:
        """
        The driver gives up, closes the connection, and the server stops the aggregation on the disconnect

        ``batchSize`` covers every document, so the first reply needs the whole burn and the timeout always falls
        on the ``aggregate`` command itself - never on a ``getMore``, which the server would finish instead
        """
        host, port, database_name = mongodb_parameters
        client = pymongo.MongoClient(host, int(port), socketTimeoutMS=SOCKET_TIMEOUT_MS)

        try:
            with pytest.raises(NetworkTimeout):
                list(client[database_name][scratch].aggregate(
                    _burn(DISCONNECT_BURN_LENGTH), comment=COMMENT, batchSize=DOCUMENT_COUNT,
                ))
        finally:
            client.close()

        assert not _wait_until_gone(database_manager, DISCONNECT_STOP_WAIT_S)
