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
Unit tests for cmdb.framework.port.bulk_actions

The pure half of §30-35's three actions - edit, delete and resolve. Every one of these functions
reports rather than raises, because the SAME cores back the delete and its pre-check: a preview that
answers has to mean a delete that will not be refused.

What is pinned hardest is the all-or-nothing contract. A bulk action is validated as a whole, so these
blockers exist to make a refusal complete - every reason at once - rather than to stop at the first
bad id and leave the caller to discover the rest one request at a time.
"""
from typing import Any

import pytest

from cmdb.framework.port.bulk_action_constants import BULK_EDITABLE_FIELDS, BulkDeletePreviewKey
from cmdb.framework.port.bulk_actions import (
    build_bulk_edit_values,
    build_delete_preview,
    bulk_edit_value_blockers,
    coerce_id_selection,
    collect_ids,
    connection_selection_blockers,
    port_selection_blockers,
)
from cmdb.models.port_model import PortKey, PortSide
from cmdb.models.port_connection_model import PortConnectionKey
from cmdb.models.port_interface_link_model import PortInterfaceLinkKey
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 700
OTHER_OBJECT_ID: int = 701
PORT_A: int = 10
PORT_B: int = 11
FOREIGN_PORT: int = 12
MISSING_PORT: int = 99

CONNECTION_A: int = 50
CONNECTION_B: int = 51
FOREIGN_CONNECTION: int = 52
MISSING_CONNECTION: int = 98

LINK_A: int = 80
PEER_PORT: int = 20


def _port(public_id: int, object_id: int = OBJECT_ID, **overrides: Any) -> dict[str, Any]:
    """A stored port document, with the keys the bulk actions read."""
    port: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.NAME.value: f'Gi0/{public_id}',
        PortKey.SIDE.value: PortSide.SINGLE.value,
    }
    port.update(overrides)

    return port


def _ports_by_id(*ports: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """The read-once mapping the selection rules are judged against."""
    return {port[PortKey.PUBLIC_ID.value]: port for port in ports}


def _connection(public_id: int, endpoints: list[int]) -> dict[str, Any]:
    """A stored connection document."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: endpoints,
    }


def _link(public_id: int, port_id: int) -> dict[str, Any]:
    """A stored interface link document."""
    return {PortInterfaceLinkKey.PUBLIC_ID.value: public_id, PortInterfaceLinkKey.PORT_ID.value: port_id}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the selection                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCoerceIdSelection:
    """What a checkbox column may send."""

    def test_a_list_of_ids_is_read(self) -> None:
        """The ordinary case"""
        assert coerce_id_selection([PORT_A, PORT_B]) == [PORT_A, PORT_B]

    def test_the_callers_order_is_kept(self) -> None:
        """A report reads back the way the selection was made"""
        assert coerce_id_selection([PORT_B, PORT_A]) == [PORT_B, PORT_A]

    def test_duplicates_are_collapsed(self) -> None:
        """A table can send the same row twice and it means the same thing"""
        assert coerce_id_selection([PORT_A, PORT_B, PORT_A]) == [PORT_A, PORT_B]

    @pytest.mark.parametrize('sent', [None, [], 'all', 7, {}, [PORT_A, 'x'], [PORT_A, None]], ids=str)
    def test_an_unusable_selection_is_rejected(self, sent: Any) -> None:
        """An empty selection is rejected too: a bulk action over nothing is a client bug"""
        assert coerce_id_selection(sent) is None

    def test_a_boolean_is_not_an_id(self) -> None:
        """bool is an int subclass in Python, so True would otherwise pass as the id 1"""
        assert coerce_id_selection([True]) is None


class TestPortSelectionBlockers:
    """Every selected port has to be one of THIS object's."""

    def test_this_objects_ports_pass(self) -> None:
        """The ordinary case"""
        ports = _ports_by_id(_port(PORT_A), _port(PORT_B))

        assert port_selection_blockers(ports, OBJECT_ID, [PORT_A, PORT_B]) == []

    def test_a_port_that_does_not_exist_is_named(self) -> None:
        """A stale table is a different mistake from a wrong list, and the message says which"""
        blockers = port_selection_blockers(_ports_by_id(_port(PORT_A)), OBJECT_ID, [PORT_A, MISSING_PORT])

        assert len(blockers) == 1
        assert str(MISSING_PORT) in blockers[0]

    def test_another_objects_port_is_refused(self) -> None:
        """
        A selection can only name rows of the table the user is looking at

        An id from another device means the client built its selection from the wrong list - obeying
        it would edit or delete a port nobody could see in that view.
        """
        ports = _ports_by_id(_port(PORT_A), _port(FOREIGN_PORT, OTHER_OBJECT_ID))

        blockers = port_selection_blockers(ports, OBJECT_ID, [PORT_A, FOREIGN_PORT])

        assert len(blockers) == 1
        assert str(FOREIGN_PORT) in blockers[0]
        assert str(OBJECT_ID) in blockers[0]

    def test_every_reason_is_reported(self) -> None:
        """The whole point of the all-or-nothing contract: one refusal, every fault"""
        ports = _ports_by_id(_port(PORT_A), _port(FOREIGN_PORT, OTHER_OBJECT_ID))

        blockers = port_selection_blockers(ports, OBJECT_ID, [PORT_A, FOREIGN_PORT, MISSING_PORT])

        assert len(blockers) == 2


