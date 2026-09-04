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
Creating a whole device's ports in one call - the second half of the creation assistant

Takes the SAME body as the preview and runs the SAME builders, so what is created is exactly what the
customer was shown. That is the point of the shared helper: a creation that generated its own names
would eventually disagree with the preview, and the customer would only find out afterwards.

The order of what this route does is the whole design:

  1. resolve the owner, check its ACL and that its Type uses ports
  2. build the preview - which validates the syntax, the count and the numbering
  3. **refuse if the preview found any collision**, before a single row is written
  4. create the ports, then a panel's INTERNAL connections
  5. on failure, roll back what was created and say honestly whether the cleanup finished

There is deliberately **no upper bound on the batch size** (Q28) - the mockup's 1-96 is a hint, not a
rule - and no equal-front/rear-count check, because one count drives both faces and the request cannot
express an unequal panel at all
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ExtendableOptionsManager, ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.ports_manager import PortsManagerGetError

from cmdb.framework.port.bulk_create import BulkCreateResult, create_batch
from cmdb.framework.port.bulk_create_constants import (
    BulkCreateError,
    BulkCreateKey,
    BulkResidueKey,
)
from cmdb.framework.port.name_preview import preview_has_collisions

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRight
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import (
    enforce_select_values,
    enforce_type_uses_ports,
    get_accessible_owner_or_abort,
)
from cmdb.interface.rest_api.routes.port_routes.port_preview_helper import build_preview_or_abort
from cmdb.interface.rest_api.routes.port_routes.port_bulk_helper import (
    build_shared_port_values,
    read_created_connections,
    read_created_ports,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_bulk_blueprint = APIBlueprint('port_bulk', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@port_bulk_blueprint.route('/object/<int:object_id>/bulk', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_bulk_blueprint.protect(auth=True, right=PortRight.ADD.value)
def bulk_create_ports(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a whole device's ports, and a patch panel's internal pairing

    A standard device gets n plain ports and no connections. A patch panel gets equal numbers of front
    and rear ports - equal by construction, since one count drives both faces - each pair joined by an
    automatically created INTERNAL connection. **That connection IS the pairing**; it is built from the
    two ports' public_ids and never from their names

    Args:
        object_id (int): public_id of the CmdbObject the ports are created on
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the syntax, the numbering or a select value is unusable, when the
                       preview found collisions, or when a write failed and was rolled back cleanly;
                       403 when the owner's ACL denies it; 404 when the object does not exist;
                       500 when the rollback could not remove everything it had created

    Returns:
        DefaultResponse: The created ports and, for a panel, the INTERNAL connections
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
            ManagerType.EXTENDABLE_OPTIONS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        owner: dict[str, Any] = get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.UPDATE,
        )
        enforce_type_uses_ports(types_manager, owner)
        enforce_select_values(extendable_options_manager, payload)

        preview: dict[str, Any] = build_preview_or_abort(ports_manager, object_id, payload)

        # Refused BEFORE anything is written. The preview already knows every name that could not be
        # created, so letting the batch start and fail on the twelfth would be a choice to leave a
        # half-built device behind for no benefit
        if preview_has_collisions(preview):
            abort(400, BulkCreateError.COLLISIONS_FOUND.value)

        result: BulkCreateResult = create_batch(
            ports_manager, port_connections_manager, object_id, preview,
            request_user.get_public_id(), build_shared_port_values(payload),
        )

        if not result.succeeded():
            _abort_for_failed_batch(result)

        return DefaultResponse({
            BulkCreateKey.PORTS.value: read_created_ports(ports_manager, result.port_ids),
            BulkCreateKey.CONNECTIONS.value: read_created_connections(
                port_connections_manager, result.connection_ids,
            ),
            BulkCreateKey.TOTAL_PORTS.value: len(result.port_ids),
            BulkCreateKey.TOTAL_CONNECTIONS.value: len(result.connection_ids),
        }).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[bulk_create_ports] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[bulk_create_ports] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the existing Ports of CmdbObject ID: {object_id}!')
    except Exception as err:
        LOGGER.error("[bulk_create_ports] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while creating the Ports!')


def _abort_for_failed_batch(result: BulkCreateResult) -> None:
    """
    Turns a failed batch into the honest refusal for what actually happened

    Two different outcomes, and conflating them is exactly what §37 forbids. A clean rollback left the
    database as it was, so the caller may simply fix their request and try again - a 400. A rollback
    that could not finish left rows nobody asked for, which the caller cannot fix by editing anything -
    a 500 naming every id, because somebody has to go and remove them

    Args:
        result (BulkCreateResult): The outcome of the failed batch

    Raises:
        HTTPException: 500 when the rollback left residue, 400 when it did not
    """
    if result.has_residue():
        abort(500, BulkCreateError.ROLLBACK_INCOMPLETE.format(
            reason=result.error,
            residue={
                BulkResidueKey.PORT_IDS.value: result.residual_port_ids,
                BulkResidueKey.CONNECTION_IDS.value: result.residual_connection_ids,
            },
        ))

    abort(400, BulkCreateError.ROLLED_BACK.format(
        created=len(result.port_ids), reason=result.error,
    ))
