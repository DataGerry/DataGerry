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
Implementation of all API routes for handling CmdbPortInterfaceLinks

These routes are the only way a port <-> interface link is written. Four invariants hold across them:

1. **They are guarded by the PORT rights, and by the port owner's ACL.** A link is an attribute of a
   port rather than an entity managed on its own, and the design added no fifth right family for it.
   The INTERFACE object's own ACL is deliberately not checked, following the connection routes' Q13
   decision for a row that spans two objects - recorded on `get_accessible_port_or_abort` rather than
   hidden.
2. **The interface triple is immutable; only the relation type is editable.** The triple is the link's
   identity, so changing one of its keys is creating a different link.
3. **Creating an already-dangling link is refused; an existing link going dangling is not.** The first
   is a mistake the write path can see. The second happens because an MDS row id is not durable - the
   full object PUT does not preserve row ids and the CSV import overwrite renumbers them - so the link
   is kept and REPORTED instead, because deleting it would destroy the only record of what the customer
   meant.
4. **A read returns the live interface row beside its link where it still resolves.** A dangling link
   comes back without that key rather than as an error, so the frontend can show what is broken.

The blueprint mounts under `/ports` beside the port CRUD, the way the two rack blueprints share
`/racks`, and is IPAM-gated with the rest of the feature (see init_rest_api)
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.port_interface_link_model import PortInterfaceLinkKey
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.port_interface_links_manager import (
    PortInterfaceLinksManagerDeleteError,
    PortInterfaceLinksManagerGetError,
    PortInterfaceLinksManagerInsertError,
    PortInterfaceLinksManagerUpdateError,
)

