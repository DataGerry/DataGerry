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
Reading a bulk-creation request body, and reading the created rows back for the response
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_connection_model import PortConnectionKey
from cmdb.models.port_model import PortKey

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRequestKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The port fields a whole batch may share. The name and the side come from the preview, one per port;
# these are the assistant form's "apply to all of them" values - a customer creating 48 uplinks almost
# always wants them all Up / SFP+ / 10G, and setting that afterwards would mean 48 more requests
SHARED_PORT_REQUEST_KEYS: tuple[PortRequestKey, ...] = (
    PortRequestKey.STATUS,
    PortRequestKey.PORT_TYPE,
    PortRequestKey.SPEED,
    PortRequestKey.DESCRIPTION,
)

# -------------------------------------------------------------------------------------------------------------------- #

def build_shared_port_values(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Reads the field values every port of a batch will carry

    Only the keys a request owns: the identity, the owner, the side, the name and the audit fields are
    the batch's own business and are never read from here. A key the body omits is left out entirely
    rather than written as null, so the model's own defaults still apply

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The shared field values, empty when the body sets none
    """
    return {
        PortKey[key.name].value: payload[key.value]
        for key in SHARED_PORT_REQUEST_KEYS
        if payload.get(key.value) is not None
    }


def read_created_ports(ports_manager: PortsManager, port_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the ports a batch created, in one query, ordered as they were created

    The frontend renders the new ports straight from the response, so they come back as stored rather
    than as the candidates that were sent - which is what makes the server-owned fields visible

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_ids (list[int]): The created ports' public_ids, in creation order

    Returns:
        list[dict[str, Any]]: The created port documents, in creation order
    """
    return _read_in_order(ports_manager, PortKey.PUBLIC_ID.value, port_ids)


def read_created_connections(
        port_connections_manager: PortConnectionsManager,
        connection_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the INTERNAL connections a panel's creation produced, in one query

    Returned rather than left for the caller to look up, because those connections ARE the pairing -
    a client that had to go and find them could not tell which front port was joined to which rear one

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        connection_ids (list[int]): The created connections' public_ids, in creation order

    Returns:
        list[dict[str, Any]]: The created connection documents, in creation order
    """
    return _read_in_order(port_connections_manager, PortConnectionKey.PUBLIC_ID.value, connection_ids)


def _read_in_order(manager: Any, id_key: str, public_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads rows by public_id and returns them in the order the ids were given

    One `$in` rather than one read per row, then re-ordered in memory: Mongo answers an `$in` in index
    order, not in the order asked for, and a panel whose pairing is read back scrambled would be
    unreadable beside its connections

    Args:
        manager (Any): The manager owning the collection
        id_key (str): Name of the collection's public_id field
        public_ids (list[int]): The ids to read, in the order they should come back

    Returns:
        list[dict[str, Any]]: The rows, in the requested order; missing ones are skipped
    """
    if not public_ids:
        return []

    by_id: dict[int, dict[str, Any]] = {
        row[id_key]: row
        for row in manager.find(criteria={id_key: {'$in': public_ids}})
        if id_key in row
    }

    return [by_id[public_id] for public_id in public_ids if public_id in by_id]
