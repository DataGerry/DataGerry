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
Copying a CmdbObject's ports onto another CmdbObject - the port half of cloning an object

A clone gets a new port for every port of its source, carrying the same side, name, number and field values,
and the source's INTERNAL connections (a patch panel's front-to-rear pairing) remapped onto the new ports. A
CABLE connection is never copied: it joins the source's port to another device, and that port can hold one cable
only. The ports' interface links are not copied either - they name the source object's interface rows

The writes are recorded in the caller's WriteLedger before they run, so a failure leaves nothing behind
"""
from datetime import datetime, timezone
from typing import Any, NamedTuple

from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey, sort_endpoints
from cmdb.models.port_model import PortKey

from cmdb.framework.port.port_clone_constants import CLONED_PORT_KEYS
from cmdb.framework.write_ledger import WriteLedger
# -------------------------------------------------------------------------------------------------------------------- #

class PortClonePlan(NamedTuple):
    """
    What cloning a source object's ports will write, read before the clone's object is written

    Attributes:
        ports (list[dict[str, Any]]): The source's ports, in the order they are listed
        internal_pairs (list[tuple[int, int]]): The source port ids of each INTERNAL connection between two of
            them
    """
    ports: list[dict[str, Any]]
    internal_pairs: list[tuple[int, int]]


class PortCloneResult(NamedTuple):
    """
    What a clone wrote

    Attributes:
        port_ids (list[int]): public_ids of the new ports, in the source's order
        connection_ids (list[int]): public_ids of the new INTERNAL connections
    """
    port_ids: list[int]
    connection_ids: list[int]


def internal_pairs_of(port_ids: set[int], connections: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """
    The INTERNAL connections that join two of the given ports

    Args:
        port_ids (set[int]): public_ids of the source's ports
        connections (list[dict[str, Any]]): The connections touching any of them

    Returns:
        list[tuple[int, int]]: The two port ids of each INTERNAL connection whose both ends are in `port_ids`
    """
    pairs: list[tuple[int, int]] = []

    for connection in connections:
        endpoints: Any = connection.get(PortConnectionKey.ENDPOINTS.value)

        if connection.get(PortConnectionKey.CONNECTION_TYPE.value) != ConnectionType.INTERNAL.value:
            continue

        if isinstance(endpoints, list) and len(endpoints) == 2 and set(endpoints) <= port_ids:
            pairs.append((endpoints[0], endpoints[1]))

    return pairs


def cloned_port_documents(
        source_ports: list[dict[str, Any]],
        target_object_id: int,
        author_id: int,
        created_at: datetime) -> list[dict[str, Any]]:
    """
    The new port documents of a clone, one per source port and in the same order

    Args:
        source_ports (list[dict[str, Any]]): The source's ports
        target_object_id (int): public_id of the CmdbObject the new ports belong to
        author_id (int): public_id of the CmdbUser cloning
        created_at (datetime): The creation time every new port carries

    Returns:
        list[dict[str, Any]]: The documents to insert - without a public_id
    """
    return [{
        **{key.value: port[key.value] for key in CLONED_PORT_KEYS if key.value in port},
        PortKey.OBJECT_ID.value: target_object_id,
        PortKey.AUTHOR_ID.value: author_id,
        PortKey.CREATION_TIME.value: created_at,
        PortKey.LAST_EDIT_TIME.value: None,
    } for port in source_ports]


def cloned_connection_documents(
        internal_pairs: list[tuple[int, int]],
        new_port_ids: dict[int, int],
        author_id: int,
        created_at: datetime) -> list[dict[str, Any]]:
    """
    The new INTERNAL connections of a clone, each joining the new ports that replace a source pair

    Args:
        internal_pairs (list[tuple[int, int]]): The source port ids of each INTERNAL connection
        new_port_ids (dict[int, int]): The new port's public_id for each source port's
        author_id (int): public_id of the CmdbUser cloning
        created_at (datetime): The creation time every new connection carries

    Returns:
        list[dict[str, Any]]: The documents to insert - without a public_id
    """
    return [{
        PortConnectionKey.ENDPOINTS.value: sort_endpoints([new_port_ids[first], new_port_ids[second]]),
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
        PortConnectionKey.AUTHOR_ID.value: author_id,
        PortConnectionKey.CREATION_TIME.value: created_at,
        PortConnectionKey.LAST_EDIT_TIME.value: None,
    } for first, second in internal_pairs]


def clone_ports(
        ports_manager: PortsManager,
        port_connections_manager: PortConnectionsManager,
        plan: PortClonePlan,
        target_object_id: int,
        author_id: int,
        ledger: WriteLedger) -> PortCloneResult:
    """
    Writes a clone's ports, then the INTERNAL connections that pair them

    Ports first: a connection names two port ids, so it can only be written once both exist. Each batch is
    recorded in `ledger` by what its documents match before it runs - the target's ports, and the INTERNAL
    connections of the new ports - since an unordered batch that fails does not say which documents it stored

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        plan (PortClonePlan): The source's ports and INTERNAL pairs
        target_object_id (int): public_id of the CmdbObject the new ports belong to; it holds no port yet
        author_id (int): public_id of the CmdbUser cloning
        ledger (WriteLedger): The request's record of its writes

    Raises:
        PortsManagerInsertError: When the ports could not be written
        PortConnectionsManagerInsertError: When the connections could not be written

    Returns:
        PortCloneResult: The new ports' and connections' public_ids
    """
    if not plan.ports:
        return PortCloneResult(port_ids=[], connection_ids=[])

    created_at: datetime = datetime.now(timezone.utc)

    ledger.inserted_where(ports_manager, {PortKey.OBJECT_ID.value: target_object_id})
    port_ids: list[int] = ports_manager.insert_many_items(
        cloned_port_documents(plan.ports, target_object_id, author_id, created_at),
    )

    if not plan.internal_pairs:
        return PortCloneResult(port_ids=port_ids, connection_ids=[])

    new_port_ids: dict[int, int] = {
        port[PortKey.PUBLIC_ID.value]: new_id for port, new_id in zip(plan.ports, port_ids, strict=True)
    }

    ledger.inserted_where(port_connections_manager, {
        PortConnectionKey.ENDPOINTS.value: {'$in': port_ids},
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
    })
    connection_ids: list[int] = port_connections_manager.insert_many_items(
        cloned_connection_documents(plan.internal_pairs, new_port_ids, author_id, created_at),
    )

    return PortCloneResult(port_ids=port_ids, connection_ids=connection_ids)
