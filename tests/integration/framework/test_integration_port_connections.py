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
Integration tests for the CmdbPortConnection collection and its manager against a real MongoDB

This is where the value of the whole feature is measured, because the connection's cardinality rules
are held by the DATABASE and by nothing else. Four things only a real MongoDB can show:

  1. one port may hold one CABLE and one INTERNAL connection at the same time - a patch panel is
     unbuildable otherwise - while a SECOND cable on the same port is refused by the index
  2. a duplicate pair is refused, and so is the same pair entered in the OPPOSITE order, which works
     only because the endpoints are stored sorted
  3. one cable CI belongs to at most one connection, while any number of connections carrying no CI
     coexist - the presence-filtered index
  4. the plain multikey index really finds a port at either end, and the delete cascades scope
     themselves to the ports actually being removed

The trap being guarded is that a plain unique index on 'endpoints' would be MULTIKEY-unique, meaning
no two documents may share any element - so no port could appear in two connections at all. A unit
test asserting the declaration would pass either way; only a real index refuses or accepts.

Note the fixture builds the model's declared indexes itself. The test database is never taken through
CollectionValidator (conftest drops the database and seeds users, nothing more), so its collections
are created implicitly by the first write and carry no index but '_id_'. Building them here is what
the application does at startup, and without it every assertion below would silently pass against a
collection that has no constraint at all
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.framework.port.cascade import (
    delete_connections_of_ports,
    port_ids_of_object,
    delete_connections_of_port,
    delete_ports_of_object,
)
from cmdb.models.port_connection_model import (
    CmdbPortConnection,
    ConnectionType,
    PortConnectionKey,
    CABLE_CI_INDEX_NAME,
    ENDPOINTS_CABLE_INDEX_NAME,
    ENDPOINTS_INDEX_NAME,
    ENDPOINTS_INTERNAL_INDEX_NAME,
)
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests take the 'connections' fixture purely for its side effect - it builds the declared
# indexes and clears the collection - and never touch the handle it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

# A patch panel's front and rear ports plus the two devices patched into it
FRONT_PORT: int = 48101
REAR_PORT: int = 48102
SERVER_PORT: int = 48103
SWITCH_PORT: int = 48104
SPARE_PORT: int = 48105

CONNECTION_IDS: list[int] = [48201, 48202, 48203, 48204, 48205]

CABLE_CI_ID: int = 48301
OTHER_CABLE_CI_ID: int = 48302


def _connection_doc(
        public_id: int,
        endpoints: list[int],
        connection_type: str = ConnectionType.CABLE.value,
        **overrides: Any) -> dict[str, Any]:
    """
    Builds a stored CmdbPortConnection document

    The endpoints are sorted here exactly as the model sorts them on write, because the sort is what
    the pair-uniqueness assertions depend on.
    """
    doc: dict[str, Any] = {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
        PortConnectionKey.CABLE_NAME.value: None,
        PortConnectionKey.CABLE_TYPE.value: None,
        PortConnectionKey.CABLE_LENGTH.value: None,
        PortConnectionKey.CABLE_COLOR.value: None,
        PortConnectionKey.CABLE_DESCRIPTION.value: None,
        PortConnectionKey.AUTHOR_ID.value: 1,
        PortConnectionKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortConnectionKey.LAST_EDIT_TIME.value: None,
    }
    doc.update(overrides)

    return doc


@pytest.fixture(name='connections')
def fixture_connections(database_manager: MongoDatabaseManager, database_name: str):
    """
    Gives the raw collection with the model's declared indexes built, cleared around each test

    The index build is what CollectionValidator does at application startup; the test database never
    goes through it (see the module docstring), so it happens here instead.
    """
    collection = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    collection.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}})
    database_manager.create_indexes(
        CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys(),
    )

    yield collection

    collection.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> PortConnectionsManager:
    """A real PortConnectionsManager backed by the test database"""
    return PortConnectionsManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the indexes really exist                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_all_four_declared_indexes_are_built(connections) -> None:
    """
    Index reconciliation is name-based and never compares options

    A declaration that silently stopped being unique or partial would change nothing anywhere else in
    the codebase, so the built index is what has to be asserted.
    """
    built = connections.index_information()

    for index_name in (ENDPOINTS_CABLE_INDEX_NAME, ENDPOINTS_INTERNAL_INDEX_NAME,
                       ENDPOINTS_INDEX_NAME, CABLE_CI_INDEX_NAME):
        assert index_name in built


