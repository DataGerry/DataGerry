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
Unit tests for cmdb.framework.port.cable_usage

Pure tests: no Mongo, no Flask. The module answers whether a CmdbPortConnection still needs one of the
Cable CIs about to be deleted, and turns that answer into the refusal the delete routes abort with.

What is pinned here: the whole selection is asked in ONE query (a bulk delete of 200 objects may not
cost 200 reads), an empty selection asks nothing at all, a connection row without usable ids is
skipped rather than reported as a blocker naming nothing, the report is ordered by the cable's
public_id so the message is stable, and the message names every blocked cable with its connection AND
that connection's two ports - the ids the user needs to resolve it.
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.framework.port.cable_usage import CableUsage, cable_usage_blocker, collect_cable_usage
from cmdb.framework.port.connection_constants import CABLE_IN_USE_ABORT_PREFIX, CABLE_IN_USE_SEPARATOR
from cmdb.models.port_connection_model import PortConnectionKey
# -------------------------------------------------------------------------------------------------------------------- #

CABLE_CI_ID: int = 501
OTHER_CABLE_CI_ID: int = 502
CONNECTION_ID: int = 7
OTHER_CONNECTION_ID: int = 8
ENDPOINTS: list[int] = [31, 32]
OTHER_ENDPOINTS: list[int] = [33, 34]


def _connection(
        cable_ci_id: Any = CABLE_CI_ID,
        connection_id: Any = CONNECTION_ID,
        endpoints: Any = None) -> dict[str, Any]:
    """A stored CmdbPortConnection document as the batched read returns it."""
    return {
        PortConnectionKey.PUBLIC_ID.value: connection_id,
        PortConnectionKey.CABLE_CI_ID.value: cable_ci_id,
        PortConnectionKey.ENDPOINTS.value: list(ENDPOINTS) if endpoints is None else endpoints,
    }


def _manager(*connections: dict[str, Any]) -> MagicMock:
    """A PortConnectionsManager answering the batched read with the given documents."""
    manager = MagicMock()
    manager.get_connections_by_cable_cis.return_value = list(connections)

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                collect_cable_usage                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_empty_selection_reads_nothing() -> None:
    """Most deletions carry no cable at all, so the guard must cost nothing for them"""
    manager = _manager()

    assert collect_cable_usage(manager, []) == []
    manager.get_connections_by_cable_cis.assert_not_called()


def test_the_whole_selection_is_asked_in_one_query() -> None:
    """A bulk delete may not pay a read per candidate - the ids go into a single '$in'"""
    manager = _manager(_connection())

    collect_cable_usage(manager, [CABLE_CI_ID, OTHER_CABLE_CI_ID])

    manager.get_connections_by_cable_cis.assert_called_once_with([CABLE_CI_ID, OTHER_CABLE_CI_ID])


def test_a_used_cable_is_reported_with_its_connection_and_ports() -> None:
    """The three ids the refusal needs come straight from the connection document"""
    usages = collect_cable_usage(_manager(_connection()), [CABLE_CI_ID])

    assert usages == [CableUsage(cable_ci_id=CABLE_CI_ID, connection_id=CONNECTION_ID, endpoints=ENDPOINTS)]


def test_a_free_cable_is_not_reported() -> None:
    """Nothing matched means nothing blocks the deletion"""
    assert collect_cable_usage(_manager(), [CABLE_CI_ID]) == []


def test_the_report_is_ordered_by_the_cables_public_id() -> None:
    """The message lists them in this order, and a stable message is a testable one"""
    manager = _manager(
        _connection(OTHER_CABLE_CI_ID, OTHER_CONNECTION_ID, OTHER_ENDPOINTS),
        _connection(),
    )

    assert [usage.cable_ci_id for usage in collect_cable_usage(manager, [CABLE_CI_ID, OTHER_CABLE_CI_ID])] \
        == [CABLE_CI_ID, OTHER_CABLE_CI_ID]


def test_a_connection_without_endpoints_is_still_reported() -> None:
    """The cable is in use whatever shape the row is in; the ports are simply not named"""
    usages = collect_cable_usage(_manager(_connection(endpoints=[])), [CABLE_CI_ID])

    assert usages[0].endpoints == []


def test_a_row_without_usable_ids_is_skipped_and_logged(caplog) -> None:
    """
    A blocker naming no connection tells the user nothing they could act on

    The query matched on cable_ci_id, so a row reaching this without an int id is broken data rather
    than a normal state - which is why it is logged instead of silently dropped.
    """
    manager = _manager(_connection(connection_id=None), _connection(cable_ci_id='not-an-int'))

    with caplog.at_level('WARNING'):
        assert collect_cable_usage(manager, [CABLE_CI_ID]) == []

    assert caplog.text.count('without usable ids') == 2


def test_the_endpoints_are_copied_out_of_the_document() -> None:
    """The usage is handed to a message builder; it may not alias the stored list"""
    document = _connection()

    usage = collect_cable_usage(_manager(document), [CABLE_CI_ID])[0]
    document[PortConnectionKey.ENDPOINTS.value].append(99)

    assert usage.endpoints == ENDPOINTS


# -------------------------------------------------------------------------------------------------------------------- #
#                                                cable_usage_blocker                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_nothing_in_use_blocks_nothing() -> None:
    """None is what lets the delete through"""
    assert cable_usage_blocker([]) is None


def test_the_refusal_names_the_cable_its_connection_and_both_ports() -> None:
    """The message has to say what to resolve, not only that something is in the way"""
    message = cable_usage_blocker(
        [CableUsage(cable_ci_id=CABLE_CI_ID, connection_id=CONNECTION_ID, endpoints=ENDPOINTS)],
    )

    assert message.startswith(CABLE_IN_USE_ABORT_PREFIX)
    assert f'ID:{CABLE_CI_ID}' in message
    assert f'ID:{CONNECTION_ID}' in message
    assert f'{ENDPOINTS[0]}, {ENDPOINTS[1]}' in message


def test_a_bulk_refusal_lists_every_blocked_cable() -> None:
    """The whole selection is refused, so the user gets the whole reason at once"""
    message = cable_usage_blocker([
        CableUsage(cable_ci_id=CABLE_CI_ID, connection_id=CONNECTION_ID, endpoints=ENDPOINTS),
        CableUsage(cable_ci_id=OTHER_CABLE_CI_ID, connection_id=OTHER_CONNECTION_ID,
                   endpoints=OTHER_ENDPOINTS),
    ])

    assert message.count(CABLE_IN_USE_SEPARATOR) == 1
    assert f'ID:{OTHER_CABLE_CI_ID}' in message
    assert f'ID:{OTHER_CONNECTION_ID}' in message
