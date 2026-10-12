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

And one job of the create route: an object created with ``?clone_ports_from=<id>`` gets a copy of every port
of that object (`plan_object_port_clone` checks before the object is written, `insert_object_with_cloned_ports`
writes the object and its ports all-or-nothing)
"""
from logging import Logger, getLogger
from typing import Any, Mapping

from flask import abort

from cmdb.manager import TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.manager import ObjectsManager
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PortKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model import CmdbUser

from cmdb.framework.port.cable_usage import cable_usage_blocker, collect_cable_usage
from cmdb.framework.port.clone import PortClonePlan, PortCloneResult, clone_ports, internal_pairs_of
from cmdb.framework.port.name_syntax_constants import MAX_BULK_PORT_COUNT
from cmdb.framework.write_ledger import WriteLedger
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.route_utils import request_authenticates_by_api_key, user_has_right
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortCloneError, PortRight
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectQueryParam
from cmdb.errors.security import AccessDeniedError
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

# -------------------------------------------------------------------------------------------------------------------- #
#                                         cloning an object's ports                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def read_port_clone_source(args: Mapping[str, str]) -> int | None:
    """
    The public_id of the object whose ports a new object clones, read off the create request

    Args:
        args (Mapping[str, str]): The request's query parameters

    Raises:
        HTTPException: 400 when the parameter is present but is no positive integer

    Returns:
        int | None: The source object's public_id, or None when the create clones no ports
    """
    param: str = ObjectQueryParam.CLONE_PORTS_FROM.value
    value: str | None = args.get(param)

    if value is None:
        return None

    if not value.isascii() or not value.isdigit() or int(value) < 1:
        abort(400, PortCloneError.SOURCE_INVALID.format(param=param, value=value))

    return int(value)


def plan_object_port_clone(
        request_user: CmdbUser,
        source_object_id: int,
        target_type: CmdbType,
        objects_manager: ObjectsManager) -> PortClonePlan | None:
    """
    Checks that a new object may clone the source object's ports, and reads what the clone will write

    Runs before the new object is written, so every refusal leaves nothing behind. The source must exist and be
    readable by the caller. A source without ports clones nothing and needs nothing more; one with ports needs a
    caller other than the cloud API key, the IPAM licence, the right to add ports, a Type of the new object that
    uses ports, and at most as many ports as a bulk create may write

    Args:
        request_user (CmdbUser): The CmdbUser creating the object
        source_object_id (int): public_id of the object whose ports are cloned
        target_type (CmdbType): The Type of the new object
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Raises:
        HTTPException: 400 when the source has too many ports or the new object's Type does not use ports, 403
            when the caller may not read the source, authenticates by the cloud API key, the IPAM licence is missing
            or the caller lacks the right to add ports, 404 when the source does not exist

    Returns:
        PortClonePlan | None: The source's ports and INTERNAL pairs, or None when it has no port
    """
    try:
        source: dict[str, Any] | None = objects_manager.get_object(
            source_object_id, request_user, AccessControlPermission.READ,
        )
    except AccessDeniedError:
        abort(403, PortCloneError.SOURCE_NOT_READABLE.format(object_id=source_object_id))

    if not source:
        abort(404, PortCloneError.SOURCE_NOT_FOUND.format(object_id=source_object_id))

    ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
    port_count: int = ports_manager.count_documents(
        {PortKey.OBJECT_ID.value: source_object_id}, limit=MAX_BULK_PORT_COUNT + 1,
    )

    if not port_count:
        return None

    # The port routes are closed to the cloud API key, so the ports may not be reached through the object create
    if request_authenticates_by_api_key():
        abort(403, PortCloneError.API_KEY_LOCKED.format(object_id=source_object_id))

    abort_if_feature_locked(LicenseFeature.IPAM, request_user)

    if not user_has_right(PortRight.ADD.value, request_user):
        abort(403, PortCloneError.RIGHT_MISSING.format(object_id=source_object_id, right=PortRight.ADD.value))

    if port_count > MAX_BULK_PORT_COUNT:
        abort(400, PortCloneError.TOO_MANY.format(object_id=source_object_id, limit=MAX_BULK_PORT_COUNT))

    if target_type.uses_ports is not True:
        abort(400, PortCloneError.TYPE_WITHOUT_PORTS.format(object_id=source_object_id))

    port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
        ManagerType.PORT_CONNECTIONS, request_user,
    )

    ports: list[dict[str, Any]] = ports_manager.get_ports_of_object(source_object_id)
    port_ids: list[int] = [port[PortKey.PUBLIC_ID.value] for port in ports]

    return PortClonePlan(
        ports=ports,
        internal_pairs=internal_pairs_of(set(port_ids), port_connections_manager.get_connections_of_ports(port_ids)),
    )


def insert_object_with_cloned_ports(
        objects_manager: ObjectsManager,
        new_object_data: dict[str, Any],
        request_user: CmdbUser,
        plan: PortClonePlan | None) -> int:
    """
    Writes a new object and, when it clones ports, the cloned ports - all or nothing

    The object, its ports and their INTERNAL connections are recorded as they are written; when a write fails,
    the ones before it are undone and the error is raised unchanged

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        new_object_data (dict[str, Any]): The normalised new object
        request_user (CmdbUser): The CmdbUser creating the object
        plan (PortClonePlan | None): What `plan_object_port_clone` read, or None when no port is cloned

    Raises:
        HTTPException: 500 naming what is left when a failed clone could not be fully undone

    Returns:
        int: public_id of the new object
    """
    if plan is None:
        return objects_manager.insert_object(new_object_data, request_user, AccessControlPermission.CREATE)

    with undone_on_failure(PortCloneError.RESIDUE.value) as ledger:
        new_object_id: int = objects_manager.insert_object(
            new_object_data, request_user, AccessControlPermission.CREATE,
        )
        ledger.inserted(objects_manager, new_object_id)
        clone_object_ports(request_user, plan, new_object_id, ledger)

    return new_object_id


def clone_object_ports(
        request_user: CmdbUser,
        plan: PortClonePlan,
        target_object_id: int,
        ledger: WriteLedger) -> PortCloneResult:
    """
    Writes the cloned ports of a new object with the managers of the caller's database

    Args:
        request_user (CmdbUser): The CmdbUser creating the object; the new ports' author
        plan (PortClonePlan): What `plan_object_port_clone` read
        target_object_id (int): public_id of the new object
        ledger (WriteLedger): The request's record of its writes

    Returns:
        PortCloneResult: The new ports' and connections' public_ids
    """
    return clone_ports(
        ManagerProvider.get_manager(ManagerType.PORTS, request_user),
        ManagerProvider.get_manager(ManagerType.PORT_CONNECTIONS, request_user),
        plan,
        target_object_id,
        request_user.public_id,
        ledger,
    )