@pytest.mark.parametrize('index_name,connection_type', [
    (ENDPOINTS_CABLE_INDEX_NAME, ConnectionType.CABLE.value),
    (ENDPOINTS_INTERNAL_INDEX_NAME, ConnectionType.INTERNAL.value),
])
def test_the_cardinality_indexes_are_unique_and_partial(
        connections, index_name: str, connection_type: str) -> None:
    """Both properties matter: unique makes the refusal, partial keeps it inside one type"""
    index = connections.index_information()[index_name]

    assert index.get('unique') is True
    assert index.get('partialFilterExpression') == {
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                       Q4's hard refusal: one cable per port                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_second_cable_on_the_same_port_is_refused_by_the_database(connections) -> None:
    """
    The feature's single most important guarantee, and it is the index that makes it

    An application check would be a read followed by a write, which two concurrent requests walk
    straight through - and this is exactly the case that a port_a_id/port_b_id pair of scalars could
    not express as an index at all, because the port lands in a different field each time.
    """
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(CONNECTION_IDS[1], [FRONT_PORT, SWITCH_PORT]))


def test_the_refusal_holds_whichever_side_the_port_was_entered_on(connections) -> None:
    """
    The measured failure of the two-scalar-fields design

    Port FRONT_PORT is the SECOND id of the first pair and the FIRST id of the second. With
    port_a_id/port_b_id and a unique index on each, the second insert is accepted and the port ends
    up with two cables; with one array it is refused.
    """
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(CONNECTION_IDS[1], [FRONT_PORT, SPARE_PORT]))

    assert connections.count_documents({PortConnectionKey.ENDPOINTS.value: FRONT_PORT}) == 1


def test_a_port_may_hold_one_cable_and_one_internal_connection(connections) -> None:
    """
    Without this a patch panel would be unbuildable

    A front port carries the internal pairing to its rear port AND the cable to the server. The two
    partial indexes never see each other's documents, which is the whole reason there are two.
    """
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[0], [FRONT_PORT, REAR_PORT], ConnectionType.INTERNAL.value,
    ))
    connections.insert_one(_connection_doc(CONNECTION_IDS[1], [SERVER_PORT, FRONT_PORT]))

    assert connections.count_documents({PortConnectionKey.ENDPOINTS.value: FRONT_PORT}) == 2


def test_a_second_internal_connection_on_the_same_port_is_refused(connections) -> None:
    """A front port pairs with exactly one rear port"""
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[0], [FRONT_PORT, REAR_PORT], ConnectionType.INTERNAL.value,
    ))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(
            CONNECTION_IDS[1], [FRONT_PORT, SPARE_PORT], ConnectionType.INTERNAL.value,
        ))


def test_an_unrelated_port_pair_is_accepted(connections) -> None:
    """
    The refusals above must not be a blanket one

    A unique index over an array without the partial filter would forbid this too, once either port
    already appeared anywhere.
    """
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]))
    connections.insert_one(_connection_doc(CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT]))

    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}}) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                        no duplicate pair, in either spelling                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_same_pair_twice_is_refused(connections) -> None:
    """Falls out of the cardinality index for free - no rule of its own is needed"""
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(CONNECTION_IDS[1], [SERVER_PORT, FRONT_PORT]))


def test_the_same_pair_in_the_opposite_order_collides_thanks_to_the_sort(connections) -> None:
    """
    Why the endpoints are stored sorted

    Without the sort these would be two different arrays, the index would see two different keys and
    the same link would exist twice - once per spelling.
    """
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [FRONT_PORT, SERVER_PORT]))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(CONNECTION_IDS[1], [SERVER_PORT, FRONT_PORT]))


