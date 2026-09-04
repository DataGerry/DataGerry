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
The write guards and lookups the port <-> interface link routes share

The split mirrors the connection routes: cmdb.framework.port.interface_links holds the pure resolution
and the dangling detection, and this module turns them into HTTP refusals.

The rule worth stating once: **creating an already-dangling link is refused, an existing link going
dangling is not.** The first is a mistake visible at the moment it is made; the second happens because
an MDS row id is not durable, and deleting the link automatically would destroy the only record of what
the customer meant
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_interface_link_model import InterfaceRelationType, PortInterfaceLinkKey
from cmdb.models.special_type_model.ipam_constants import IpamSection
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.utils import coerce_whole_number

from cmdb.framework.port.interface_links import find_interface_row, resolve_link_row

from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import (
    INTERFACE_ROW_KEY,
    LINK_ALREADY_EXISTS_MESSAGE,
    LINK_FIELD_IMMUTABLE_MESSAGE,
    LINK_INTERFACE_OBJECT_NOT_FOUND_MESSAGE,
    LINK_INTERFACE_ROW_NOT_FOUND_MESSAGE,
    LINK_MISSING_MULTI_DATA_ID_MESSAGE,
    LINK_NOT_FOUND_MESSAGE,
    LINK_PORT_NOT_FOUND_MESSAGE,
    LINK_RELATION_TYPE_INVALID_MESSAGE,
    InterfaceLinkRequestKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import get_accessible_owner_or_abort
from cmdb.models.port_model import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The identity keys an update may not change, in the order they are reported
IMMUTABLE_REQUEST_KEYS: tuple[InterfaceLinkRequestKey, ...] = (
    InterfaceLinkRequestKey.INTERFACE_OBJECT_ID,
    InterfaceLinkRequestKey.INTERFACE_SECTION_ID,
    InterfaceLinkRequestKey.INTERFACE_MULTI_DATA_ID,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      lookups                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def get_link_or_abort(
        port_interface_links_manager: PortInterfaceLinksManager,
        public_id: int) -> dict[str, Any]:
    """
    Reads a CmdbPortInterfaceLink or aborts 404

    Args:
        port_interface_links_manager (PortInterfaceLinksManager): db interface for the links
        public_id (int): public_id of the CmdbPortInterfaceLink

    Raises:
        HTTPException: 404 when no link with that public_id exists

    Returns:
        dict[str, Any]: The stored link document
    """
    link: dict[str, Any] | None = port_interface_links_manager.get_item(public_id, as_dict=True)

    if not link:
        abort(404, LINK_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return link


def get_accessible_port_or_abort(
        ports_manager: PortsManager,
        objects_manager: ObjectsManager,
        port_id: int,
        request_user: CmdbUser,
        permission: AccessControlPermission) -> dict[str, Any]:
    """
    Reads a CmdbPort with its OWNER object's ACL applied, or aborts

    The same check every /ports route performs, for the same reason: a link is an attribute of a port,
    so reading or writing one is reading or writing part of the port's owner object.

    The INTERFACE object's ACL is deliberately NOT checked, following the connection routes' Q13
    decision for a row that spans two objects. That is recorded rather than hidden: a caller who may
    edit a port can link it to an interface on an object they cannot open, and a link read tells them
    that interface row exists

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        objects_manager (ObjectsManager): db interface for CmdbObjects
        port_id (int): public_id of the CmdbPort
        request_user (CmdbUser): The user performing the request
        permission (AccessControlPermission): The permission required on the port's owner object

    Raises:
        AccessDeniedError: When the user's ACL does not grant the permission on the owner's type
        HTTPException: 404 when the port or its owner does not exist

    Returns:
        dict[str, Any]: The stored port document
    """
    port: dict[str, Any] | None = ports_manager.get_item(port_id, as_dict=True)

    if not port:
        abort(404, LINK_PORT_NOT_FOUND_MESSAGE.format(port_id=port_id))

    get_accessible_owner_or_abort(
        objects_manager, port.get(PortKey.OBJECT_ID.value), request_user, permission,
    )

    return port

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    write guards                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def get_requested_relation_type_or_abort(payload: dict[str, Any]) -> str:
    """
    Reads the relation type from a request body, aborting 400 on a missing or unknown value

    The list is fixed and non-customizable by decision, so an unknown value is a typo rather than a
    list the customer still has to extend - which is why the message names the five allowed tokens

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the relation type is absent or not an InterfaceRelationType value

    Returns:
        str: The requested InterfaceRelationType value
    """
    raw: Any = payload.get(InterfaceLinkRequestKey.RELATION_TYPE.value)

    if not isinstance(raw, str) or not InterfaceRelationType.is_valid(raw):
        abort(400, LINK_RELATION_TYPE_INVALID_MESSAGE.format(
            relation_type=raw,
            allowed=', '.join(member.value for member in InterfaceRelationType),
        ))

    return raw


def get_requested_multi_data_id_or_abort(payload: dict[str, Any]) -> int:
    """
    Reads the MDS row id from a request body, aborting 400 when there is none

    The concept refuses linking an interface row that carries no multi_data_id outright: the id IS the
    reference, so a link without one would point at nothing from the moment it was created

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the row id is absent or not a whole number

    Returns:
        int: The requested multi_data_id
    """
    multi_data_id: int | None = coerce_whole_number(
        payload.get(InterfaceLinkRequestKey.INTERFACE_MULTI_DATA_ID.value),
    )

    if multi_data_id is None:
        abort(400, LINK_MISSING_MULTI_DATA_ID_MESSAGE)

    return multi_data_id


def get_interface_row_or_abort(
        objects_manager: ObjectsManager,
        object_id: Any,
        section_id: str,
        multi_data_id: int) -> dict[str, Any]:
    """
    Resolves the interface row a create names, aborting when it is not there

    Creating an already-dangling link is refused here. A link going dangling LATER is tolerated and
    reported instead - the difference is that this one is a mistake the write path can see

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        object_id (Any): public_id of the CmdbObject that should hold the row
        section_id (str): Name of the MDS section the row should live in
        multi_data_id (int): The row's multi_data_id

    Raises:
        HTTPException: 404 when the object does not exist, 400 when it holds no such row

    Returns:
        dict[str, Any]: The interface MDS row
    """
    if not isinstance(object_id, int):
        abort(404, LINK_INTERFACE_OBJECT_NOT_FOUND_MESSAGE.format(object_id=object_id))

    interface_object: dict[str, Any] | None = objects_manager.get_object(object_id)

    if not interface_object:
        abort(404, LINK_INTERFACE_OBJECT_NOT_FOUND_MESSAGE.format(object_id=object_id))

    row: dict[str, Any] | None = find_interface_row(interface_object, section_id, multi_data_id)

    if not row:
        abort(400, LINK_INTERFACE_ROW_NOT_FOUND_MESSAGE.format(
            object_id=object_id, section_id=section_id, multi_data_id=multi_data_id,
        ))

    return row


def enforce_link_is_new(
        port_interface_links_manager: PortInterfaceLinksManager,
        candidate: dict[str, Any]) -> None:
    """
    Aborts 400 when this port is already linked to this interface row

    A readable rejection for the ordinary case. It is not the guarantee - being a read followed by a
    write it cannot stop two concurrent requests, which is what the unique index on the identity tuple
    is for

    Args:
        port_interface_links_manager (PortInterfaceLinksManager): db interface for the links
        candidate (dict[str, Any]): The link document about to be written

    Raises:
        HTTPException: 400 when an identical link already exists
    """
    existing: dict[str, Any] | None = port_interface_links_manager.get_one_by({
        key.value: candidate[key.value] for key in (
            PortInterfaceLinkKey.PORT_ID,
            PortInterfaceLinkKey.INTERFACE_OBJECT_ID,
            PortInterfaceLinkKey.INTERFACE_SECTION_ID,
            PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID,
        )
    })

    if existing:
        abort(400, LINK_ALREADY_EXISTS_MESSAGE.format(
            port_id=candidate[PortInterfaceLinkKey.PORT_ID.value],
        ))


def refuse_identity_change(stored_link: dict[str, Any], payload: dict[str, Any]) -> None:
    """
    Aborts 400 when an update payload would change which interface row the link names

    The three interface keys are the link's identity, so changing one is creating a different link
    rather than editing this one. Only the relation type describes the pair, and it is what an update
    writes. A payload repeating the stored values is fine, since a client that round-trips a GET must
    not be punished for sending them back

    Args:
        stored_link (dict[str, Any]): The link as currently stored
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when an identity key differs from the stored value
    """
    for key in IMMUTABLE_REQUEST_KEYS:
        requested: Any = payload.get(key.value)

        if requested is not None and requested != stored_link.get(key.value):
            abort(400, LINK_FIELD_IMMUTABLE_MESSAGE.format(field=key.value))

# -------------------------------------------------------------------------------------------------------------------- #
#                                                building and resolving                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def build_link_candidate(port_id: int, payload: dict[str, Any], multi_data_id: int,
                         relation_type: str) -> dict[str, Any]:
    """
    Builds the link document a create writes

    The section id defaults to the IPAM interface template, which is the only interface-bearing section
    today. It is STORED rather than assumed, so the triple stays self-describing and a second such
    section later would not invalidate every existing row

    Args:
        port_id (int): public_id of the CmdbPort, taken from the URL
        payload (dict[str, Any]): The request body
        multi_data_id (int): The already-validated MDS row id
        relation_type (str): The already-validated InterfaceRelationType value

    Returns:
        dict[str, Any]: The link document without its identity and audit fields
    """
    return {
        PortInterfaceLinkKey.PORT_ID.value: port_id,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: payload.get(
            InterfaceLinkRequestKey.INTERFACE_OBJECT_ID.value,
        ),
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: payload.get(
            InterfaceLinkRequestKey.INTERFACE_SECTION_ID.value,
        ) or IpamSection.INTERFACE.value,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: multi_data_id,
        PortInterfaceLinkKey.RELATION_TYPE.value: relation_type,
    }


def with_interface_rows(
        objects_manager: ObjectsManager,
        links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Adds each link's live interface row to a read response, where it still resolves

    **The objects are read once each, not once per link**: whether a row exists is a question about one
    CmdbObject, and a port with a bond and four VLAN sub-interfaces on the same peer would otherwise
    cost five identical reads.

    A dangling link comes back WITHOUT the row key rather than as an error or an omission from the
    list. The customer has to see that the link exists and that what it named is gone - that is the
    whole point of tolerating it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        links (list[dict[str, Any]]): The link documents about to be returned

    Returns:
        list[dict[str, Any]]: The same link documents, each carrying its interface row when resolvable
    """
    object_ids: set[Any] = {
        link.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value) for link in links
    }
    interface_objects: dict[Any, Any] = {
        object_id: objects_manager.get_object(object_id)
        for object_id in object_ids if isinstance(object_id, int)
    }

    for link in links:
        row: dict[str, Any] | None = resolve_link_row(
            link, interface_objects.get(link.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value)),
        )

        if row is not None:
            link[INTERFACE_ROW_KEY] = row

    return links


def read_interface_objects(
        objects_manager: ObjectsManager,
        links: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    Reads every CmdbObject the given links point at, once each

    Backs the dangling-link report, which judges each link against the object holding its row. Objects
    that no longer exist are simply absent from the mapping, which the report reads as 'gone'

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        links (list[dict[str, Any]]): The link documents to resolve the objects of

    Returns:
        dict[int, dict[str, Any]]: The CmdbObjects keyed by public_id, missing ones omitted
    """
    object_ids: set[int] = {
        link[PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value] for link in links
        if isinstance(link.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value), int)
    }

    resolved: dict[int, dict[str, Any]] = {}

    for object_id in object_ids:
        interface_object: dict[str, Any] | None = objects_manager.get_object(object_id)

        if interface_object:
            resolved[object_id] = interface_object

    return resolved
