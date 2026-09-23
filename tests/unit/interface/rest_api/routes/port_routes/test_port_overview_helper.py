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
Unit tests for the ports overview assembly

Pure: no Mongo, no Flask app. Everything the answer depends on is read before these functions run, so
what is pinned here is the shaping - the two row shapes, the pairing being the INTERNAL connection
rather than the names, the one-hop rule for the connected CI, and the masking of a CI the requesting
user may not read. Document keys come from the model key enums per the no-magic-values rule
"""
from typing import Any

import pytest

from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.port_model.port_constants import PortKey, PortSide
from cmdb.models.port_connection_model.port_connection_constants import (
    CABLE_VIEW_KEY,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PORT_CONNECTED_KEY
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import PORT_INTERFACE_LINKS_KEY
from cmdb.interface.rest_api.routes.port_routes.port_overview_constants import (
    ConnectedObjectKey,
    ConnectedPortKey,
    PortOverviewEntryKey,
    PortOverviewKey,
    PortOverviewOptionKey,
    PortOverviewRowKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_overview_helper import (
    PeerEnds,
    build_option_view,
    build_panel_rows,
    build_port_entry,
    build_port_overview,
    build_standard_rows,
    collect_peer_port_ids,
    index_connections_by_kind,
    peer_port_id,
)
# -------------------------------------------------------------------------------------------------------------------- #

FRONT_ID: int = 1
REAR_ID: int = 2
PEER_ID: int = 77
OWNER_OBJECT_ID: int = 10
PEER_OBJECT_ID: int = 900
CABLE_CONNECTION_ID: int = 500
INTERNAL_CONNECTION_ID: int = 501

STATUS_OPTION_ID: int = 41
STATUS_OPTION_TYPE: str = OptionType.PORT_STATUS.value
STATUS_LABEL: str = 'Up'


def _port(public_id: int, side: PortSide, name: str = 'Port', number: int | None = None) -> dict[str, Any]:
    """A stored port as the read route hands it on, with its derived keys."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: PEER_OBJECT_ID if public_id == PEER_ID else OWNER_OBJECT_ID,
        PortKey.SIDE.value: side.value,
        PortKey.NAME.value: name,
        PortKey.PORT_NUMBER.value: number,
        PortKey.DESCRIPTION.value: None,
        PORT_CONNECTED_KEY: False,
        PORT_INTERFACE_LINKS_KEY: [],
    }


def _connection(public_id: int, endpoints: list[int], connection_type: ConnectionType) -> dict[str, Any]:
    """A stored connection carrying its resolved cable block."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: connection_type.value,
        CABLE_VIEW_KEY: {'name': 'Patch 3m'} if connection_type is ConnectionType.CABLE else None,
    }


def _entry_builder(port: dict[str, Any]) -> dict[str, Any]:
    """The smallest entry builder the row builders need: the port id alone."""
    return {PortOverviewEntryKey.PORT_ID.value: port[PortKey.PUBLIC_ID.value]}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  reading connections                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_connections_are_indexed_under_both_of_their_ports() -> None:
    """The stored pair is sorted ascending, so neither position carries meaning"""
    connection = _connection(CABLE_CONNECTION_ID, [PEER_ID, FRONT_ID], ConnectionType.CABLE)

    indexed = index_connections_by_kind([connection], ConnectionType.CABLE)

    assert set(indexed) == {FRONT_ID, PEER_ID}


def test_the_other_kind_is_skipped() -> None:
    """A panel port holds a cable AND a pairing; the two are read separately"""
    connections = [
        _connection(CABLE_CONNECTION_ID, [FRONT_ID, PEER_ID], ConnectionType.CABLE),
        _connection(INTERNAL_CONNECTION_ID, [FRONT_ID, REAR_ID], ConnectionType.INTERNAL),
    ]

    assert index_connections_by_kind(connections, ConnectionType.INTERNAL)[FRONT_ID][
        PortConnectionKey.PUBLIC_ID.value
    ] == INTERNAL_CONNECTION_ID


def test_the_peer_of_a_connection_is_its_other_endpoint() -> None:
    """Seen from one of its ports"""
    connection = _connection(CABLE_CONNECTION_ID, [FRONT_ID, PEER_ID], ConnectionType.CABLE)

    assert peer_port_id(connection, FRONT_ID) == PEER_ID
    assert peer_port_id(connection, PEER_ID) == FRONT_ID


@pytest.mark.parametrize('connection', [None, {}])
def test_a_port_without_a_connection_has_no_peer(connection: Any) -> None:
    """The common state of a free port"""
    assert peer_port_id(connection, FRONT_ID) is None


def test_a_connection_the_port_is_not_part_of_names_nothing() -> None:
    """Reading a peer out of someone else's connection would invent one"""
    assert peer_port_id(_connection(CABLE_CONNECTION_ID, [PEER_ID, REAR_ID], ConnectionType.CABLE), FRONT_ID) is None