def test_the_model_sorts_what_the_manager_writes(connections, manager: PortConnectionsManager) -> None:
    """
    The stored shape is what the indexes depend on, so the write path has to produce it

    Written through the manager rather than the raw collection, because the model's constructor is
    where the canonical form is applied.
    """
    new_id: int = manager.insert_item(CmdbPortConnection(
        public_id=CONNECTION_IDS[0],
        endpoints=[SWITCH_PORT, SERVER_PORT],
        connection_type=ConnectionType.CABLE.value,
    ))

    stored = connections.find_one({PortConnectionKey.PUBLIC_ID.value: new_id})

    assert stored[PortConnectionKey.ENDPOINTS.value] == sorted([SERVER_PORT, SWITCH_PORT])


# -------------------------------------------------------------------------------------------------------------------- #
#                                        one cable CI, one connection                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_second_connection_claiming_the_same_cable_ci_is_refused(connections) -> None:
    """
    Reusing one inventoried cable on two links is a data-entry error, not a use case

    Enforced by the index rather than a read-then-write check, so it holds under concurrency.
    """
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT],
        **{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID},
    ))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(
            CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT],
            **{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID},
        ))


def test_two_connections_with_different_cable_cis_are_accepted(connections) -> None:
    """The refusal is about the same CI, not about carrying one"""
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT],
        **{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID},
    ))
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT],
        **{PortConnectionKey.CABLE_CI_ID.value: OTHER_CABLE_CI_ID},
    ))

    assert connections.count_documents(
        {PortConnectionKey.CABLE_CI_ID.value: {'$exists': True}}) == 2


def test_any_number_of_connections_without_a_cable_ci_coexist(connections) -> None:
    """
    The reason the index is filtered on the key's PRESENCE

    Scenario A - cable info with no CI - is the common case. An unfiltered unique index would treat
    every one of them as the same missing value and refuse the second.
    """
    connections.insert_one(_connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]))
    connections.insert_one(_connection_doc(CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT]))
    connections.insert_one(_connection_doc(CONNECTION_IDS[2], [SPARE_PORT, SWITCH_PORT + 100]))

    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}}) == 3


def test_a_stored_null_cable_ci_would_break_the_index(connections) -> None:
    """
    Why to_json OMITS the key instead of writing null

    A null is a PRESENT value, so it falls inside the filter - two such documents collide. This test
    documents the failure the model's omission avoids, so a future 'tidy up' that always writes the
    key fails here with its reason attached.
    """
    connections.insert_one(_connection_doc(
        CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT],
        **{PortConnectionKey.CABLE_CI_ID.value: None},
    ))

    with pytest.raises(DuplicateKeyError):
        connections.insert_one(_connection_doc(
            CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT],
            **{PortConnectionKey.CABLE_CI_ID.value: None},
        ))


def test_the_model_never_writes_that_null(connections, manager: PortConnectionsManager) -> None:
    """The other half of the test above: two CI-less connections written through the model coexist"""
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT]),
    ))

    assert connections.count_documents(
        {PortConnectionKey.CABLE_CI_ID.value: {'$exists': True}}) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the manager                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_manager_round_trips_a_connection(connections, manager: PortConnectionsManager) -> None:
    """A connection inserted through the manager comes back as a CmdbPortConnection"""
    new_id: int = manager.insert_item(CmdbPortConnection.from_data(_connection_doc(
        CONNECTION_IDS[0], [SWITCH_PORT, SERVER_PORT],
        **{
            PortConnectionKey.CABLE_NAME.value: 'Patch 1',
            PortConnectionKey.CABLE_LENGTH.value: '2.5 m',
        },
    )))

    stored = manager.get_item(new_id)

    assert isinstance(stored, CmdbPortConnection)
    assert stored.endpoints == sorted([SERVER_PORT, SWITCH_PORT])
    assert stored.cable_name == 'Patch 1'
    assert stored.cable_length == '2.5 m'


def test_the_manager_finds_a_port_at_either_end(connections, manager: PortConnectionsManager) -> None:
    """
    One indexed predicate matches the array element wherever it sits

    With two scalar fields every such read would be an $or over both of them.
    """
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))

    assert len(manager.get_connections_of_port(SERVER_PORT)) == 1
    assert len(manager.get_connections_of_port(FRONT_PORT)) == 1


def test_the_manager_reads_a_whole_page_of_ports_at_once(
        connections, manager: PortConnectionsManager) -> None:
    """The batched read the computed 'connected' flag runs once per response"""
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT]),
    ))

    found = manager.get_connections_of_ports([SERVER_PORT, SWITCH_PORT])

    assert {connection[PortConnectionKey.PUBLIC_ID.value] for connection in found} == {
        CONNECTION_IDS[0], CONNECTION_IDS[1],
    }


