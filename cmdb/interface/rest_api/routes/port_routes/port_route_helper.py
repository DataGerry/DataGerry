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
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.extendable_option_model import ExtendableOptionKey
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PORT_SELECT_FIELD_OPTION_TYPES, PortKey, PortSide
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import (
    PORT_FIELD_IMMUTABLE_MESSAGE,
    PORT_NAME_REQUIRED_MESSAGE,
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