from cmdb.framework.port.interface_links import collect_dangling_links

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    DefaultResponse,
    DeleteSingleResponse,
    GetSingleResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRight
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import (
    LINK_ALREADY_EXISTS_MESSAGE,
)
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_helper import (
    build_link_candidate,
    enforce_link_is_new,
    get_accessible_port_or_abort,
    get_interface_row_or_abort,
    get_link_or_abort,
    get_requested_multi_data_id_or_abort,
    get_requested_relation_type_or_abort,
    read_interface_objects,
    refuse_identity_change,
    with_interface_rows,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_interface_link_blueprint = APIBlueprint('port_interface_links', __name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - CREATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_interface_link_blueprint.route('/<int:port_id>/interface_links/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.EDIT.value)
def insert_port_interface_link(port_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to link a CmdbPort to one IPAM interface row

    The port comes from the URL, so a body can not disagree with it. The addressed interface row has to
    exist: a link that is dangling from the moment it is created is a mistake, unlike one that goes
    dangling later

    Args:
        port_id (int): public_id of the CmdbPort to link
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the row id, the relation type or the row itself is unusable, or the
                       link already exists; 403 when the port owner's ACL denies it; 404 when the port
                       or the interface object does not exist; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPortInterfaceLink and its public_id
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        get_accessible_port_or_abort(
            ports_manager, objects_manager, port_id, request_user, AccessControlPermission.UPDATE,
        )

        multi_data_id: int = get_requested_multi_data_id_or_abort(payload)
        relation_type: str = get_requested_relation_type_or_abort(payload)

        candidate: dict[str, Any] = build_link_candidate(
            port_id, payload, multi_data_id, relation_type,
        )

        get_interface_row_or_abort(
            objects_manager,
            candidate[PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value],
            candidate[PortInterfaceLinkKey.INTERFACE_SECTION_ID.value],
            multi_data_id,
        )
        enforce_link_is_new(port_interface_links_manager, candidate)

        candidate[PortInterfaceLinkKey.AUTHOR_ID.value] = request_user.get_public_id()
        candidate[PortInterfaceLinkKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        candidate[PortInterfaceLinkKey.LAST_EDIT_TIME.value] = None

        new_id: int = port_interface_links_manager.insert_item(candidate)

        created: dict[str, Any] | None = port_interface_links_manager.get_item(new_id, as_dict=True)

        if not created:
            abort(404, 'Could not retrieve the created Port interface link from the database!')

        return InsertSingleResponse(created, new_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[insert_port_interface_link] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortInterfaceLinksManagerInsertError as err:
        # The unique index on the identity tuple is what stops two concurrent creates, and it is the
        # only thing that can: the pre-check above is a read followed by a write
        LOGGER.error("[insert_port_interface_link] PortInterfaceLinksManagerInsertError: %s", err, exc_info=True)
        abort(400, LINK_ALREADY_EXISTS_MESSAGE.format(port_id=port_id))
    except Exception as err:
        LOGGER.error("[insert_port_interface_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while creating the Port interface link!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CRUD - READ                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@port_interface_link_blueprint.route('/interface_links/dangling', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.VIEW.value)
def get_dangling_port_interface_links(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to list every link whose interface row can no longer be resolved

    The repair report. A link goes dangling because an MDS row id is not durable - the full object PUT
    does not preserve row ids and the CSV import overwrite renumbers them - and the feature tolerates
    that rather than cascading, so somebody has to be able to find the damage.

    Every CmdbObject the links name is read ONCE, not once per link: whether a row exists is a question
    about one object, and a port with several interfaces on the same peer would otherwise pay for the
    same read repeatedly.

    Declared before the `/<public_id>` route because 'dangling' is not an integer and would otherwise
    have to compete with it - Flask matches an int converter first, but stating the order makes the
    intent explicit

    Args:
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 500 on an unexpected error

    Returns:
        DefaultResponse: The dangling CmdbPortInterfaceLinks as a list, empty when nothing is broken
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        links: list[dict[str, Any]] = port_interface_links_manager.get_all_links()

        return DefaultResponse(
            collect_dangling_links(links, read_interface_objects(objects_manager, links)),
        ).make_response()
    except HTTPException as http_err:
        # Unreachable today - unlike its five siblings this route aborts nowhere inside the try, since
        # a dangling link is exactly what it is looking for and there is nothing to refuse. Kept so the
        # arm order matches every other route here: without it, an abort added later would be caught by
        # the generic handler below and reported as a 500
        raise http_err
    except PortInterfaceLinksManagerGetError as err:
        LOGGER.error("[get_dangling_port_interface_links] PortInterfaceLinksManagerGetError: %s", err, exc_info=True)
        abort(400, 'Failed to retrieve the Port interface links from the database!')
    except Exception as err:
        LOGGER.error("[get_dangling_port_interface_links] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while retrieving the dangling Port interface links!')


@port_interface_link_blueprint.route('/interface_links/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.VIEW.value)
def get_port_interface_link(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPortInterfaceLink

    The response carries the live interface row beside the link where it still resolves. A dangling
    link answers without that key rather than with an error - the customer has to see that the link
    exists and that what it named is gone

    Args:
        public_id (int): public_id of the CmdbPortInterfaceLink
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the port owner's ACL denies it; 404 when the link or its port does not
                       exist; 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested link, with its interface row when resolvable
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        link: dict[str, Any] = get_link_or_abort(port_interface_links_manager, public_id)

        get_accessible_port_or_abort(
            ports_manager, objects_manager, link.get(PortInterfaceLinkKey.PORT_ID.value),
            request_user, AccessControlPermission.READ,
        )

        with_interface_rows(objects_manager, [link])

        return GetSingleResponse(link, body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_port_interface_link] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortInterfaceLinksManagerGetError as err:
        LOGGER.error("[get_port_interface_link] PortInterfaceLinksManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Port interface link with ID: {public_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_port_interface_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the Port interface link ID: {public_id}!')


@port_interface_link_blueprint.route('/<int:port_id>/interface_links/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.VIEW.value)
def get_port_interface_links_of_port(port_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve every interface link of one CmdbPort

    A port legitimately has several - a bond member, a stack of VLAN sub-interfaces - which is what
    makes the relationship N:M. A port linked to nothing answers with an empty list, not a 404

    Args:
        port_id (int): public_id of the CmdbPort
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the port owner's ACL denies it; 404 when the port does not exist;
                       500 on an unexpected error

    Returns:
        DefaultResponse: The port's links as a list, each with its interface row when resolvable
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        get_accessible_port_or_abort(
            ports_manager, objects_manager, port_id, request_user, AccessControlPermission.READ,
        )

        links: list[dict[str, Any]] = port_interface_links_manager.get_links_of_port(port_id)

        return DefaultResponse(with_interface_rows(objects_manager, links)).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_port_interface_links_of_port] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortInterfaceLinksManagerGetError as err:
        LOGGER.error("[get_port_interface_links_of_port] PortInterfaceLinksManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the interface links of Port ID: {port_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_port_interface_links_of_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the interface links of Port ID: {port_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_interface_link_blueprint.route('/interface_links/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.EDIT.value)
def update_port_interface_link(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to change the relation type of a CmdbPortInterfaceLink

    **The relation type is the only thing an update writes.** The interface triple is the link's
    identity, so a payload naming a different row is refused rather than ignored - re-linking is a
    delete plus a create

    Args:
        public_id (int): public_id of the CmdbPortInterfaceLink to update
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the payload changes an identity key or names an invalid relation type;
                       403 when the port owner's ACL denies it; 404 when the link or its port does not
                       exist; 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbPortInterfaceLink
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        stored: dict[str, Any] = get_link_or_abort(port_interface_links_manager, public_id)

        get_accessible_port_or_abort(
            ports_manager, objects_manager, stored.get(PortInterfaceLinkKey.PORT_ID.value),
            request_user, AccessControlPermission.UPDATE,
        )

        refuse_identity_change(stored, payload)

        candidate: dict[str, Any] = dict(stored)
        candidate[PortInterfaceLinkKey.RELATION_TYPE.value] = get_requested_relation_type_or_abort(payload)
        candidate[PortInterfaceLinkKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        port_interface_links_manager.update_item(public_id, candidate)

        return UpdateSingleResponse(candidate).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[update_port_interface_link] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortInterfaceLinksManagerUpdateError as err:
        LOGGER.error("[update_port_interface_link] PortInterfaceLinksManagerUpdateError: %s", err, exc_info=True)
        abort(400, f'Failed to update the Port interface link with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[update_port_interface_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while updating the Port interface link ID: {public_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - DELETE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_interface_link_blueprint.route('/interface_links/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_interface_link_blueprint.protect(auth=True, right=PortRight.DELETE.value)
def delete_port_interface_link(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to remove a single CmdbPortInterfaceLink

    Removes the association and nothing else: neither the port nor the interface row is touched. This
    is also the route a customer uses to clear a dangling link the report showed them

    Args:
        public_id (int): public_id of the CmdbPortInterfaceLink to delete
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 403 when the port owner's ACL denies it; 404 when the link or its port does not
                       exist; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbPortInterfaceLink data
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        link: dict[str, Any] = get_link_or_abort(port_interface_links_manager, public_id)

        get_accessible_port_or_abort(
            ports_manager, objects_manager, link.get(PortInterfaceLinkKey.PORT_ID.value),
            request_user, AccessControlPermission.UPDATE,
        )

        port_interface_links_manager.delete_item(public_id)

        return DeleteSingleResponse(link).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[delete_port_interface_link] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortInterfaceLinksManagerDeleteError as err:
        LOGGER.error("[delete_port_interface_link] PortInterfaceLinksManagerDeleteError: %s", err, exc_info=True)
        abort(400, f'Failed to delete the Port interface link with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[delete_port_interface_link] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while deleting the Port interface link ID: {public_id}!')