def test_a_free_port_has_no_connections(connections, manager: PortConnectionsManager) -> None:
    """The common case, and what the computed flag reports as 'Free'"""
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))

    assert manager.get_connections_of_port(SPARE_PORT) == []


def test_deleting_a_ports_connections_leaves_its_peers_free(
        connections, manager: PortConnectionsManager) -> None:
    """
    A connection must not outlive an endpoint, and the peer needs no rewrite

    'connected' is computed, so freeing a peer is simply the connection being gone.
    """
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [FRONT_PORT, REAR_PORT], ConnectionType.INTERNAL.value),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[2], [REAR_PORT, SWITCH_PORT]),
    ))

    removed: int = manager.delete_connections_of_ports([FRONT_PORT, REAR_PORT])

    assert removed == 3
    assert manager.get_connections_of_port(SERVER_PORT) == []
    assert manager.get_connections_of_port(SWITCH_PORT) == []


def test_deleting_one_ports_connections_leaves_the_others_untouched(
        connections, manager: PortConnectionsManager) -> None:
    """
    The rule to honour from the start: removing one connection must never remove another

    A filter that was slightly too wide would silently unpatch half a rack.
    """
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [REAR_PORT, SWITCH_PORT]),
    ))

    assert manager.delete_connections_of_ports([SERVER_PORT]) == 1
    assert len(manager.get_connections_of_port(REAR_PORT)) == 1


def test_the_freed_pair_may_be_connected_again(connections, manager: PortConnectionsManager) -> None:
    """
    Guards against a delete that only marks rows instead of removing them

    The unique index would then refuse the next cable between the same two ports.
    """
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.delete_connections_of_ports([SERVER_PORT])

    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [SERVER_PORT, FRONT_PORT]),
    ))

    assert len(manager.get_connections_of_port(SERVER_PORT)) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the cascades, against stored rows                                               #
# -------------------------------------------------------------------------------------------------------------------- #
PANEL_OBJECT_ID: int = 48401
PEER_OBJECT_ID: int = 48402
OBJECT_IDS: list[int] = [PANEL_OBJECT_ID, PEER_OBJECT_ID]


@pytest.fixture(name='ports_manager')
def fixture_ports_manager(database_manager: MongoDatabaseManager) -> PortsManager:
    """A real PortsManager backed by the test database"""
    return PortsManager(database_manager)


@pytest.fixture(name='ports')
def fixture_ports(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the panel's two faces and the two peer device ports, cleared around each test

    Real port documents rather than mocks, because what the object cascade has to get right is
    resolving the doomed ports' ids BEFORE they are deleted - a mocked read cannot show that.
    """
    collection = database_manager.get_collection(CmdbPort.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})

    _purge()
    collection.insert_many([
        {
            PortKey.PUBLIC_ID.value: FRONT_PORT,
            PortKey.OBJECT_ID.value: PANEL_OBJECT_ID,
            PortKey.SIDE.value: PortSide.FRONT.value,
            PortKey.NAME.value: '1',
        },
        {
            PortKey.PUBLIC_ID.value: REAR_PORT,
            PortKey.OBJECT_ID.value: PANEL_OBJECT_ID,
            PortKey.SIDE.value: PortSide.REAR.value,
            PortKey.NAME.value: '1',
        },
        {
            PortKey.PUBLIC_ID.value: SERVER_PORT,
            PortKey.OBJECT_ID.value: PEER_OBJECT_ID,
            PortKey.SIDE.value: PortSide.SINGLE.value,
            PortKey.NAME.value: 'eth0',
        },
        {
            PortKey.PUBLIC_ID.value: SWITCH_PORT,
            PortKey.OBJECT_ID.value: PEER_OBJECT_ID,
            PortKey.SIDE.value: PortSide.SINGLE.value,
            PortKey.NAME.value: 'Gi0/1',
        },
    ])

    yield collection

    _purge()


def _seed_full_path(manager: PortConnectionsManager) -> None:
    """
    Seeds the three connections a full physical path through a patch panel is made of

    server -> front (cable), front -> rear (the panel's internal pairing), rear -> switch (cable).
    """
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[0], [SERVER_PORT, FRONT_PORT]),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[1], [FRONT_PORT, REAR_PORT], ConnectionType.INTERNAL.value),
    ))
    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[2], [REAR_PORT, SWITCH_PORT]),
    ))


def test_deleting_one_port_removes_both_of_its_connections(
        connections, manager: PortConnectionsManager) -> None:
    """A panel's front port holds a cable AND an internal pairing, and loses both"""
    _seed_full_path(manager)

    assert delete_connections_of_port(manager, FRONT_PORT) == 2
    assert manager.get_connections_of_port(FRONT_PORT) == []


def test_deleting_one_port_leaves_the_rest_of_the_path_intact(
        connections, manager: PortConnectionsManager) -> None:
    """
    The rule that resolving or deleting one connection must never delete another

    A cascade whose filter was slightly too wide would silently unpatch the rear half of the panel
    as well.
    """
    _seed_full_path(manager)

    delete_connections_of_port(manager, SERVER_PORT)

    assert len(manager.get_connections_of_port(REAR_PORT)) == 2


def test_the_object_cascade_removes_every_connection_of_its_ports(
        connections, ports, ports_manager: PortsManager, manager: PortConnectionsManager) -> None:
    """
    Deleting the panel takes all three connections, because both of its faces were endpoints

    The ids come from a real read of framework.ports, which is the part a mocked test cannot show.
    """
    _seed_full_path(manager)

    removed: int = delete_connections_of_ports(manager, port_ids_of_object(ports_manager, PANEL_OBJECT_ID))

    assert removed == 3
    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}}) == 0


