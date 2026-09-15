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
Integration tests for the bulk port creation against a real MongoDB

The two the plan calls the important ones, and they are the only place §37 can actually be measured:

  1. **force a failure mid-batch** and assert nothing is left behind - counted in the collections, not
     in the return value, because a rollback that reported success while rows survived is precisely the
     failure being guarded against
  2. **force a failure during the rollback** and assert the result reports the residue rather than
     claiming a clean failure

DataGerry requires no replica set, so there is no transaction to lean on; the compensating rollback is
all there is, and a real database is what shows whether it worked. The unique index on
(object_id, side, name) is built here too, so a mid-batch duplicate fails the way it would in
production rather than succeeding on a constraint-free collection
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_connection_model import CmdbPortConnection, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.framework.port.bulk_create import create_batch
from cmdb.framework.port.name_syntax_constants import PortPreviewKey
# -------------------------------------------------------------------------------------------------------------------- #
# The fixtures are taken for their side effect - building the declared indexes and clearing the
# collections - and several tests never touch the handles they yield
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 47901
AUTHOR_ID: int = 1


def _face(side: str, names: list[str]) -> dict[str, Any]:
    """One face of a preview."""
    return {PortPreviewKey.SIDE.value: side, PortPreviewKey.NAMES.value: names}


def _standard(names: list[str]) -> dict[str, Any]:
    """A standard device's preview."""
    return {PortPreviewKey.FACES.value: [_face(PortSide.SINGLE.value, names)]}


def _panel(front: list[str], rear: list[str]) -> dict[str, Any]:
    """A patch panel's preview."""
    return {PortPreviewKey.FACES.value: [
        _face(PortSide.FRONT.value, front), _face(PortSide.REAR.value, rear),
    ]}


@pytest.fixture(name='ports')
def fixture_ports(database_manager: MongoDatabaseManager, database_name: str):
    """
    The raw port collection with the model's declared indexes built, cleared around each test

    The index build is what CollectionValidator does at startup; without it a mid-batch duplicate would
    simply succeed and the rollback would never be exercised at all.
    """
    collection = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    collection.delete_many({PortKey.OBJECT_ID.value: OBJECT_ID})
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    yield collection

    collection.delete_many({PortKey.OBJECT_ID.value: OBJECT_ID})


@pytest.fixture(name='connections')
def fixture_connections(database_manager: MongoDatabaseManager, database_name: str, ports):
    """The raw connection collection with its indexes built, cleared around each test."""
    collection = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    database_manager.create_indexes(
        CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys(),
    )

    def _purge() -> None:
        stored = [row[PortKey.PUBLIC_ID.value]
                  for row in ports.find({PortKey.OBJECT_ID.value: OBJECT_ID})]
        collection.delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': stored}})

    _purge()

    yield collection

    _purge()


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager) -> tuple[PortsManager, PortConnectionsManager]:
    """Real managers backed by the test database."""
    return PortsManager(database_manager), PortConnectionsManager(database_manager)


def _count_ports(ports) -> int:
    """How many ports the object currently has."""
    return ports.count_documents({PortKey.OBJECT_ID.value: OBJECT_ID})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the happy paths                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_standard_batch_is_written(ports, connections, managers) -> None:
    """The ordinary case, against real documents and real indexes"""
    ports_manager, connections_manager = managers

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2', '3']), AUTHOR_ID,
    )

    assert result.succeeded()
    assert _count_ports(ports) == 3


def test_a_panel_is_written_and_paired(ports, connections, managers) -> None:
    """Four ports and two INTERNAL connections, with the pairing stored as endpoints"""
    ports_manager, connections_manager = managers

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _panel(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
    )

    assert result.succeeded()
    assert _count_ports(ports) == 4
    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': result.connection_ids}}) == 2


def test_the_pairing_survives_the_real_unique_indexes(ports, connections, managers) -> None:
    """
    Every internal connection is a distinct pair, so the partial unique index accepts all of them

    A pairing that joined the same port twice would be refused by the index rather than by anything in
    the application - which is exactly where it should be caught.
    """
    ports_manager, connections_manager = managers

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID,
        _panel(['F1', 'F2', 'F3'], ['R1', 'R2', 'R3']), AUTHOR_ID,
    )

    assert result.succeeded()
    assert len(result.connection_ids) == 3


def test_a_panels_front_and_rear_may_share_a_name(ports, connections, managers) -> None:
    """
    The reason 'side' is part of the unique key

    A batch naming both faces identically is legal, and a unique (object_id, name) index would have
    made every patch panel uncreatable.
    """
    ports_manager, connections_manager = managers

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _panel(['1', '2'], ['1', '2']), AUTHOR_ID,
    )

    assert result.succeeded()
    assert _count_ports(ports) == 4


