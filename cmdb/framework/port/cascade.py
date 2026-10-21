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
What happens to CmdbPorts' connections and interface links when the ports are deleted - one port, a selection of
ports, or every port of a deleted CmdbObject

A port belongs to exactly one CmdbObject and is stored outside that object's document, and a connection is stored
outside both of the ports it joins - so nothing removes either when a port goes. Without this cascade a deleted port
would leave connections behind whose endpoint no longer resolves, and interface links nothing can reach.

**The order is the whole trick.** A connection names its endpoints and a port does not name its connections, so the
port ids have to be known before the ports are deleted: once they are gone there is no way left to find the
connections that pointed at them. `delete_ports_with_dependents` therefore removes the connections, then the
interface links, and only then the ports.

**It is all or nothing.** Each of the three deletes is recorded in the caller's WriteLedger with the documents it
removes, before it runs, so a failure part-way restores what was already deleted - the connections are never gone
while their ports are still there.

The peer at the other end of a removed connection is simply free again. Nothing about it is rewritten, because
`connected` is computed from this collection on read and never stored.

**The interface links go the same way, and the asymmetry is deliberate.** A link's reference to its PORT is hard -
a link without its port is a row nothing can reach - so a deleted port takes its links with it. Its reference to the
interface ROW is soft, so a deleted interface leaves the link in place to be reported and repaired; nothing here ever
removes a link because of the interface side
"""
from dataclasses import dataclass
from logging import Logger, getLogger

from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_model.port_constants import PortKey
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.port.cascade_constants import CascadeLedgerDescription
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class PortStoreManagers:
    """
    The managers of the three collections a port delete touches
    """
    ports: PortsManager
    connections: PortConnectionsManager
    interface_links: PortInterfaceLinksManager


@dataclass(frozen=True)
class PortCascadeResult:
    """
    How many documents a port delete removed from each collection
    """
    connections: int
    interface_links: int
    ports: int

# -------------------------------------------------------------------------------------------------------------------- #

def port_ids_of_object(ports_manager: PortsManager, object_id: int) -> list[int]:
    """
    Returns the public_ids of one CmdbObject's ports

    The read an object's cascade starts with, because both the connections and the interface links are found
    through their port ids and neither can be reached once the ports are gone. Only the ids are read
    (`get_port_kinds_of_object`), and a row without a usable id is dropped rather than putting a null into the
    following `$in`

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject

    Raises:
        PortsManagerGetError: If the ports could not be read

    Returns:
        list[int]: The object's port ids, empty when it has none
    """
    return [
        port[PortKey.PUBLIC_ID.value]
        for port in ports_manager.get_port_kinds_of_object(object_id)
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    ]


def delete_ports_with_dependents(
        managers: PortStoreManagers,
        port_ids: list[int],
        ledger: WriteLedger) -> PortCascadeResult:
    """
    Deletes CmdbPorts with every connection and interface link they hold, recording each delete in the ledger

    Connections first, then interface links, then the ports - each found through the port ids, which is why the
    ports go last. Every delete is recorded with the documents it removes before it runs, so the caller's
    `undone_on_failure` restores all of them when a later step fails. Nothing else is touched: the peer ports keep
    every other connection they hold, and no CmdbObject's interface rows change

    Args:
        managers (PortStoreManagers): The managers of ports, connections and interface links
        port_ids (list[int]): public_ids of the CmdbPorts to delete; an empty list deletes nothing
        ledger (WriteLedger): The ledger of the caller's block

    Raises:
        PortConnectionsManagerGetError | PortConnectionsManagerDeleteError: If the connections could not be read
            or deleted
        PortInterfaceLinksManagerGetError | PortInterfaceLinksManagerDeleteError: If the interface links could not
            be read or deleted
        PortsManagerGetError | PortsManagerDeleteError: If the ports could not be read or deleted

    Returns:
        PortCascadeResult: How many connections, interface links and ports were deleted
    """
    if not port_ids:
        return PortCascadeResult(connections=0, interface_links=0, ports=0)

    described_ports: str = str(sorted(port_ids))

    ledger.deleted_many(
        managers.connections, managers.connections.snapshot_connections_of_ports(port_ids),
        CascadeLedgerDescription.CONNECTIONS.value.format(port_ids=described_ports),
    )
    connections: int = managers.connections.delete_connections_of_ports(port_ids)

    ledger.deleted_many(
        managers.interface_links, managers.interface_links.snapshot_links_of_ports(port_ids),
        CascadeLedgerDescription.INTERFACE_LINKS.value.format(port_ids=described_ports),
    )
    interface_links: int = managers.interface_links.delete_links_of_ports(port_ids)

    ledger.deleted_many(
        managers.ports, managers.ports.snapshot_ports(port_ids),
        CascadeLedgerDescription.PORTS.value.format(port_ids=described_ports),
    )
    ports: int = managers.ports.delete_ports_by_ids(port_ids)

    LOGGER.info(
        "[delete_ports_with_dependents] deleted %s port(s), %s connection(s), %s interface link(s)",
        ports, connections, interface_links,
    )

    return PortCascadeResult(connections=connections, interface_links=interface_links, ports=ports)