class TestConnectionSelectionBlockers:
    """A connection belongs to no single device, so 'this object's' means: one end on it."""

    def test_a_connection_with_one_end_on_the_object_passes(self) -> None:
        """A cable reaching another device is resolvable from either end - it is the same act"""
        connections = {CONNECTION_A: _connection(CONNECTION_A, [PORT_A, PEER_PORT])}

        assert connection_selection_blockers(connections, {PORT_A}, OBJECT_ID, [CONNECTION_A]) == []

    def test_a_connection_with_both_ends_on_the_object_passes(self) -> None:
        """The patch panel's internal pairing"""
        connections = {CONNECTION_B: _connection(CONNECTION_B, [PORT_A, PORT_B])}

        assert connection_selection_blockers(
            connections, {PORT_A, PORT_B}, OBJECT_ID, [CONNECTION_B],
        ) == []

    def test_a_connection_that_does_not_exist_is_named(self) -> None:
        """An id nothing answers to"""
        blockers = connection_selection_blockers({}, {PORT_A}, OBJECT_ID, [MISSING_CONNECTION])

        assert len(blockers) == 1
        assert str(MISSING_CONNECTION) in blockers[0]

    def test_a_connection_touching_neither_port_is_refused(self) -> None:
        """Two other devices' ports: resolving it from this table would be acting out of view"""
        connections = {FOREIGN_CONNECTION: _connection(FOREIGN_CONNECTION, [PEER_PORT, FOREIGN_PORT])}

        blockers = connection_selection_blockers(
            connections, {PORT_A}, OBJECT_ID, [FOREIGN_CONNECTION],
        )

        assert len(blockers) == 1
        assert str(OBJECT_ID) in blockers[0]

    def test_a_connection_without_endpoints_is_refused(self) -> None:
        """A malformed row cannot be shown to touch anything, so it is not silently resolved"""
        connections = {CONNECTION_A: {PortConnectionKey.PUBLIC_ID.value: CONNECTION_A}}

        assert connection_selection_blockers(connections, {PORT_A}, OBJECT_ID, [CONNECTION_A]) != []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the bulk EDIT                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkEditValues:
    """Only the four shared properties, and a field outside them is reported."""

    def test_the_allowed_fields_pass(self) -> None:
        """Status, port type, speed and description - what a selection can sensibly share"""
        values = {field.value: 1 for field in BULK_EDITABLE_FIELDS}

        assert bulk_edit_value_blockers(values) == []

    def test_a_subset_is_enough(self) -> None:
        """"Set the speed of these twelve" must not require sending their statuses too"""
        assert bulk_edit_value_blockers({PortKey.SPEED.value: 3}) == []

    @pytest.mark.parametrize('field', [
        PortKey.NAME.value, PortKey.PORT_NUMBER.value, PortKey.OBJECT_ID.value, PortKey.SIDE.value,
    ])
    def test_an_identifying_field_is_refused(self, field: str) -> None:
        """
        Reported, never dropped

        A name identifies a port within its face, so one value across a selection collides by
        construction - and silently ignoring it would answer 200 to a request that asked to rename
        twelve ports.
        """
        blockers = bulk_edit_value_blockers({field: 'x'})

        assert len(blockers) == 1
        assert field in blockers[0]

    @pytest.mark.parametrize('sent', [None, {}, [], 'status'], ids=str)
    def test_an_empty_or_unusable_values_block_is_refused(self, sent: Any) -> None:
        """A bulk edit that sets nothing is a client bug, not a no-op worth answering 200 to"""
        assert bulk_edit_value_blockers(sent) != []

    def test_every_unknown_field_is_reported(self) -> None:
        """One refusal, every fault"""
        assert len(bulk_edit_value_blockers({'name': 'x', 'side': 'front'})) == 2


