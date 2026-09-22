# DATAGERRY - OpenSource Enterprise CMDB
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
The port BULK ACTIONS the concept asks for in §30-35: edit, delete, and resolve connections

Three actions over a SELECTION, and one rule they all obey:

**A bulk action is validated as a whole and applied only if every element passes.** Nothing partial
ever happens, and a refusal lists every reason at once. That is a deliberate choice over the
report-per-entry shape the CSV importers use: an importer is fed a file nobody read, while a bulk
action is a selection a user just made in a table - "three of your five ports were updated" is a state
they then have to reverse-engineer, and the fix is one click away anyway.

**Every action is scoped to one CmdbObject**, taken from the URL. A selection is what a checkbox
column produces, so it can only ever name rows of the table the user is looking at; an id from another
device is a client bug and is refused rather than silently obeyed. For the connections that means at
least ONE endpoint on that object - a cable legitimately reaches another device, and resolving it from
either end is the same act.

**Resolving is granular** (§34): the selection names CONNECTION ids, never ports. A patch-panel pair
carries a front, a rear and an internal connection, and each has to be resolvable on its own - only an
id per connection can express "the internal one, and nothing else". The rule §35 states, *resolving one
connection must never delete another*, is then structural rather than something the code has to
remember.

Pure and free of Flask: every function reports its reasons and the routes decide whether to abort
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.port_model.port_constants import PortKey
from cmdb.models.port_connection_model.port_connection_constants import PortConnectionKey
from cmdb.models.port_interface_link_model import PortInterfaceLinkKey