def test_the_object_cascade_leaves_another_objects_links_alone(
        connections, ports, ports_manager: PortsManager, manager: PortConnectionsManager) -> None:
    """Deleting the peer device takes its two cables but not the panel's internal pairing"""
    _seed_full_path(manager)

    removed: int = delete_connections_of_ports(manager, port_ids_of_object(ports_manager, PEER_OBJECT_ID))

    assert removed == 2
    assert len(manager.get_connections_of_port(FRONT_PORT)) == 1


def test_an_object_without_ports_removes_nothing(
        connections, ports, ports_manager: PortsManager, manager: PortConnectionsManager) -> None:
    """The common case on every object deletion"""
    _seed_full_path(manager)

    assert delete_connections_of_ports(manager, port_ids_of_object(ports_manager, 48499)) == 0
    assert connections.count_documents(
        {PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}}) == 3


def test_the_full_object_cascade_leaves_nothing_dangling(
        connections, ports, ports_manager: PortsManager, manager: PortConnectionsManager) -> None:
    """
    Both halves in the order the hook runs them, measured end to end

    This is the failure the ordering exists to prevent: with the ports deleted first there would be
    no way left to find the connections that named them, and the three rows would survive their own
    endpoints.
    """
    _seed_full_path(manager)

    delete_connections_of_ports(manager, port_ids_of_object(ports_manager, PANEL_OBJECT_ID))
    delete_ports_of_object(ports_manager, {'public_id': PANEL_OBJECT_ID})

    assert ports.count_documents({PortKey.OBJECT_ID.value: PANEL_OBJECT_ID}) == 0
    assert manager.get_connections_of_ports([FRONT_PORT, REAR_PORT]) == []


def test_the_peers_of_a_deleted_object_are_free_again(
        connections, ports, ports_manager: PortsManager, manager: PortConnectionsManager) -> None:
    """
    Nothing about a peer is rewritten - `connected` is computed, so freeing it needs no write

    Proven by the peer port accepting a new cable straight afterwards, which the unique index would
    refuse if the old row had survived.
    """
    _seed_full_path(manager)

    delete_connections_of_ports(manager, port_ids_of_object(ports_manager, PANEL_OBJECT_ID))
    delete_ports_of_object(ports_manager, {'public_id': PANEL_OBJECT_ID})

    manager.insert_item(CmdbPortConnection.from_data(
        _connection_doc(CONNECTION_IDS[3], [SERVER_PORT, SWITCH_PORT]),
    ))

    assert len(manager.get_connections_of_port(SERVER_PORT)) == 1