def test_peers_on_the_object_itself_are_not_collected() -> None:
    """A cable between two ports of one object names a peer already in hand - re-reading it is a
    query for nothing"""
    ports = [_port(FRONT_ID, PortSide.SINGLE), _port(REAR_ID, PortSide.SINGLE)]
    cable_by_port = index_connections_by_kind(
        [_connection(CABLE_CONNECTION_ID, [FRONT_ID, REAR_ID], ConnectionType.CABLE)], ConnectionType.CABLE,
    )

    assert collect_peer_port_ids(ports, cable_by_port) == []


def test_each_peer_is_collected_once() -> None:
    """Two ports cabled to the same far port cost one read, not two"""
    ports = [_port(FRONT_ID, PortSide.SINGLE), _port(REAR_ID, PortSide.SINGLE)]
    cable_by_port = {FRONT_ID: _connection(CABLE_CONNECTION_ID, [FRONT_ID, PEER_ID], ConnectionType.CABLE),
                     REAR_ID: _connection(CABLE_CONNECTION_ID + 1, [REAR_ID, PEER_ID], ConnectionType.CABLE)}

    assert collect_peer_port_ids(ports, cable_by_port) == [PEER_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the connected CI                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_connected_ci_is_the_owner_of_the_peer_port() -> None:
    """One cable hop: a device cabled into a patch panel reports the panel"""
    peers = PeerEnds(
        ports_by_id={PEER_ID: _port(PEER_ID, PortSide.SINGLE, 'Gi1/1')},
        summary_lines={PEER_OBJECT_ID: 'Switch #900'},
        accessible_ids={PEER_OBJECT_ID},
    )

    connected = peers.connected_object(PEER_ID)

    assert connected[ConnectedObjectKey.OBJECT_ID.value] == PEER_OBJECT_ID
    assert connected[ConnectedObjectKey.LABEL.value] == 'Switch #900'
    assert connected[ConnectedObjectKey.RESTRICTED.value] is False


def test_a_ci_the_user_may_not_read_is_reported_without_its_label() -> None:
    """The id is already implied by the connection the user may read; the summary line is not"""
    peers = PeerEnds(
        ports_by_id={PEER_ID: _port(PEER_ID, PortSide.SINGLE, 'Gi1/1')},
        summary_lines={},
        accessible_ids=set(),
    )

    connected = peers.connected_object(PEER_ID)

    assert connected[ConnectedObjectKey.RESTRICTED.value] is True
    assert connected[ConnectedObjectKey.LABEL.value] is None


def test_the_far_end_port_is_named_without_a_second_read() -> None:
    """A user names a connection port first, device second - both halves come off one read"""
    peers = PeerEnds(
        ports_by_id={PEER_ID: _port(PEER_ID, PortSide.REAR, 'Gi1/1')}, accessible_ids={PEER_OBJECT_ID},
    )

    connected = peers.connected_port(PEER_ID)

    assert connected[ConnectedPortKey.PORT_ID.value] == PEER_ID
    assert connected[ConnectedPortKey.NAME.value] == 'Gi1/1'
    assert connected[ConnectedPortKey.SIDE.value] == PortSide.REAR.value


def test_a_far_port_of_a_denied_object_is_reported_by_id_alone() -> None:
    """`GET /ports/<id>` answers 403 for that port, so its NAME may not leak through this response"""
    peers = PeerEnds(ports_by_id={PEER_ID: _port(PEER_ID, PortSide.REAR, 'Gi1/1')}, accessible_ids=set())

    connected = peers.connected_port(PEER_ID)

    assert connected[ConnectedPortKey.PORT_ID.value] == PEER_ID
    assert connected[ConnectedPortKey.NAME.value] is None
    assert connected[ConnectedPortKey.SIDE.value] is None


def test_a_port_with_no_cable_names_no_far_port() -> None:
    """A free port, which is the common state"""
    assert PeerEnds().connected_port(None) is None


def test_a_far_port_that_could_not_be_read_names_nothing() -> None:
    """A dangling endpoint - inventing a name would be worse than saying nothing"""
    assert PeerEnds().connected_port(PEER_ID) is None


def test_a_port_with_no_cable_has_no_connected_ci() -> None:
    """A free port, which is the common state"""
    assert PeerEnds().connected_object(None) is None


def test_a_peer_port_that_could_not_be_read_has_no_connected_ci() -> None:
    """A dangling endpoint names no object, and inventing one would be worse than saying nothing"""
    assert PeerEnds().connected_object(PEER_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the port entry                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_option_resolves_to_its_id_and_its_label() -> None:
    """The panel shows the label; an edit form needs the id to preselect the option"""
    view = build_option_view(STATUS_OPTION_ID, {STATUS_OPTION_ID: STATUS_LABEL})

    assert view == {
        PortOverviewOptionKey.ID.value: STATUS_OPTION_ID,
        PortOverviewOptionKey.LABEL.value: STATUS_LABEL,
    }


def test_an_option_whose_list_entry_is_gone_keeps_its_id() -> None:
    """The port still holds that value - reporting no id would read as 'nothing selected'"""
    view = build_option_view(STATUS_OPTION_ID, {})

    assert view[PortOverviewOptionKey.ID.value] == STATUS_OPTION_ID
    assert view[PortOverviewOptionKey.LABEL.value] is None


def test_a_port_holding_no_option_reports_both_as_none() -> None:
    """An unset select field"""
    assert build_option_view(None, {STATUS_OPTION_ID: STATUS_LABEL}) == {
        PortOverviewOptionKey.ID.value: None,
        PortOverviewOptionKey.LABEL.value: None,
    }


def test_the_entry_carries_the_cable_and_the_connection_it_belongs_to() -> None:
    """The cable is what the column reads; its connection id is what a disconnect acts on"""
    port = _port(FRONT_ID, PortSide.SINGLE, number=1)
    cable = _connection(CABLE_CONNECTION_ID, [FRONT_ID, PEER_ID], ConnectionType.CABLE)
    peers = PeerEnds(
        {PEER_ID: _port(PEER_ID, PortSide.SINGLE, 'Gi1/1')}, {PEER_OBJECT_ID: 'Switch #900'}, {PEER_OBJECT_ID},
    )

    entry = build_port_entry(port, {}, {FRONT_ID: cable}, peers)

    assert entry[PortOverviewEntryKey.CABLE.value] == {'name': 'Patch 3m'}
    assert entry[PortOverviewEntryKey.CABLE_CONNECTION_ID.value] == CABLE_CONNECTION_ID
    assert entry[PortOverviewEntryKey.CONNECTED_OBJECT.value][ConnectedObjectKey.OBJECT_ID.value] == PEER_OBJECT_ID
    assert entry[PortOverviewEntryKey.CONNECTED_PORT.value][ConnectedPortKey.PORT_ID.value] == PEER_ID


def test_a_free_port_carries_neither_cable_nor_connection() -> None:
    """Both keys are present and null rather than missing, so the column has one shape"""
    entry = build_port_entry(_port(FRONT_ID, PortSide.SINGLE), {}, {}, PeerEnds())

    assert entry[PortOverviewEntryKey.CABLE.value] is None
    assert entry[PortOverviewEntryKey.CABLE_CONNECTION_ID.value] is None
    assert entry[PortOverviewEntryKey.CONNECTED_PORT.value] is None
    assert entry[PortOverviewEntryKey.CONNECTED_OBJECT.value] is None


def test_the_entry_resolves_all_three_select_fields() -> None:
    """Status, port type and speed all come back as {id, label}"""
    port = {**_port(FRONT_ID, PortSide.SINGLE), PortKey.STATUS.value: STATUS_OPTION_ID}
    labels = {STATUS_OPTION_TYPE: {STATUS_OPTION_ID: STATUS_LABEL}}

    entry = build_port_entry(port, labels, {}, PeerEnds())

    assert entry[PortKey.STATUS.value][PortOverviewOptionKey.LABEL.value] == STATUS_LABEL
    assert entry[PortKey.PORT_TYPE.value][PortOverviewOptionKey.ID.value] is None
    assert entry[PortKey.SPEED.value][PortOverviewOptionKey.ID.value] is None


def test_the_entry_passes_the_interface_links_through() -> None:
    """The client owns how an interface is named, so the links are handed on as they are read"""
    link = {'public_id': 7, 'relation_type': 'PHYSICAL'}
    port = {**_port(FRONT_ID, PortSide.SINGLE), PORT_INTERFACE_LINKS_KEY: [link]}

    assert build_port_entry(port, {}, {}, PeerEnds())[PortOverviewEntryKey.INTERFACE_LINKS.value] == [link]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      the rows                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_standard_device_gets_one_row_per_port() -> None:
    """In the order the ports were read"""
    ports = [_port(FRONT_ID, PortSide.SINGLE, number=1), _port(REAR_ID, PortSide.SINGLE, number=2)]

    rows = build_standard_rows(ports, _entry_builder)

    assert [row[PortOverviewRowKey.PORT.value][PortOverviewEntryKey.PORT_ID.value] for row in rows] == [
        FRONT_ID, REAR_ID,
    ]


def test_a_panel_pairs_a_row_by_its_internal_connection() -> None:
    """The pairing IS the connection - the names are never consulted"""
    ports = [_port(FRONT_ID, PortSide.FRONT, 'F1', 1), _port(REAR_ID, PortSide.REAR, 'nothing-alike', 1)]
    internal = index_connections_by_kind(
        [_connection(INTERNAL_CONNECTION_ID, [FRONT_ID, REAR_ID], ConnectionType.INTERNAL)],
        ConnectionType.INTERNAL,
    )

    rows = build_panel_rows(ports, internal, _entry_builder)

    assert len(rows) == 1
    assert rows[0][PortOverviewRowKey.FRONT.value][PortOverviewEntryKey.PORT_ID.value] == FRONT_ID
    assert rows[0][PortOverviewRowKey.REAR.value][PortOverviewEntryKey.PORT_ID.value] == REAR_ID
    assert rows[0][PortOverviewRowKey.PAIRED.value] is True


def test_a_front_with_no_pairing_is_listed_with_an_empty_rear() -> None:
    """A half-built panel has to be visible to be fixable"""
    rows = build_panel_rows([_port(FRONT_ID, PortSide.FRONT)], {}, _entry_builder)

    assert rows[0][PortOverviewRowKey.REAR.value] is None
    assert rows[0][PortOverviewRowKey.PAIRED.value] is False


def test_a_rear_no_front_claims_is_listed_on_its_own() -> None:
    """The other half of the same rule - a rear face is not silently dropped"""
    rows = build_panel_rows([_port(REAR_ID, PortSide.REAR)], {}, _entry_builder)

    assert rows[0][PortOverviewRowKey.FRONT.value] is None
    assert rows[0][PortOverviewRowKey.REAR.value][PortOverviewEntryKey.PORT_ID.value] == REAR_ID


def test_a_paired_rear_is_not_listed_twice() -> None:
    """It already appears in its front's row"""
    ports = [_port(FRONT_ID, PortSide.FRONT), _port(REAR_ID, PortSide.REAR)]
    internal = index_connections_by_kind(
        [_connection(INTERNAL_CONNECTION_ID, [FRONT_ID, REAR_ID], ConnectionType.INTERNAL)],
        ConnectionType.INTERNAL,
    )

    assert len(build_panel_rows(ports, internal, _entry_builder)) == 1


def test_unpaired_rears_follow_the_front_rows() -> None:
    """Front faces lead, so the table reads front to back"""
    ports = [_port(FRONT_ID, PortSide.FRONT), _port(REAR_ID, PortSide.REAR)]

    rows = build_panel_rows(ports, {}, _entry_builder)

    assert rows[0][PortOverviewRowKey.FRONT.value] is not None
    assert rows[1][PortOverviewRowKey.FRONT.value] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the whole payload                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_device_kind_chooses_the_row_shape() -> None:
    """Which is the property the client branches on"""
    panel = build_port_overview(
        [_port(FRONT_ID, PortSide.FRONT)], [], PortDeviceKind.PATCH_PANEL.value, {}, PeerEnds(),
    )
    standard = build_port_overview(
        [_port(FRONT_ID, PortSide.SINGLE)], [], PortDeviceKind.STANDARD.value, {}, PeerEnds(),
    )

    assert PortOverviewRowKey.FRONT.value in panel[PortOverviewKey.ROWS.value][0]
    assert PortOverviewRowKey.PORT.value in standard[PortOverviewKey.ROWS.value][0]


def test_an_object_without_ports_names_no_kind() -> None:
    """It is still free to become either, so naming one would be a guess"""
    overview = build_port_overview([], [], None, {}, PeerEnds())

    assert overview[PortOverviewKey.DEVICE_KIND.value] is None
    assert overview[PortOverviewKey.ROWS.value] == []
    assert overview[PortOverviewKey.TOTAL.value] == 0


def test_the_total_counts_rows_and_not_ports() -> None:
    """A panel's two faces are one row, which is what the pagination of the panel counts"""
    ports = [_port(FRONT_ID, PortSide.FRONT), _port(REAR_ID, PortSide.REAR)]
    connections = [_connection(INTERNAL_CONNECTION_ID, [FRONT_ID, REAR_ID], ConnectionType.INTERNAL)]

    overview = build_port_overview(ports, connections, PortDeviceKind.PATCH_PANEL.value, {}, PeerEnds())

    assert overview[PortOverviewKey.TOTAL.value] == 1
