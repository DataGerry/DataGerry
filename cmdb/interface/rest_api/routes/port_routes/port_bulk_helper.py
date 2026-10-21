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
Reading a bulk-creation request body, and reading the created rows back for the response
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_connection_model import PortConnectionKey
from cmdb.models.port_model import PortKey, PortSide

from cmdb.framework.port.bulk_action_constants import (
    BULK_ACTION_ABORT_PREFIX,
    BULK_ACTION_SEPARATOR,
    BulkActionError,
)
from cmdb.framework.port.bulk_actions import (
    connection_selection_blockers,
    coerce_id_selection,
    port_selection_blockers,
)

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRequestKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The port fields a whole batch may share. The name and the side come from the preview, one per port;
# these are the assistant form's "apply to all of them" values - a customer creating 48 uplinks almost
# always wants them all Up / SFP+ / 10G, and setting that afterwards would mean 48 more requests
SHARED_PORT_REQUEST_KEYS: tuple[PortRequestKey, ...] = (
    PortRequestKey.STATUS,
    PortRequestKey.PORT_TYPE,
    PortRequestKey.SPEED,
    PortRequestKey.DESCRIPTION,
)

# The rear face's own value for each of those four, keyed by the shared key it overrides. A panel's
# rear ports are not the same equipment as its front ports - a different port type and speed is the
# normal case, not the exception - so the assistant asks for both and the request carries both
REAR_PORT_REQUEST_KEYS: dict[PortRequestKey, PortRequestKey] = {
    PortRequestKey.STATUS: PortRequestKey.REAR_STATUS,
    PortRequestKey.PORT_TYPE: PortRequestKey.REAR_PORT_TYPE,
    PortRequestKey.SPEED: PortRequestKey.REAR_SPEED,
    PortRequestKey.DESCRIPTION: PortRequestKey.REAR_DESCRIPTION,
}

# -------------------------------------------------------------------------------------------------------------------- #