# -------------------------------------------------------------------------------------------------------------------- #
#                              §37: a failure mid-batch leaves NOTHING behind                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_duplicate_mid_batch_rolls_the_whole_thing_back(ports, connections, managers) -> None:
    """
    The first of the two tests this step exists for

    A port is seeded so the batch's third name collides. The unique index refuses it - the way it would
    in production - and the two already written have to be gone afterwards. Counted in the collection,
    because a rollback trusting its own return value is what §37 forbids.
    """
    ports_manager, connections_manager = managers
    ports.insert_one({
        PortKey.PUBLIC_ID.value: 47950,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: '3',
    })

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2', '3']), AUTHOR_ID,
    )

    assert not result.succeeded()
    assert not result.has_residue()
    # Only the seeded port survives - nothing the batch created does
    assert _count_ports(ports) == 1


def test_a_panel_failing_on_its_rear_face_leaves_no_front_ports(ports, connections, managers) -> None:
    """
    Never 24 front / 18 rear / 18 internal

    The rear face collides, so the front face - already fully written - has to come back out too.
    """
    ports_manager, connections_manager = managers
    ports.insert_one({
        PortKey.PUBLIC_ID.value: 47951,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.REAR.value,
        PortKey.NAME.value: 'R2',
    })

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _panel(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
    )

    assert not result.succeeded()
    assert not result.has_residue()
    assert _count_ports(ports) == 1


def test_a_failed_batch_creates_no_connections(ports, connections, managers) -> None:
    """
    A panel whose ports were rolled back must leave no pairing either

    Counted against THIS batch's connection ids rather than against every INTERNAL connection in the
    collection: a global count would pass or fail depending on what other tests happened to leave
    behind, which is a fragile way to assert a scoped rule.
    """
    ports_manager, connections_manager = managers
    ports.insert_one({
        PortKey.PUBLIC_ID.value: 47952,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.REAR.value,
        PortKey.NAME.value: 'R1',
    })

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _panel(['F1'], ['R1']), AUTHOR_ID,
    )

    assert not result.succeeded()
    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': result.connection_ids or [0]}}) == 0


def test_the_names_are_free_again_after_a_rollback(ports, connections, managers) -> None:
    """
    Guards against a rollback that only marks rows

    The unique index would then refuse the retry, and the customer could never fix their batch.
    """
    ports_manager, connections_manager = managers
    seeded = {
        PortKey.PUBLIC_ID.value: 47953,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: '2',
    }
    ports.insert_one(seeded)

    create_batch(ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2']), AUTHOR_ID)
    ports.delete_one({PortKey.PUBLIC_ID.value: 47953})

    retried = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2']), AUTHOR_ID,
    )

    assert retried.succeeded()
    assert _count_ports(ports) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                          §37: a failure DURING the rollback is reported, not hidden                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_rollback_that_cannot_delete_reports_the_residue(ports, connections, managers, monkeypatch) -> None:
    """
    The second of the two tests this step exists for

    The cleanup is broken deliberately, so the ports the batch wrote really do survive. The result has
    to say so and name them - reporting a clean failure here is the one outcome §37 singles out, and it
    would leave a half-built device that nobody knows to remove.
    """
    ports_manager, connections_manager = managers
    ports.insert_one({
        PortKey.PUBLIC_ID.value: 47954,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: '3',
    })

    def _broken_delete(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('the cleanup itself failed')

    monkeypatch.setattr(PortsManager, 'delete_many', _broken_delete)

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2', '3']), AUTHOR_ID,
    )

    assert not result.succeeded()
    assert result.has_residue()
    # Named, not counted - somebody has to go and remove exactly these
    assert result.residual_port_ids == sorted(result.port_ids)
    assert _count_ports(ports) == 3


def test_the_residue_is_what_really_survived_not_what_was_attempted(
        ports, connections, managers, monkeypatch) -> None:
    """
    The residue comes from a verification READ, not from the delete's own report

    Here the cleanup half works: the delete removes the rows but is made to raise afterwards, so a
    rollback trusting its exception would report residue that is not there. Only reading back gives the
    truth.
    """
    ports_manager, connections_manager = managers
    ports.insert_one({
        PortKey.PUBLIC_ID.value: 47955,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: '2',
    })

    real_delete = PortsManager.delete_many

    def _delete_then_raise(self, filter_query):
        real_delete(self, filter_query)
        raise RuntimeError('reported a failure it did not have')

    monkeypatch.setattr(PortsManager, 'delete_many', _delete_then_raise)

    result = create_batch(
        ports_manager, connections_manager, OBJECT_ID, _standard(['1', '2']), AUTHOR_ID,
    )

    assert not result.succeeded()
    assert not result.has_residue()
    assert _count_ports(ports) == 1
