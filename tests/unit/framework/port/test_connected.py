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
Unit tests for cmdb.framework.port.connected

The derivation that replaces a stored flag. One case carries the module: a connection stores its two
endpoints in ONE array, sorted ascending, so a given port is sometimes the first element and sometimes
the second - which of the two is an accident of the ids the user happened to pick. A projection reading
one position only would report roughly half of all connected ports as free, and a test using a single
fixed pair would not notice. Every assertion here that matters exercises both positions.

Pure tests: no Mongo, no Flask, no managers - the connections are handed in as plain dicts
"""
from typing import Any

import pytest

from cmdb.framework.port.connected import collect_connected_port_ids, project_connected
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTED_KEY: str = 'connected'

LOW_PORT: int = 3
HIGH_PORT: int = 10
FREE_PORT: int = 7
REAR_PORT: int = 21


def _connection(
        endpoints: Any,
        connection_type: str = ConnectionType.CABLE.value,
        **overrides: Any) -> dict[str, Any]:
    """A stored connection document, endpoints given exactly as passed."""
    connection: dict[str, Any] = {
        PortConnectionKey.ENDPOINTS.value: endpoints,
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
    }
    connection.update(overrides)

    return connection


def _port(public_id: Any) -> dict[str, Any]:
    """A stored port document - only the id the projection reads."""
    return {PortKey.PUBLIC_ID.value: public_id, PortKey.NAME.value: f'port-{public_id}'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             collecting the connected ids                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectConnectedPortIds:
    """Both ends of every connection, because neither position means anything."""

    def test_both_endpoints_are_collected(self) -> None:
        """
        The whole point of the module

        A port at the second position is exactly as connected as one at the first.
        """
        assert collect_connected_port_ids([_connection([LOW_PORT, HIGH_PORT])]) == {LOW_PORT, HIGH_PORT}

    def test_ids_from_several_connections_are_merged(self) -> None:
        """A page of ports is answered by one batched read, so the set spans every row it returned"""
        connected = collect_connected_port_ids([
            _connection([LOW_PORT, HIGH_PORT]),
            _connection([REAR_PORT, HIGH_PORT], ConnectionType.INTERNAL.value),
        ])

        assert connected == {LOW_PORT, HIGH_PORT, REAR_PORT}

    def test_no_connections_is_an_empty_set(self) -> None:
        """The common case for an object whose ports are all free"""
        assert collect_connected_port_ids([]) == set()

    def test_a_tuple_of_endpoints_is_read_too(self) -> None:
        """A document read back through a driver may hand over either sequence type"""
        assert collect_connected_port_ids([_connection((LOW_PORT, HIGH_PORT))]) == {LOW_PORT, HIGH_PORT}

    @pytest.mark.parametrize('endpoints', [None, 'x', 5, {}], ids=str)
    def test_a_drifted_endpoints_value_is_skipped_rather_than_raising(self, endpoints: Any) -> None:
        """
        A read path must never fail on a row it did not write

        A connection whose endpoints are unusable makes no port connected; it must not take the whole
        ports panel down with it.
        """
        assert collect_connected_port_ids([_connection(endpoints)]) == set()

    def test_a_non_integer_endpoint_is_skipped(self) -> None:
        """Only real port ids count - a stray value would never match a port's public_id anyway"""
        assert collect_connected_port_ids([_connection([LOW_PORT, 'not-an-id'])]) == {LOW_PORT}

    def test_one_drifted_row_does_not_hide_the_others(self) -> None:
        """The usable rows still answer, which is what keeps the panel readable"""
        connected = collect_connected_port_ids([
            _connection(None),
            _connection([LOW_PORT, HIGH_PORT]),
        ])

        assert connected == {LOW_PORT, HIGH_PORT}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the projection                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestProjectConnected:
    """Every port in a response gets the flag."""

    @pytest.mark.parametrize('port_id', [LOW_PORT, HIGH_PORT], ids=['first-in-pair', 'second-in-pair'])
    def test_a_port_at_either_end_reports_connected(self, port_id: int) -> None:
        """
        The regression this module exists to prevent

        Parametrized over BOTH positions of the sorted pair: a projection looking at one only would
        pass for one of these and fail for the other, and with a single fixed pair the failing half
        would depend on nothing but the ids chosen.
        """
        ports = project_connected(
            [_port(port_id)], [_connection([LOW_PORT, HIGH_PORT])], CONNECTED_KEY,
        )

        assert ports[0][CONNECTED_KEY] is True

    def test_a_free_port_reports_false(self) -> None:
        """The other half - 'Free' is what the frontend renders from it"""
        ports = project_connected(
            [_port(FREE_PORT)], [_connection([LOW_PORT, HIGH_PORT])], CONNECTED_KEY,
        )

        assert ports[0][CONNECTED_KEY] is False

    def test_every_port_receives_the_key(self) -> None:
        """
        Including the free ones

        A response where the key is present on some rows and absent on others would make the frontend
        distinguish 'free' from 'unknown', and there is no such state.
        """
        ports = project_connected(
            [_port(LOW_PORT), _port(FREE_PORT)], [_connection([LOW_PORT, HIGH_PORT])], CONNECTED_KEY,
        )

        assert all(CONNECTED_KEY in port for port in ports)

    def test_a_panel_port_with_two_connections_reports_connected_once(self) -> None:
        """A front port holds a cable AND an internal pairing; the flag is still a plain boolean"""
        ports = project_connected(
            [_port(HIGH_PORT)],
            [
                _connection([LOW_PORT, HIGH_PORT]),
                _connection([HIGH_PORT, REAR_PORT], ConnectionType.INTERNAL.value),
            ],
            CONNECTED_KEY,
        )

        assert ports[0][CONNECTED_KEY] is True

    def test_an_internal_connection_alone_counts_as_connected(self) -> None:
        """
        A panel face paired to its counterpart is not free

        The flag says 'something is plugged in here', and the internal pairing is exactly that - the
        concept treats it as one of the three connections of a full physical path.
        """
        ports = project_connected(
            [_port(HIGH_PORT)],
            [_connection([HIGH_PORT, REAR_PORT], ConnectionType.INTERNAL.value)],
            CONNECTED_KEY,
        )

        assert ports[0][CONNECTED_KEY] is True

    def test_no_connections_marks_every_port_free(self) -> None:
        """An object whose ports are all unused"""
        ports = project_connected([_port(LOW_PORT), _port(FREE_PORT)], [], CONNECTED_KEY)

        assert [port[CONNECTED_KEY] for port in ports] == [False, False]

    def test_an_empty_page_is_returned_unchanged(self) -> None:
        """An object with no ports at all"""
        assert project_connected([], [_connection([LOW_PORT, HIGH_PORT])], CONNECTED_KEY) == []

    def test_the_flag_is_a_real_boolean(self) -> None:
        """
        Not a truthy value

        The frontend renders Free / Connected from it, and a JSON client comparing against false has to
        get a false rather than a null or a missing key.
        """
        ports = project_connected([_port(FREE_PORT)], [], CONNECTED_KEY)

        assert isinstance(ports[0][CONNECTED_KEY], bool)

    def test_a_port_without_a_usable_id_reports_free_rather_than_raising(self) -> None:
        """A drifted port row must not take the response down"""
        ports = project_connected(
            [_port(None)], [_connection([LOW_PORT, HIGH_PORT])], CONNECTED_KEY,
        )

        assert ports[0][CONNECTED_KEY] is False

    def test_the_other_port_fields_are_untouched(self) -> None:
        """The projection adds one key and changes nothing else"""
        ports = project_connected([_port(LOW_PORT)], [], CONNECTED_KEY)

        assert ports[0][PortKey.NAME.value] == f'port-{LOW_PORT}'
        assert ports[0][PortKey.PUBLIC_ID.value] == LOW_PORT

    def test_the_key_is_the_one_the_caller_names(self) -> None:
        """
        The response key is passed in, not imported

        It is deliberately not a member of PortKey - there is no such field on a stored port - so the
        projection must not hard-code it.
        """
        ports = project_connected([_port(LOW_PORT)], [], 'some_other_key')

        assert 'some_other_key' in ports[0]
        assert CONNECTED_KEY not in ports[0]
