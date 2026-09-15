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
The Port consequences of a CmdbObject write, called from the /objects routes

The object routes own the object lifecycle; this module is what they call so a deleted object does not
leave its ports - or their connections - behind. It mirrors rack_object_hooks: the hook resolves the
managers it needs and delegates the actual statements to cmdb.framework.port, so the cascade itself
stays testable without a request.

Two jobs, in the order the routes run them:

* **before** anything is deleted, `guard_cable_objects_delete` refuses the deletion of a CABLE
  SpecialType CmdbObject a CmdbPortConnection still names as its cable. The connection is a fact
  about its two ports and survives its cable record, so it is neither cascaded nor left dangling -
  the user resolves it or re-describes its cable, and the message names both
* **after** the object is gone, `handle_object_deleted` removes the ports it owned, with their
  connections and interface links

Both are used by the single AND the bulk object delete: the guard through
`objects_helper.guard_object[s]_delete`, the cascade by each route's own cleanup. A bulk delete asks
the guard once for the whole selection, so it costs one query however many objects it carries
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model import CmdbUser

from cmdb.framework.port.cable_usage import cable_usage_blocker, collect_cable_usage
from cmdb.framework.port.cascade import (
    delete_connections_of_ports,
    delete_interface_links_of_ports,
    delete_ports_of_object,
    port_ids_of_object,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def handle_object_deleted(
        request_user: CmdbUser,
        deleted_object: dict[str, Any],
        ports_manager: PortsManager | None = None,
        port_connections_manager: PortConnectionsManager | None = None,
        port_interface_links_manager: PortInterfaceLinksManager | None = None) -> None:
    """
    Removes the ports a deleted CmdbObject leaves behind, with their connections and interface links

    **Everything that references the ports goes first.** A connection is found through its endpoints
    and a link through its port_id; a port names neither, so once the ports are deleted there is no way
    left to reach the rows that pointed at them. The peers at the other ends simply become free, and no
    CmdbObject's interface rows are touched - the link's interface half is a soft reference.

    Not gated on the licence or on the type's `uses_ports` flag, deliberately: cleanup must never be
    blocked by a state the user cannot currently reach. A licence that lapsed, or a flag turned off
    after the ports were created, would otherwise orphan exactly the rows this exists to remove. The
    same reasoning the Rack hooks apply to their own cleanup

    Args:
        request_user (CmdbUser): The user performing the deletion
        deleted_object (dict[str, Any]): The CmdbObject document being deleted
        ports_manager (PortsManager | None): Optional pre-resolved CmdbPorts manager
        port_connections_manager (PortConnectionsManager | None): Optional pre-resolved connections manager
        port_interface_links_manager (PortInterfaceLinksManager | None): Optional pre-resolved links manager
    """
    object_id: Any = deleted_object.get(CmdbObjectKey.PUBLIC_ID.value)

    if not isinstance(object_id, int):
        return

    # A bulk delete resolves the three managers once and passes them in, so a 200-object selection
    # does not build 600 managers; the single delete lets the hook resolve them itself
    if ports_manager is None:
        ports_manager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

    if port_connections_manager is None:
        port_connections_manager = ManagerProvider.get_manager(ManagerType.PORT_CONNECTIONS, request_user)

    if port_interface_links_manager is None:
        port_interface_links_manager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user,
        )

    # Resolved ONCE and shared: both cascades answer the same "which ports are doomed" question, and
    # reading it twice would cost a second query on every object deletion for no new information
    doomed_port_ids: list[int] = port_ids_of_object(ports_manager, object_id)

    delete_connections_of_ports(port_connections_manager, doomed_port_ids)
    delete_interface_links_of_ports(port_interface_links_manager, doomed_port_ids)
    delete_ports_of_object(ports_manager, deleted_object)


def cable_object_ids(types_manager: TypesManager, target_objects: list[dict[str, Any]]) -> list[int]:
    """
    Filters a delete selection down to the CmdbObjects of a CABLE SpecialType

    One distinct query for the CABLE type ids, so a selection without a single cable pays one cheap
    read and no connection lookup at all

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        target_objects (list[dict[str, Any]]): The CmdbObject documents being deleted

    Raises:
        TypesManagerGetError: If the CABLE type lookup fails

    Returns:
        list[int]: public_ids of the targets that are Cable CIs
    """
    if not target_objects:
        return []

    cable_type_ids: set[int] = set(types_manager.get_type_ids_of_special_type(SpecialType.CABLE))

    if not cable_type_ids:
        return []

    return [
        target[CmdbObjectKey.PUBLIC_ID.value]
        for target in target_objects
        if target.get(CmdbObjectKey.TYPE_ID.value) in cable_type_ids
        and isinstance(target.get(CmdbObjectKey.PUBLIC_ID.value), int)
    ]


def guard_cable_objects_delete(
        request_user: CmdbUser,
        types_manager: TypesManager,
        target_objects: list[dict[str, Any]]) -> None:
    """
    Refuses a deletion that would strand a CmdbPortConnection's cable

    Evaluated for the WHOLE selection before anything is deleted, so a bulk delete either happens or
    does not - the same rule its IPAM guard follows, and for the same reason: refusing halfway would
    leave the earlier targets already gone

    Args:
        request_user (CmdbUser): The CmdbUser performing the deletion
        types_manager (TypesManager): db interface for CmdbTypes
        target_objects (list[dict[str, Any]]): The CmdbObject documents being deleted

    Raises:
        HTTPException: 400 when a Cable CI in the selection is still used by a connection
    """
    cable_ids: list[int] = cable_object_ids(types_manager, target_objects)

    if not cable_ids:
        return

    port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
        ManagerType.PORT_CONNECTIONS, request_user,
    )

    blocker: str | None = cable_usage_blocker(collect_cable_usage(port_connections_manager, cable_ids))

    if blocker:
        abort(400, blocker)
