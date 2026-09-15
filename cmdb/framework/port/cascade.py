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
What happens to a CmdbObject's ports, their connections and their interface links when the object
itself is deleted

A port belongs to exactly one CmdbObject and is stored outside that object's document, and a
connection is stored outside both of the ports it joins - so nothing removes either when an object
goes. Without this cascade a deleted object would leave its ports behind as rows nothing can reach,
and those ports' connections behind as links whose endpoint no longer resolves.

**The order is the whole trick.** A connection names its endpoints and a port does not name its
connections, so the ports have to be READ before they are deleted: once they are gone there is no way
left to find the connections that pointed at them. Every function here therefore resolves the port ids
first, removes the connections, and only then removes the ports.

The peer at the other end of a removed connection is simply free again. Nothing about it is rewritten,
because `connected` is computed from this collection on read and never stored.

**The interface links go the same way, and the asymmetry is deliberate.** A link's reference to its
PORT is hard - a link without its port is a row nothing can reach - so a deleted port takes its links
with it. Its reference to the interface ROW is soft, so a deleted interface leaves the link in place
to be reported and repaired; nothing here ever removes a link because of the interface side
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model.port_constants import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def port_ids_of_object(ports_manager: PortsManager, object_id: int) -> list[int]:
    """
    Returns the public_ids of one CmdbObject's ports

    The read every cascade starts with, because both the connections and the interface links are found
    through their port ids and neither can be reached once the ports are gone. Only the ids are used,
    so a device with many ports costs one read rather than one per port; a row without a usable id is
    dropped rather than putting a null into the following `$in`

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject

    Returns:
        list[int]: The object's port ids, empty when it has none
    """
    return [
        port[PortKey.PUBLIC_ID.value]
        for port in ports_manager.get_ports_of_object(object_id)
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    ]


def delete_connections_of_port(
        port_connections_manager: PortConnectionsManager,
        port_id: int) -> int:
    """
    Removes every CmdbPortConnection one deleted CmdbPort was an endpoint of

    A port may not leave a connection pointing at nothing, so deleting one takes its cable and - on a
    patch-panel port - its internal pairing with it. Nothing else is touched: the peer ports keep every
    other connection they hold, which is the rule that resolving or deleting one connection must never
    delete another

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        port_id (int): public_id of the CmdbPort being removed

    Returns:
        int: The number of removed connections
    """
    removed: int = port_connections_manager.delete_connections_of_ports([port_id])

    if removed:
        LOGGER.info(
            "[delete_connections_of_port] CmdbPort ID:%s deleted - removed %s connection(s)",
            port_id, removed,
        )

    return removed


def delete_interface_links_of_port(
        port_interface_links_manager: PortInterfaceLinksManager,
        port_id: int) -> int:
    """
    Removes every CmdbPortInterfaceLink a deleted CmdbPort held

    The port reference is the HARD half of a link: without its port a link is a row nothing can reach
    and nothing can repair. The interface half is untouched - no CmdbObject's interface rows are
    changed by a port going away

    Args:
        port_interface_links_manager (PortInterfaceLinksManager): db interface for the links
        port_id (int): public_id of the CmdbPort being removed

    Returns:
        int: The number of removed links
    """
    removed: int = port_interface_links_manager.delete_links_of_ports([port_id])

    if removed:
        LOGGER.info(
            "[delete_interface_links_of_port] CmdbPort ID:%s deleted - removed %s interface link(s)",
            port_id, removed,
        )

    return removed


def delete_interface_links_of_ports(
        port_interface_links_manager: PortInterfaceLinksManager,
        port_ids: list[int]) -> int:
    """
    Removes every CmdbPortInterfaceLink held by a set of doomed CmdbPorts

    Takes the ids for the same reason the connection cascade does, and must run before the ports are
    deleted for the same reason: a link is found through its port_id

    Args:
        port_interface_links_manager (PortInterfaceLinksManager): db interface for the links
        port_ids (list[int]): public_ids of the CmdbPorts being removed

    Returns:
        int: The number of removed links
    """
    if not port_ids:
        return 0

    removed: int = port_interface_links_manager.delete_links_of_ports(port_ids)

    if removed:
        LOGGER.info(
            "[delete_interface_links_of_ports] removed %s interface link(s) of %s doomed port(s)",
            removed, len(port_ids),
        )

    return removed


def delete_connections_of_ports(
        port_connections_manager: PortConnectionsManager,
        port_ids: list[int]) -> int:
    """
    Removes every CmdbPortConnection held by a set of doomed CmdbPorts

    Takes the ids rather than reading them, so the caller resolves them ONCE and both this and the
    interface-link cascade work from the same list - the object-delete hook would otherwise read the
    same ports twice to answer the same question.

    Must run BEFORE the ports are deleted: a connection is found through its endpoints, and a deleted
    port can no longer be looked up

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        port_ids (list[int]): public_ids of the CmdbPorts being removed

    Returns:
        int: The number of removed connections
    """
    if not port_ids:
        return 0

    removed: int = port_connections_manager.delete_connections_of_ports(port_ids)

    if removed:
        LOGGER.info(
            "[delete_connections_of_ports] removed %s connection(s) of %s doomed port(s)",
            removed, len(port_ids),
        )

    return removed


def delete_ports_of_object(ports_manager: PortsManager, deleted_object: dict[str, Any]) -> int:
    """
    Removes every CmdbPort a deleted CmdbObject owned

    One statement, not a per-port loop. An object that never had ports is a no-op costing a single
    indexed delete. Whether the object's type declares `uses_ports` is deliberately NOT consulted: the
    flag can have been turned off after the ports were created, and the rows would then be orphaned by
    exactly the check meant to protect them.

    The ports' CONNECTIONS and INTERFACE LINKS are not this function's job - delete_connections_of_ports
    and delete_interface_links_of_ports remove those, and both have to run FIRST, while the port ids
    still exist to find them by

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        deleted_object (dict[str, Any]): The CmdbObject document that was (or is about to be) deleted

    Returns:
        int: The number of removed ports
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return 0

    removed: int = ports_manager.delete_ports_of_object(object_id)

    if removed:
        LOGGER.info(
            "[delete_ports_of_object] CmdbObject ID:%s deleted - removed %s port(s)", object_id, removed,
        )

    return removed
