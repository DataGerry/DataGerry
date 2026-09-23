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
The bulk surfaces of the ports table: creating a whole device's ports, and acting on a selection

Two different things share this blueprint. **Bulk creation** is the second half of the creation
assistant; the **bulk actions** (edit, delete and the delete pre-check) are §30-35's operations over a
selection the user ticked in the table. What they have in common is the object scope: every one of
them is addressed as `/ports/object/<object_id>/...`, because a selection can only ever name rows of
the table the user is looking at.

The bulk actions obey one rule the creation does not need: **validated as a whole, applied only if
every element passes** - nothing partial, and a refusal lists every reason at once. Resolving
connections is the third §30-35 action and lives on `/port_connections`, since a connection belongs to
neither of the two devices it joins.

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
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response

from cmdb.manager import ExtendableOptionsManager, ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.port_model import PortKey
from cmdb.models.port_connection_model import PortConnectionKey
from cmdb.models.port_interface_link_model import PortInterfaceLinkKey
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.ports_manager import PortsManagerGetError, PortsManagerDeleteError, \
    PortsManagerUpdateError

from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager

from cmdb.framework.port.bulk_actions import (
    build_bulk_edit_values,
    build_delete_preview,
    bulk_edit_value_blockers,
    collect_ids,
)
from cmdb.framework.port.bulk_action_constants import (
    BulkActionKey,
    BulkActionRequestKey,
)
from cmdb.framework.port.cascade import delete_connections_of_ports, delete_interface_links_of_ports
from cmdb.framework.port.bulk_create import BulkCreateResult, create_batch
from cmdb.framework.port.bulk_create_constants import (
    BulkCreateError,
    BulkCreateKey,
    BulkResidueKey,
)
from cmdb.framework.port.name_preview import preview_has_collisions

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
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
    abort_bulk_action,
    build_values_by_side,
    rear_select_payload,
    get_selected_ports_or_abort,
    get_selection_or_abort,
    read_created_connections,
    read_created_ports,
    read_port_dependents,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_bulk_blueprint = APIBlueprint('port_bulk', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@port_bulk_blueprint.route('/object/<int:object_id>/bulk', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_bulk_blueprint.protect(auth=True, right=PortRight.ADD.value)
@handle_route_errors("while creating the Ports")
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
        # The rear face's own select values, judged by the same rule: the projection puts them under
        # the unprefixed key names the validator knows
        enforce_select_values(extendable_options_manager, rear_select_payload(payload))

        preview: dict[str, Any] = build_preview_or_abort(ports_manager, object_id, payload)

        # Refused BEFORE anything is written. The preview already knows every name that could not be
        # created, so letting the batch start and fail on the twelfth would be a choice to leave a
        # half-built device behind for no benefit
        if preview_has_collisions(preview):
            abort(400, BulkCreateError.COLLISIONS_FOUND.value)

        result: BulkCreateResult = create_batch(
            ports_manager, port_connections_manager, object_id, preview,
            request_user.get_public_id(), build_values_by_side(payload),
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
    except AccessDeniedError as err:
        LOGGER.error("[bulk_create_ports] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[bulk_create_ports] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the existing Ports of CmdbObject ID: {object_id}!')


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

# -------------------------------------------------------------------------------------------------------------------- #
#                                            the bulk ACTIONS (§30-35)                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

@port_bulk_blueprint.route('/object/<int:object_id>/bulk', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_bulk_blueprint.protect(auth=True, right=PortRight.EDIT.value)
@handle_route_errors("while updating the selected Ports")
def bulk_edit_ports(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route to set the shared properties of several CmdbPorts of one CmdbObject at once

    The body is ``{'port_ids': [...], 'values': {...}}``. Only the four shared properties may be set -
    status, port type, speed and description: a name identifies a port within its face, so one value
    applied to a selection would collide by construction, and the owner and the side are a port's
    identity. A field the values block leaves out keeps whatever each port already has, which is what
    makes "set the speed of these twelve" expressible without touching their statuses.

    **Validated as a whole**: an id naming another device's port, or a field outside the allowed four,
    refuses the entire request and nothing is written. One `$set` then updates the whole selection

    Args:
        object_id (int): public_id of the CmdbObject whose ports are edited
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the selection or the values are unusable, or a select value is not an
                       option of its own list; 403 when the object's ACL denies it; 404 when the
                       object does not exist; 500 on an unexpected error

    Returns:
        DefaultResponse: How many ports were updated, and which
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
            ManagerType.EXTENDABLE_OPTIONS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.UPDATE,
        )

        port_ids: list[int] = get_selection_or_abort(payload, BulkActionRequestKey.PORT_IDS.value)
        raw_values: Any = payload.get(BulkActionRequestKey.VALUES.value)

        abort_bulk_action(bulk_edit_value_blockers(raw_values))
        get_selected_ports_or_abort(ports_manager, object_id, port_ids)

        # The same cross-collection rule the single update runs: a select field stores the public_id
        # of an option of ITS own list, which no schema or index can express
        enforce_select_values(extendable_options_manager, raw_values)

        values: dict[str, Any] = build_bulk_edit_values(raw_values)
        values[PortKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        # One write for the whole selection - the values are identical for every port by definition
        ports_manager.update_many(
            criteria={PortKey.PUBLIC_ID.value: {'$in': port_ids}}, update=values,
        )

        return DefaultResponse({
            BulkActionKey.UPDATED.value: len(port_ids),
            BulkActionKey.PORT_IDS.value: port_ids,
        }).make_response()
    except AccessDeniedError as err:
        LOGGER.error("[bulk_edit_ports] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except (PortsManagerGetError, PortsManagerUpdateError) as err:
        LOGGER.error("[bulk_edit_ports] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f'Failed to update the selected Ports of CmdbObject ID: {object_id}!')


@port_bulk_blueprint.route('/object/<int:object_id>/bulk/delete_preview', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_bulk_blueprint.protect(auth=True, right=PortRight.VIEW.value)
@handle_route_errors("while previewing the deletion of the Ports")
def preview_bulk_delete_ports(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route answering what a bulk delete of these CmdbPorts would take with it

    **Writes nothing.** The concept requires a bulk action to inform the user of its consequences
    (§41), and deleting a port is never only the port: its connections and its interface links go with
    it, and neither was named by the caller - a connection in particular may be the customer's record
    of a cable that physically exists.

    A `POST` because the selection is a body, not a query string: a device can have 96 ports and an id
    list does not belong in a URL. It validates its selection exactly as the delete does, so a preview
    that answers is a delete that will not be refused

    Args:
        object_id (int): public_id of the CmdbObject whose ports would be deleted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the selection is unusable; 403 when the object's ACL denies it;
                       404 when the object does not exist; 500 on an unexpected error

    Returns:
        DefaultResponse: One entry per port naming what it would lose, plus the distinct totals
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.READ,
        )

        port_ids: list[int] = get_selection_or_abort(payload, BulkActionRequestKey.PORT_IDS.value)
        ports: list[dict[str, Any]] = get_selected_ports_or_abort(ports_manager, object_id, port_ids)

        connections, interface_links = read_port_dependents(
            port_connections_manager, port_interface_links_manager, port_ids,
        )

        return DefaultResponse({
            BulkActionKey.PORTS.value: build_delete_preview(ports, connections, interface_links),
            BulkActionKey.PORT_IDS.value: port_ids,
            # The DISTINCT ids: a connection between two selected ports appears under both of them in
            # the per-port list, and counting it twice would overstate what the delete removes
            BulkActionKey.CONNECTION_IDS.value: collect_ids(
                connections, PortConnectionKey.PUBLIC_ID.value,
            ),
            BulkActionKey.INTERFACE_LINK_IDS.value: collect_ids(
                interface_links, PortInterfaceLinkKey.PUBLIC_ID.value,
            ),
        }).make_response()
    except AccessDeniedError as err:
        LOGGER.error("[preview_bulk_delete_ports] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[preview_bulk_delete_ports] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the selected Ports of CmdbObject ID: {object_id}!')


@port_bulk_blueprint.route('/object/<int:object_id>/bulk', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_bulk_blueprint.protect(auth=True, right=PortRight.DELETE.value)
@handle_route_errors("while deleting the selected Ports")
def bulk_delete_ports(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete several CmdbPorts of one CmdbObject at once

    The body is ``{'port_ids': [...]}`` - a `DELETE` with a body, because the selection is a list and
    a device can have 96 ports. Each port takes its CONNECTIONS and its INTERFACE LINKS with it, the
    same cascade the single delete runs and for the same reason: neither may be left pointing at a
    port that no longer exists. Both run as ONE batched delete for the whole selection.

    The answer names what the cascade removed, not only the ports: those rows were never named by the
    caller, and `GET .../bulk/delete_preview` is the same list before the fact.

    **Validated as a whole**: one id naming another device's port refuses the request and nothing is
    deleted

    Args:
        object_id (int): public_id of the CmdbObject whose ports are deleted
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the selection is unusable; 403 when the object's ACL denies it;
                       404 when the object does not exist; 500 on an unexpected error

    Returns:
        DefaultResponse: How many ports were deleted, which, and what went with them
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.UPDATE,
        )

        port_ids: list[int] = get_selection_or_abort(payload, BulkActionRequestKey.PORT_IDS.value)
        get_selected_ports_or_abort(ports_manager, object_id, port_ids)

        # Read BEFORE the cascade: afterwards the rows are gone and the answer could only say how many
        connections, interface_links = read_port_dependents(
            port_connections_manager, port_interface_links_manager, port_ids,
        )

        # Dependents first, then the ports: each is found THROUGH its port, and a deleted port can no
        # longer be looked up - the same order the single delete and the object hook use
        delete_connections_of_ports(port_connections_manager, port_ids)
        delete_interface_links_of_ports(port_interface_links_manager, port_ids)

        ports_manager.delete_many({PortKey.PUBLIC_ID.value: {'$in': port_ids}})

        return DefaultResponse({
            BulkActionKey.DELETED.value: len(port_ids),
            BulkActionKey.PORT_IDS.value: port_ids,
            BulkActionKey.CONNECTION_IDS.value: collect_ids(
                connections, PortConnectionKey.PUBLIC_ID.value,
            ),
            BulkActionKey.INTERFACE_LINK_IDS.value: collect_ids(
                interface_links, PortInterfaceLinkKey.PUBLIC_ID.value,
            ),
        }).make_response()
    except AccessDeniedError as err:
        LOGGER.error("[bulk_delete_ports] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except (PortsManagerGetError, PortsManagerDeleteError) as err:
        LOGGER.error("[bulk_delete_ports] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, f'Failed to delete the selected Ports of CmdbObject ID: {object_id}!')