from cmdb.framework.port.bulk_action_constants import (
    BULK_EDITABLE_FIELDS,
    BulkActionError,
    BulkActionRequestKey,
    BulkDeletePreviewKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# How the allowed field names are listed in a refusal
ALLOWED_FIELDS_SEPARATOR: str = ', '


def coerce_id_selection(raw_selection: Any) -> list[int] | None:
    """
    Reads a bulk action's selection out of a request body

    A selection is a non-empty list of whole ids. Duplicates are collapsed - a table can send the same
    row twice and it means the same thing - and the caller's order is kept so a report reads back the
    way the selection was made

    Args:
        raw_selection (Any): The raw ids value from the request

    Returns:
        list[int] | None: The ids, or None when the value is not a usable selection
    """
    if not isinstance(raw_selection, list) or not raw_selection:
        return None

    selection: list[int] = []

    for entry in raw_selection:
        # bool is an int subclass in Python, so True would otherwise pass as the id 1
        if isinstance(entry, bool) or not isinstance(entry, int):
            return None

        if entry not in selection:
            selection.append(entry)

    return selection


def port_selection_blockers(
        ports_by_id: dict[int, dict[str, Any]],
        object_id: int,
        port_ids: list[int]) -> list[str]:
    """
    Judges a port selection against the object the action runs on

    Two reasons, reported per id rather than as one summary: a port that does not exist, and one that
    exists on ANOTHER device. They are different mistakes - a stale table versus a client that built
    its selection from the wrong list - and the message says which

    Args:
        ports_by_id (dict[int, dict[str, Any]]): The ports that exist, keyed by public_id
        object_id (int): public_id of the CmdbObject the action is scoped to
        port_ids (list[int]): The selected port ids

    Returns:
        list[str]: One reason per unusable id; empty when the whole selection is this object's
    """
    blockers: list[str] = []

    for port_id in port_ids:
        port: dict[str, Any] | None = ports_by_id.get(port_id)

        if port is None:
            blockers.append(BulkActionError.UNKNOWN_PORT.format(port_id=port_id))
            continue

        if port.get(PortKey.OBJECT_ID.value) != object_id:
            blockers.append(BulkActionError.FOREIGN_PORT.format(port_id=port_id, object_id=object_id))

    return blockers


def connection_selection_blockers(
        connections_by_id: dict[int, dict[str, Any]],
        object_port_ids: set[int],
        object_id: int,
        connection_ids: list[int]) -> list[str]:
    """
    Judges a connection selection against the object the action runs on

    A connection belongs to no single device - it joins two - so "this object's connections" means the
    ones with at least ONE endpoint among its ports. Resolving a cable from either end is the same
    act, and the far end is often a device the user is not looking at

    Args:
        connections_by_id (dict[int, dict[str, Any]]): The connections that exist, keyed by public_id
        object_port_ids (set[int]): public_ids of every port of the object the action is scoped to
        object_id (int): public_id of that CmdbObject, for the message
        connection_ids (list[int]): The selected connection ids

    Returns:
        list[str]: One reason per unusable id; empty when every one touches this object
    """
    blockers: list[str] = []

    for connection_id in connection_ids:
        connection: dict[str, Any] | None = connections_by_id.get(connection_id)

        if connection is None:
            blockers.append(BulkActionError.UNKNOWN_CONNECTION.format(connection_id=connection_id))
            continue

        endpoints: Any = connection.get(PortConnectionKey.ENDPOINTS.value) or []

        if not object_port_ids.intersection(endpoints):
            blockers.append(BulkActionError.FOREIGN_CONNECTION.format(
                connection_id=connection_id, object_id=object_id,
            ))

    return blockers


def bulk_edit_value_blockers(raw_values: Any) -> list[str]:
    """
    Judges the values block of a bulk edit

    Only the four shared properties may be set (BULK_EDITABLE_FIELDS). A field outside that list is
    REPORTED rather than dropped: silently ignoring `name` would answer 200 to a request that asked to
    rename a selection, and the caller would find out by reading the table

    Args:
        raw_values (Any): The raw values block from the request

    Returns:
        list[str]: The reasons the values are refused; empty when they are usable
    """
    allowed: str = ALLOWED_FIELDS_SEPARATOR.join(field.value for field in BULK_EDITABLE_FIELDS)

    if not isinstance(raw_values, dict) or not raw_values:
        return [BulkActionError.NO_VALUES.format(key=BulkActionRequestKey.VALUES.value, allowed=allowed)]

    allowed_names: set[str] = {field.value for field in BULK_EDITABLE_FIELDS}

    return [
        BulkActionError.UNKNOWN_VALUE_FIELD.format(field=field, allowed=allowed)
        for field in raw_values
        if field not in allowed_names
    ]


def build_bulk_edit_values(raw_values: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the ``$set`` a bulk edit applies, from the values it was given

    Only the allowed fields the request actually carries: a field it left out keeps whatever each
    selected port already has, which is what makes "set the speed of these twelve ports" expressible
    without touching their statuses. A null IS a value - it clears the field - so it is kept

    Args:
        raw_values (dict[str, Any]): The validated values block

    Returns:
        dict[str, Any]: The port keys to write, in the model's field order
    """
    return {
        field.value: raw_values[field.value] for field in BULK_EDITABLE_FIELDS
        if field.value in raw_values
    }


def build_delete_preview(
        ports: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        interface_links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Builds what a bulk delete would take with it, per port

    The answer to §41's *"inform the user of the consequences"*: deleting a port is never only the
    port. Its connections and its interface links go too, and neither was named by the caller - the
    connections in particular may be the customer's record of a cable that physically exists

    A connection appears under BOTH of its ports when both are in the selection, deliberately: the
    dialog lists per port what that row loses, and a caller counting distinct ids has them in the
    action's own answer instead

    Args:
        ports (list[dict[str, Any]]): The selected port documents, in the order to report them
        connections (list[dict[str, Any]]): Every connection of those ports
        interface_links (list[dict[str, Any]]): Every interface link of those ports

    Returns:
        list[dict[str, Any]]: One entry per port, naming it and what it would take with it
    """
    preview: list[dict[str, Any]] = []

    for port in ports:
        port_id: Any = port.get(PortKey.PUBLIC_ID.value)

        preview.append({
            BulkDeletePreviewKey.PORT_ID.value: port_id,
            BulkDeletePreviewKey.NAME.value: port.get(PortKey.NAME.value),
            BulkDeletePreviewKey.SIDE.value: port.get(PortKey.SIDE.value),
            BulkDeletePreviewKey.CONNECTION_IDS.value: [
                connection[PortConnectionKey.PUBLIC_ID.value] for connection in connections
                if port_id in (connection.get(PortConnectionKey.ENDPOINTS.value) or [])
            ],
            BulkDeletePreviewKey.INTERFACE_LINK_IDS.value: [
                link[PortInterfaceLinkKey.PUBLIC_ID.value] for link in interface_links
                if link.get(PortInterfaceLinkKey.PORT_ID.value) == port_id
            ],
        })

    return preview


def collect_ids(documents: list[dict[str, Any]], key: str) -> list[int]:
    """
    Reads the ids out of a list of documents, once each and in the order they came

    Shared by the delete report and the preview totals, which both have to say what a cascade covered
    without counting the same connection twice for its two ports

    Args:
        documents (list[dict[str, Any]]): The documents to read
        key (str): The document key holding the id

    Returns:
        list[int]: The ids, de-duplicated
    """
    ids: list[int] = []

    for document in documents:
        value: Any = document.get(key)

        if isinstance(value, int) and value not in ids:
            ids.append(value)

    return ids
