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
The port name preview - what a batch WOULD be called, before anything is created

**This route writes nothing.** It exists so a customer about to create 48 ports can see the names, the
pairing of a patch panel's two faces, and every collision, while it still costs them nothing to change
their mind. Step 12's creation runs the same builders on the same request shape, so the preview cannot
promise something the creation does differently - a preview that is a second implementation is one that
eventually lies.

It is a POST because it carries a body, not because it changes anything. A GET with a syntax, two
counts, a prefix and a slot in the query string would be unreadable and would cap the syntax at
whatever the URL length allows.

Guarded by the port ADD right and the owner object's ACL: previewing names against an object tells you
what that object already has, which is the same information the ports list gives - and the operation it
previews is a create
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.ports_manager import PortsManagerGetError

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRight
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import (
    enforce_type_uses_ports,
    get_accessible_owner_or_abort,
)
from cmdb.interface.rest_api.routes.port_routes.port_preview_helper import build_preview_or_abort
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_preview_blueprint = APIBlueprint('port_previews', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@port_preview_blueprint.route('/object/<int:object_id>/name_preview', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_preview_blueprint.protect(auth=True, right=PortRight.ADD.value)
def preview_port_names(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to preview the port names a batch would produce, writing nothing

    Answers with one entry per face - one for a standard device, two for a patch panel - each carrying
    its generated names and its collisions, plus a panel's positional pairing and the total port count.
    A preview with collisions is still a 200: the names ARE what that syntax produces, and the customer
    needs to see them to fix it. Only the creation in step 12 refuses

    Args:
        object_id (int): public_id of the CmdbObject the ports would be created on
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the device kind, the syntax or the numbering is unusable; 403 when the
                       owner's ACL denies it; 404 when the object does not exist; 500 on an unexpected
                       error

    Returns:
        DefaultResponse: The preview document
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        owner: dict[str, Any] = get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.UPDATE,
        )
        enforce_type_uses_ports(types_manager, owner)

        return DefaultResponse(
            build_preview_or_abort(ports_manager, object_id, payload),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[preview_port_names] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[preview_port_names] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the existing Ports of CmdbObject ID: {object_id}!')
    except Exception as err:
        LOGGER.error("[preview_port_names] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while previewing the Port names!')