class TestBuildBulkEditValues:
    """What actually reaches the `$set`."""

    def test_only_the_fields_the_request_carries(self) -> None:
        """A field left out keeps whatever each port already has"""
        assert build_bulk_edit_values({PortKey.SPEED.value: 3}) == {PortKey.SPEED.value: 3}

    def test_a_null_is_kept(self) -> None:
        """Null IS a value here - it is how a description is cleared across a selection"""
        assert build_bulk_edit_values({PortKey.DESCRIPTION.value: None}) == {
            PortKey.DESCRIPTION.value: None,
        }

    def test_the_fields_come_out_in_the_models_order(self) -> None:
        """So two identical requests produce the same document, whatever order they were written in"""
        values = {PortKey.DESCRIPTION.value: 'x', PortKey.STATUS.value: 1}

        assert list(build_bulk_edit_values(values)) == [PortKey.STATUS.value, PortKey.DESCRIPTION.value]


# -------------------------------------------------------------------------------------------------------------------- #
#                                             the delete pre-check                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildDeletePreview:
    """§41's 'inform the user of the consequences', per port."""

    def test_a_port_names_what_it_would_lose(self) -> None:
        """Deleting a port is never only the port"""
        preview = build_delete_preview(
            [_port(PORT_A)], [_connection(CONNECTION_A, [PORT_A, PEER_PORT])], [_link(LINK_A, PORT_A)],
        )

        assert preview == [{
            BulkDeletePreviewKey.PORT_ID.value: PORT_A,
            BulkDeletePreviewKey.NAME.value: f'Gi0/{PORT_A}',
            BulkDeletePreviewKey.SIDE.value: PortSide.SINGLE.value,
            BulkDeletePreviewKey.CONNECTION_IDS.value: [CONNECTION_A],
            BulkDeletePreviewKey.INTERFACE_LINK_IDS.value: [LINK_A],
        }]

    def test_a_port_that_loses_nothing_still_appears(self) -> None:
        """The dialog lists the whole selection, not only the rows with consequences"""
        preview = build_delete_preview([_port(PORT_A)], [], [])

        assert preview[0][BulkDeletePreviewKey.CONNECTION_IDS.value] == []
        assert preview[0][BulkDeletePreviewKey.INTERFACE_LINK_IDS.value] == []

    def test_a_shared_connection_appears_under_both_ports(self) -> None:
        """
        Deliberate: the dialog lists per port what THAT row loses

        A panel's internal pairing joins two selected ports, and each row has to show it. The distinct
        count comes from the action's own answer instead.
        """
        preview = build_delete_preview(
            [_port(PORT_A), _port(PORT_B)], [_connection(CONNECTION_B, [PORT_A, PORT_B])], [],
        )

        assert preview[0][BulkDeletePreviewKey.CONNECTION_IDS.value] == [CONNECTION_B]
        assert preview[1][BulkDeletePreviewKey.CONNECTION_IDS.value] == [CONNECTION_B]

    def test_another_ports_dependents_are_not_listed(self) -> None:
        """The preview is per port, not per batch"""
        preview = build_delete_preview(
            [_port(PORT_A)], [_connection(CONNECTION_A, [PORT_B, PEER_PORT])], [_link(LINK_A, PORT_B)],
        )

        assert preview[0][BulkDeletePreviewKey.CONNECTION_IDS.value] == []
        assert preview[0][BulkDeletePreviewKey.INTERFACE_LINK_IDS.value] == []

    def test_the_order_of_the_selection_is_kept(self) -> None:
        """The dialog lists the rows the way the user ticked them"""
        preview = build_delete_preview([_port(PORT_B), _port(PORT_A)], [], [])

        assert [entry[BulkDeletePreviewKey.PORT_ID.value] for entry in preview] == [PORT_B, PORT_A]


class TestCollectIds:
    """The distinct totals a report answers with."""

    def test_the_ids_come_back_once_each(self) -> None:
        """A connection between two selected ports is ONE row the delete removes, not two"""
        connections = [_connection(CONNECTION_A, [PORT_A, PORT_B]), _connection(CONNECTION_A, [PORT_A])]

        assert collect_ids(connections, PortConnectionKey.PUBLIC_ID.value) == [CONNECTION_A]

    def test_the_order_is_kept(self) -> None:
        """Stable output, so a client can diff two answers"""
        connections = [_connection(CONNECTION_B, []), _connection(CONNECTION_A, [])]

        assert collect_ids(connections, PortConnectionKey.PUBLIC_ID.value) == [CONNECTION_B, CONNECTION_A]

    def test_a_row_without_the_key_is_skipped(self) -> None:
        """A malformed row must not put a null into a report"""
        assert collect_ids([{}, _connection(CONNECTION_A, [])], PortConnectionKey.PUBLIC_ID.value) == [
            CONNECTION_A,
        ]
