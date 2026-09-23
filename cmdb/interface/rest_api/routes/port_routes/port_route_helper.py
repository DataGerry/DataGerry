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
The write guards and lookups shared by the Port REST routes

Every one of them lives here rather than inline in the routes, for one reason: the owner-object ACL
check has to run on EVERY route, and a guard that is inlined five times is a guard that will be
forgotten on the sixth. A port is stored outside its owner's document, so nothing about it inherits
the object's access control - reading or writing a port has to ask about the object explicitly
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ExtendableOptionsManager, ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.extendable_option_model import ExtendableOptionKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PORT_SELECT_FIELD_OPTION_TYPES, PortKey, PortSide
from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.framework.port.connected import project_connected

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import (
    PORT_CONNECTED_KEY,
    PORT_FIELD_IMMUTABLE_MESSAGE,
    PORT_NAME_REQUIRED_MESSAGE,
    PORT_KIND_CONFLICT_MESSAGE,
    PORT_KIND_LABELS,
    PORT_NAME_TAKEN_MESSAGE,
    PORT_NOT_FOUND_MESSAGE,
    PORT_OPTION_INVALID_MESSAGE,
    PORT_OWNER_NOT_FOUND_MESSAGE,
    PORT_TYPE_NOT_PORT_BEARING_MESSAGE,
    PortRequestKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_port_or_abort(ports_manager: PortsManager, public_id: int) -> dict[str, Any]:
    """
    Reads a CmdbPort or aborts 404

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        public_id (int): public_id of the CmdbPort

    Raises:
        HTTPException: 404 when no port with that public_id exists

    Returns:
        dict[str, Any]: The stored port document
    """
    port: dict[str, Any] | None = ports_manager.get_item(public_id, as_dict=True)

    if not port:
        abort(404, PORT_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return port


def get_accessible_owner_or_abort(
    objects_manager: ObjectsManager,
    object_id: Any,
    request_user: CmdbUser,
    permission: AccessControlPermission,
) -> dict[str, Any]:
    """
    Reads the owner CmdbObject with its ACL applied, or aborts

    This is the check nothing else performs for a port. `objects_manager.get_object` runs
    `verify_access` against the object's CmdbType, so an object the caller may not see raises
    AccessDeniedError (mapped to 403 by the routes) instead of quietly handing its ports over.

    READ is the permission for reading ports, UPDATE for creating, editing and deleting one: a port
    write does not change the object document, but it does change what that object IS, so it is the
    object's update permission that governs it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        object_id (Any): public_id of the owner CmdbObject, as it came off the request or the port
        request_user (CmdbUser): The user performing the request
        permission (AccessControlPermission): The permission required on the owner object

    Raises:
        AccessDeniedError: When the user's ACL does not grant the permission on the owner's type
        HTTPException: 400 when the object_id is not an integer, 404 when the object does not exist

    Returns:
        dict[str, Any]: The owner CmdbObject document
    """
    if not isinstance(object_id, int):
        abort(400, PORT_OWNER_NOT_FOUND_MESSAGE.format(object_id=object_id))

    owner: dict[str, Any] | None = objects_manager.get_object(object_id, request_user, permission)

    if not owner:
        abort(404, PORT_OWNER_NOT_FOUND_MESSAGE.format(object_id=object_id))

    return owner


def enforce_type_uses_ports(types_manager: TypesManager, owner_object: dict[str, Any]) -> None:
    """
    Aborts 400 unless the owner's CmdbType declares that its objects have ports

    Read from the stored CmdbType rather than from the object, because `uses_ports` is a type-level
    declaration and an object document carries no copy of it. This is what step 1's flag is for: a
    port on a type that does not use ports would be invisible in the UI, which renders the ports panel
    only for a port-bearing type

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        owner_object (dict[str, Any]): The owner CmdbObject document

    Raises:
        HTTPException: 400 when the type does not declare uses_ports
    """
    type_id: Any = owner_object.get(CmdbObjectKey.TYPE_ID)
    type_doc: dict[str, Any] | None = types_manager.get_type(type_id) if isinstance(type_id, int) else None

    if not type_doc or type_doc.get(TypeSchemaKey.USES_PORTS.value) is not True:
        abort(400, PORT_TYPE_NOT_PORT_BEARING_MESSAGE.format(
            object_id=owner_object.get(CmdbObjectKey.PUBLIC_ID),
        ))


def port_kind_of_side(side: str | None) -> str:
    """
    Reports which kind of device a single port side belongs to

    The two kinds are the creation assistant's first question, and a port's side is the only thing
    that answers it - nothing stores "is a panel"

    Args:
        side (str | None): A PortSide value, or None for a port that carries none

    Returns:
        str: A PortDeviceKind value - PATCH_PANEL for FRONT/REAR, STANDARD for anything else
    """
    return (PortDeviceKind.PATCH_PANEL if PortSide.is_panel_side(side) else PortDeviceKind.STANDARD).value


def current_port_kind(ports: list[dict[str, Any]]) -> str | None:
    """
    Reports which kind an object currently is, from the ports it holds

    Args:
        ports (list[dict[str, Any]]): The object's stored ports

    Returns:
        str | None: The PortDeviceKind value, or None when the object holds no ports and is therefore
            still free to become either
    """
    for port in ports:
        return port_kind_of_side(port.get(PortKey.SIDE.value))

    return None


def port_kind_blocker(existing_ports: list[dict[str, Any]], requested_side: str | None) -> str | None:
    """
    Reports why a port of the requested side may not join this object, if it may not

    **An object is either an ordinary device or a patch panel, never both.** A device's ports are
    PortSide.SINGLE; a panel's are FRONT and REAR, paired by an INTERNAL connection. Mixing the two
    on one object describes a thing that does not exist, and every consumer that asks "is this a
    panel?" reads the side of whichever port it happens to look at first.

    The kind is not switched by editing either: while an object holds ports of one kind, a port of
    the other is refused whatever the route, so the only way out of a kind is to delete every port
    of it. That includes an object holding a single port - flipping its side would change what the
    object is without anything being deleted, which is the one workflow this rule exists to remove.

    The reason is returned rather than raised so every write path can use it - the routes abort with
    it, and a preview refuses on it before it offers names that could not be created

    Args:
        existing_ports (list[dict[str, Any]]): The object's ports as stored, excluding the one being
            updated when the caller is an update
        requested_side (str | None): The PortSide the write asks for

    Returns:
        str | None: The reason the write is refused, or None when the kinds agree
    """
    current: str | None = current_port_kind(existing_ports)
    requested: str = port_kind_of_side(requested_side)

    if current is None or current == requested:
        return None

    return PORT_KIND_CONFLICT_MESSAGE.format(
        object_id=existing_ports[0].get(PortKey.OBJECT_ID.value),
        current=PORT_KIND_LABELS[current],
        requested=PORT_KIND_LABELS[requested],
    )


def enforce_port_kind(
    ports_manager: PortsManager,
    object_id: int,
    requested_side: str | None,
    exclude_id: int | None = None,
) -> None:
    """
    Aborts 400 when a write would give an object ports of the kind it is not

    The route-level wrapper around `port_kind_blocker`, reading the object's current ports itself.
    `exclude_id` is the port being updated: it is left out of the comparison so a port is never
    measured against itself

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the owner CmdbObject
        requested_side (str | None): The PortSide the write asks for
        exclude_id (int | None): public_id of the port being updated. Defaults to None

    Raises:
        HTTPException: 400 when the object already holds ports of the other kind
    """
    existing: list[dict[str, Any]] = [
        port for port in ports_manager.get_ports_of_object(object_id)
        if port.get(PortKey.PUBLIC_ID.value) != exclude_id
    ]

    blocker: str | None = port_kind_blocker(existing, requested_side)

    if blocker:
        abort(400, blocker)


def enforce_bulk_port_kind(ports_manager: PortsManager, object_id: int, device_kind: str) -> None:
    """
    Aborts 400 when a bulk creation would give an object ports of the kind it is not

    The same rule as `enforce_port_kind`, asked with the assistant's vocabulary instead of a port
    side: a bulk request names a `PortDeviceKind` directly, and a PATCH_PANEL batch creates both
    faces at once, so there is no single side to compare

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the owner CmdbObject
        device_kind (str): The PortDeviceKind the request asks for

    Raises:
        HTTPException: 400 when the object already holds ports of the other kind
    """
    existing: list[dict[str, Any]] = ports_manager.get_ports_of_object(object_id)
    current: str | None = current_port_kind(existing)

    if current is None or current == device_kind:
        return

    abort(400, PORT_KIND_CONFLICT_MESSAGE.format(
        object_id=object_id,
        current=PORT_KIND_LABELS[current],
        requested=PORT_KIND_LABELS[device_kind],
    ))


def enforce_port_name_available(
    ports_manager: PortsManager,
    object_id: int,
    side: str,
    name: str,
    exclude_id: int | None = None,
) -> None:
    """
    Aborts 400 when the port name is already taken on this face of this object

    A readable rejection for the ordinary case. It is not the guarantee: being a read followed by a
    write it cannot stop two concurrent requests, which is what the unique (object_id, side, name)
    index is for - the routes translate its duplicate-key error into the same 400

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the owner CmdbObject
        side (str): A PortSide value
        name (str): The requested port name
        exclude_id (int | None): public_id of the port being updated, so it does not clash with
            itself. Defaults to None

    Raises:
        HTTPException: 400 when another port of this object and side already carries the name
    """
    existing: dict[str, Any] | None = ports_manager.get_port_by_name(object_id, side, name)

    if not existing or existing.get(PortKey.PUBLIC_ID.value) == exclude_id:
        return

    abort(400, PORT_NAME_TAKEN_MESSAGE.format(name=name, side=side, object_id=object_id))


def enforce_select_values(extendable_options_manager: ExtendableOptionsManager, payload: dict[str, Any]) -> None:
    """
    Aborts 400 when a select field does not name an option of its own list

    The three select fields store the public_id of a CmdbExtendableOption, and which list each draws
    from is declared once by the port model (PORT_SELECT_FIELD_OPTION_TYPES). Without this check a
    PORT_TYPE id could be stored in the speed field and would then be rendered as a speed - a
    cross-collection rule neither the document schema nor an index can express

    Args:
        extendable_options_manager (ExtendableOptionsManager): db interface for CmdbExtendableOptions
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when a select value is not an option, or is an option of another list
    """
    for field, option_type in PORT_SELECT_FIELD_OPTION_TYPES.items():
        value: Any = payload.get(field.value)

        if value is None:
            continue

        option: dict[str, Any] | None = None

        if isinstance(value, int):
            option = extendable_options_manager.get_one_by({
                ExtendableOptionKey.PUBLIC_ID: value,
                ExtendableOptionKey.OPTION_TYPE: option_type.value,
            })

        if not option:
            abort(400, PORT_OPTION_INVALID_MESSAGE.format(
                field=field.value, option_type=option_type.value, value=value,
            ))


def get_requested_name_or_abort(payload: dict[str, Any]) -> str:
    """
    Reads the port name from a request body, aborting 400 when it is missing or blank

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the name is absent, not a string, or empty after stripping

    Returns:
        str: The requested name
    """
    name: Any = payload.get(PortRequestKey.NAME.value)

    if not isinstance(name, str) or not name.strip():
        abort(400, PORT_NAME_REQUIRED_MESSAGE)

    return name


def get_requested_side_or_abort(payload: dict[str, Any]) -> str:
    """
    Reads the side from a create body, aborting 400 on an unknown value

    An absent side reads as SINGLE, which is what every request that is not the patch-panel assistant
    sends - the virtual section template does not expose the field at all

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the side is not a PortSide value

    Returns:
        str: The requested side
    """
    side: Any = payload.get(PortRequestKey.SIDE.value) or PortSide.SINGLE.value

    if side not in {member.value for member in PortSide}:
        abort(400, PORT_OPTION_INVALID_MESSAGE.format(
            field=PortRequestKey.SIDE.value, option_type='PortSide', value=side,
        ))

    return side


def refuse_owner_change(stored_port: dict[str, Any], payload: dict[str, Any]) -> None:
    """
    Aborts 400 when an update payload would move the port to another object or another face

    Both are immutable. Moving the owner would need the target object's ACL and its type flag checked
    as well - a different operation from editing a port. Moving the side would move the port into
    another face's name space, where its name may already be taken, so the unique index would refuse
    the write with a duplicate-key error rather than this readable message.

    A payload repeating the stored value is fine: the routes take the whole object, so a client that
    round-trips a GET must not be punished for sending the fields back

    Args:
        stored_port (dict[str, Any]): The port as currently stored
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when object_id or side differ from the stored values
    """
    for key in (PortRequestKey.OBJECT_ID, PortRequestKey.SIDE):
        requested: Any = payload.get(key.value)

        if requested is not None and requested != stored_port.get(key.value):
            abort(400, PORT_FIELD_IMMUTABLE_MESSAGE.format(field=key.value))


def build_port_candidate(object_id: int, side: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the port document a create or update writes, from the request body

    Only the keys a request owns are read: the identity, the owner, the side and the audit fields are
    filled in by the caller from the URL, the stored port or the request user, never from the payload

    Args:
        object_id (int): public_id of the owner CmdbObject
        side (str): The port's side
        name (str): The port's name
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The port document without its identity and audit fields
    """
    return {
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: name,
        PortKey.PORT_NUMBER.value: payload.get(PortRequestKey.PORT_NUMBER.value),
        PortKey.STATUS.value: payload.get(PortRequestKey.STATUS.value),
        PortKey.PORT_TYPE.value: payload.get(PortRequestKey.PORT_TYPE.value),
        PortKey.SPEED.value: payload.get(PortRequestKey.SPEED.value),
        PortKey.DESCRIPTION.value: payload.get(PortRequestKey.DESCRIPTION.value),
    }


def collect_port_ids(ports: list[dict[str, Any]]) -> list[int]:
    """
    Reads the public_ids out of a list of port documents

    Shared by the connected-flag projection and the object-level connection read, which ask the same
    question of the same list. A port without a usable public_id is skipped rather than passed into a
    '$in': it could never match a connection endpoint anyway

    Args:
        ports (list[dict[str, Any]]): Port documents

    Returns:
        list[int]: Their public_ids, in the order the ports were given
    """
    return [
        port[PortKey.PUBLIC_ID.value] for port in ports
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    ]


def with_connected_flag(
        port_connections_manager: PortConnectionsManager,
        ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Adds the derived connected flag to the ports of a read response

    **One batched read for the whole response**, not one per port: a switch with 48 ports would
    otherwise cost 48 queries to answer a question a single indexed `$in` answers. The query is served
    by the plain multikey index on `endpoints`, which exists for exactly this.

    An empty page costs no query at all - an object with no ports is the common case on every object
    view that does not use them

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        ports (list[dict[str, Any]]): The port documents about to be returned

    Returns:
        list[dict[str, Any]]: The same port documents, each carrying the flag
    """
    connections: list[dict[str, Any]] = port_connections_manager.get_connections_of_ports(
        collect_port_ids(ports),
    )

    return project_connected(ports, connections, PORT_CONNECTED_KEY)