def build_shared_port_values(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Reads the field values every port of a batch will carry

    Only the keys a request owns: the identity, the owner, the side, the name and the audit fields are
    the batch's own business and are never read from here. A key the body omits is left out entirely
    rather than written as null, so the model's own defaults still apply

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The shared field values, empty when the body sets none
    """
    return {
        PortKey[key.name].value: payload[key.value]
        for key in SHARED_PORT_REQUEST_KEYS
        if payload.get(key.value) is not None
    }


def build_rear_port_values(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Reads the rear face's own field values out of a bulk-create body

    Only the four `REAR_*` keys, translated to the port document's own key names - so the result is
    mergeable over `build_shared_port_values` without either side knowing about the other. A key the
    body omits is left out rather than written as null, which is what makes the shared value the
    default instead of being erased by an absent override

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The rear-only field values, empty when the body sets none
    """
    return {
        PortKey[shared.name].value: payload[rear.value]
        for shared, rear in REAR_PORT_REQUEST_KEYS.items()
        if payload.get(rear.value) is not None
    }


def build_values_by_side(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Resolves the field values each face of a batch will carry

    The unprefixed keys are the values for **every** face; the `REAR_*` keys override them for the
    rear one. Resolved here rather than in the creation so the framework layer is handed finished
    values per face and never has to know the request's vocabulary

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, dict[str, Any]]: The field values keyed by PortSide value, one entry per side
    """
    shared: dict[str, Any] = build_shared_port_values(payload)
    rear: dict[str, Any] = build_rear_port_values(payload)

    return {
        PortSide.SINGLE.value: shared,
        PortSide.FRONT.value: shared,
        PortSide.REAR.value: {**shared, **rear},
    }


def rear_select_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Projects the rear face's select values onto the unprefixed keys

    So `enforce_select_values` - which knows which option list each of the three select fields draws
    from - validates the rear values by the same rule as the front ones, without growing a second
    spelling of that rule

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The rear values under their unprefixed key names, empty when none are set
    """
    return {
        shared.value: payload[rear.value]
        for shared, rear in REAR_PORT_REQUEST_KEYS.items()
        if payload.get(rear.value) is not None
    }


def read_created_ports(ports_manager: PortsManager, port_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the ports a batch created, in one query, ordered as they were created

    The frontend renders the new ports straight from the response, so they come back as stored rather
    than as the candidates that were sent - which is what makes the server-owned fields visible

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_ids (list[int]): The created ports' public_ids, in creation order

    Returns:
        list[dict[str, Any]]: The created port documents, in creation order
    """
    return _read_in_order(ports_manager, PortKey.PUBLIC_ID.value, port_ids)


def read_created_connections(
        port_connections_manager: PortConnectionsManager,
        connection_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the INTERNAL connections a panel's creation produced, in one query

    Returned rather than left for the caller to look up, because those connections ARE the pairing -
    a client that had to go and find them could not tell which front port was joined to which rear one

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        connection_ids (list[int]): The created connections' public_ids, in creation order

    Returns:
        list[dict[str, Any]]: The created connection documents, in creation order
    """
    return _read_in_order(port_connections_manager, PortConnectionKey.PUBLIC_ID.value, connection_ids)


def _read_in_order(manager: Any, id_key: str, public_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads rows by public_id and returns them in the order the ids were given

    One `$in` rather than one read per row, then re-ordered in memory: Mongo answers an `$in` in index
    order, not in the order asked for, and a panel whose pairing is read back scrambled would be
    unreadable beside its connections

    Args:
        manager (Any): The manager owning the collection
        id_key (str): Name of the collection's public_id field
        public_ids (list[int]): The ids to read, in the order they should come back

    Returns:
        list[dict[str, Any]]: The rows, in the requested order; missing ones are skipped
    """
    if not public_ids:
        return []

    by_id: dict[int, dict[str, Any]] = {
        row[id_key]: row
        for row in manager.find(criteria={id_key: {'$in': public_ids}})
        if id_key in row
    }

    return [by_id[public_id] for public_id in public_ids if public_id in by_id]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the bulk ACTIONS (§30-35)                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def get_selection_or_abort(payload: dict[str, Any], key: str) -> list[int]:
    """
    Reads a bulk action's selection out of the body, or aborts

    Args:
        payload (dict[str, Any]): The request body
        key (str): The body key holding the ids (`port_ids` / `connection_ids`)

    Raises:
        HTTPException: 400 when the value is not a non-empty list of ids

    Returns:
        list[int]: The selected ids, de-duplicated, in the order they were sent
    """
    selection: list[int] | None = coerce_id_selection(payload.get(key))

    if selection is None:
        abort(400, BulkActionError.INVALID_SELECTION.format(key=key))

    return selection


def abort_bulk_action(blockers: list[str]) -> None:
    """
    Aborts 400 with every reason a bulk action was refused, in one message

    The prefix says NOTHING was changed, which is the part a caller has to be able to rely on: a bulk
    action is validated as a whole, so a refusal means the selection is untouched rather than
    partially applied

    Args:
        blockers (list[str]): The reasons found; a no-op when empty

    Raises:
        HTTPException: 400 when there is at least one reason
    """
    if blockers:
        abort(400, f'{BULK_ACTION_ABORT_PREFIX}: {BULK_ACTION_SEPARATOR.join(blockers)}')


def read_ports_by_id(ports_manager: PortsManager, port_ids: list[int]) -> dict[int, dict[str, Any]]:
    """
    Reads the selected CmdbPorts in ONE query, keyed by public_id

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_ids (list[int]): The selected port ids

    Returns:
        dict[int, dict[str, Any]]: The ports that exist, keyed by public_id
    """
    if not port_ids:
        return {}

    return {
        port[PortKey.PUBLIC_ID.value]: port
        for port in ports_manager.find(criteria={PortKey.PUBLIC_ID.value: {'$in': port_ids}})
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    }


def get_selected_ports_or_abort(
        ports_manager: PortsManager,
        object_id: int,
        port_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the selected ports and refuses the whole selection unless every id is this object's

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject the action is scoped to
        port_ids (list[int]): The selected port ids

    Raises:
        HTTPException: 400 when an id names no port, or a port of another CmdbObject

    Returns:
        list[dict[str, Any]]: The selected port documents, in the order they were selected
    """
    ports_by_id: dict[int, dict[str, Any]] = read_ports_by_id(ports_manager, port_ids)

    abort_bulk_action(port_selection_blockers(ports_by_id, object_id, port_ids))

    return [ports_by_id[port_id] for port_id in port_ids]


def get_selected_connections_or_abort(
        port_connections_manager: PortConnectionsManager,
        ports_manager: PortsManager,
        object_id: int,
        connection_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the selected connections and refuses the whole selection unless every one touches the object

    Two queries: the connections themselves, and the object's own port ids - which is what "this
    object's connections" means, a connection belonging to no single device

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the CmdbObject the action is scoped to
        connection_ids (list[int]): The selected connection ids

    Raises:
        HTTPException: 400 when an id names no connection, or one with neither end on this object

    Returns:
        list[dict[str, Any]]: The selected connection documents, in the order they were selected
    """
    connections_by_id: dict[int, dict[str, Any]] = {
        connection[PortConnectionKey.PUBLIC_ID.value]: connection
        for connection in port_connections_manager.find(
            criteria={PortConnectionKey.PUBLIC_ID.value: {'$in': connection_ids}},
        )
        if isinstance(connection.get(PortConnectionKey.PUBLIC_ID.value), int)
    }

    object_port_ids: set[int] = {
        port[PortKey.PUBLIC_ID.value]
        for port in ports_manager.get_ports_of_object(object_id)
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    }

    abort_bulk_action(connection_selection_blockers(
        connections_by_id, object_port_ids, object_id, connection_ids,
    ))

    return [connections_by_id[connection_id] for connection_id in connection_ids]


def read_port_dependents(
        port_connections_manager: PortConnectionsManager,
        port_interface_links_manager: PortInterfaceLinksManager,
        port_ids: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Reads everything that would go with a set of ports - their connections and their interface links

    One batched query each for the whole selection, the shape every per-page port read uses. Shared by
    the delete pre-check and the delete itself, so what the dialog showed is what the action reports

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        port_interface_links_manager (PortInterfaceLinksManager): db interface for the interface links
        port_ids (list[int]): The selected port ids

    Returns:
        tuple[list[dict[str, Any]], list[dict[str, Any]]]: The connections and the interface links
    """
    return (
        port_connections_manager.get_connections_of_ports(port_ids),
        port_interface_links_manager.get_links_of_ports(port_ids),
    )
