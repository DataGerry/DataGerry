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
Creating a whole device's ports in one call, and undoing it when a write fails part-way

DataGerry does not require a replica set, so there is no transaction to roll back into. The concept's
§37 - *never 24 front / 18 rear / 18 internal* - is therefore met by a **best-effort compensating
rollback**: everything created so far is removed in reverse order, and if that cleanup itself cannot
finish, the caller is told exactly what was left behind rather than being handed a success or a clean
failure. A half-built patch panel that nobody knows about is the one outcome this module exists to
prevent.

**The order is load-bearing in both directions.**

  - Forward: **ports first, then the internal connections.** A connection stores two port ids, so
    creating it before its ports would reference rows that do not exist yet - and a failure between the
    two would leave a connection pointing at nothing, which is worse than leaving a port with no cable.
  - Backward: **connections first, then ports.** The reverse of the same reasoning - removing a port
    while its connection still names it would recreate exactly the dangling row the forward order
    avoided.

**The pairing is the connection, never the names.** A panel's front port i is joined to rear port i by
an INTERNAL connection created here, using the two ports' public_ids. The names are not consulted; the
concept forbids deriving the pairing from them, and a test pins that two faces sharing no naming scheme
still pair correctly
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any, NamedTuple

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey, sort_endpoints
from cmdb.models.port_model import PortKey

from cmdb.framework.port.name_syntax_constants import PortPreviewKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


class BulkCreateResult(NamedTuple):
    """
    What a bulk creation did, whether or not it succeeded

    Attributes:
        port_ids (list[int]): public_ids of the ports that were created, in creation order
        connection_ids (list[int]): public_ids of the INTERNAL connections that were created
        error (str | None): The reason the batch stopped, or None when it completed
        residual_port_ids (list[int]): Ports the rollback could not remove - empty unless it failed
        residual_connection_ids (list[int]): Connections the rollback could not remove
    """
    port_ids: list[int]
    connection_ids: list[int]
    error: str | None
    # No default: a shared mutable default on a NamedTuple field is one accidental mutation away from
    # leaking between results, and every call site knows what it created anyway
    residual_port_ids: list[int]
    residual_connection_ids: list[int]


    def succeeded(self) -> bool:
        """
        Reports whether the whole batch was created

        Returns:
            bool: True when nothing failed
        """
        return self.error is None


    def has_residue(self) -> bool:
        """
        Reports whether the rollback left rows behind

        The one outcome that is neither a success nor a clean failure, and the reason the caller has
        to distinguish the two

        Returns:
            bool: True when anything the batch created is still stored
        """
        return bool(self.residual_port_ids or self.residual_connection_ids)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   creating the rows                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

#pylint: disable=R0913, R0917
def create_face_ports(
        ports_manager: PortsManager,
        object_id: int,
        face: dict[str, Any],
        author_id: int,
        base_candidate: dict[str, Any],
        ledger: list[int]) -> list[int]:
    """
    Creates every port of one previewed face, in the order the preview listed them

    The names come from the preview rather than being generated again, which is what makes the created
    ports exactly the ones the customer was shown.

    **`ledger` is appended to in a `finally`, and that is the point.** A face of 24 ports can fail on
    its thirteenth, and the twelve already written have to be rollback-able. Returning them only on
    success would lose exactly the ports a partial failure leaves behind - which is the state §37
    exists to prevent, and the one a caller would never notice was missing

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        object_id (int): public_id of the owner CmdbObject
        face (dict[str, Any]): One face of a preview, carrying its side and its names
        author_id (int): public_id of the CmdbUser creating the batch
        base_candidate (dict[str, Any]): The field values every port of the batch shares - the select
            fields and the description the assistant form applied to all of them
        ledger (list[int]): The caller's record of everything created so far. Extended with this
            face's ports whether or not the face completes

    Returns:
        list[int]: The created ports' public_ids, in creation order
    """
    created: list[int] = []

    try:
        for name in face[PortPreviewKey.NAMES.value]:
            candidate: dict[str, Any] = {
                **base_candidate,
                PortKey.OBJECT_ID.value: object_id,
                PortKey.SIDE.value: face[PortPreviewKey.SIDE.value],
                PortKey.NAME.value: name,
                PortKey.AUTHOR_ID.value: author_id,
                PortKey.CREATION_TIME.value: datetime.now(timezone.utc),
                PortKey.LAST_EDIT_TIME.value: None,
            }

            created.append(ports_manager.insert_item(candidate))
    finally:
        ledger.extend(created)

    return created


def create_internal_connections(
        port_connections_manager: PortConnectionsManager,
        front_ids: list[int],
        rear_ids: list[int],
        author_id: int,
        ledger: list[int]) -> list[int]:
    """
    Joins a panel's two faces, pair by pair, with an INTERNAL connection

    **This is the pairing.** Front port i is joined to rear port i by public_id; the names are never
    consulted, because the concept forbids deriving the pairing from them - two faces named nothing
    alike pair just as correctly as two that match.

    The endpoints are stored canonically sorted like every other connection, so the panel's internal
    links are indistinguishable in shape from a cable and are covered by the same unique index

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        front_ids (list[int]): The front ports' public_ids, in face order
        rear_ids (list[int]): The rear ports' public_ids, in the same order
        author_id (int): public_id of the CmdbUser creating the batch
        ledger (list[int]): The caller's record of the connections created so far. Extended whether or
            not the pairing completes, for the same reason the port ledger is

    Returns:
        list[int]: The created connections' public_ids, in creation order
    """
    created: list[int] = []

    try:
        for front_id, rear_id in zip(front_ids, rear_ids, strict=True):
            created.append(port_connections_manager.insert_item({
                PortConnectionKey.ENDPOINTS.value: sort_endpoints([front_id, rear_id]),
                PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
                PortConnectionKey.AUTHOR_ID.value: author_id,
                PortConnectionKey.CREATION_TIME.value: datetime.now(timezone.utc),
                PortConnectionKey.LAST_EDIT_TIME.value: None,
            }))
    finally:
        ledger.extend(created)

    return created

# -------------------------------------------------------------------------------------------------------------------- #
#                                             the compensating rollback                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def roll_back(
        ports_manager: PortsManager,
        port_connections_manager: PortConnectionsManager,
        port_ids: list[int],
        connection_ids: list[int]) -> tuple[list[int], list[int]]:
    """
    Removes everything a failed batch created, connections first, and reports what survived

    Two bulk statements rather than one delete per row, then a **verification read** of each collection
    - so the residue is what is actually still stored rather than what the delete claimed. A rollback
    that reported success because its statement did not raise would be exactly as misleading as no
    rollback at all.

    Every failure here is swallowed on purpose: this already runs on an error path, and a rollback that
    raised would replace an honest "this was left behind" with a stack trace naming neither

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        port_ids (list[int]): The ports the batch created
        connection_ids (list[int]): The connections the batch created

    Returns:
        tuple[list[int], list[int]]: The port ids and connection ids that are still stored
    """
    if connection_ids:
        try:
            port_connections_manager.delete_many(
                {PortConnectionKey.PUBLIC_ID.value: {'$in': connection_ids}},
            )
        except Exception as err:
            LOGGER.error("[roll_back] Removing the created connections failed: %s", err, exc_info=True)

    if port_ids:
        try:
            ports_manager.delete_many({PortKey.PUBLIC_ID.value: {'$in': port_ids}})
        except Exception as err:
            LOGGER.error("[roll_back] Removing the created ports failed: %s", err, exc_info=True)

    return (
        _surviving(ports_manager, PortKey.PUBLIC_ID.value, port_ids),
        _surviving(port_connections_manager, PortConnectionKey.PUBLIC_ID.value, connection_ids),
    )


def _surviving(manager: GenericManager, id_key: str, public_ids: list[int]) -> list[int]:
    """
    Reads back which of the given rows are still stored

    A read the rollback cannot trust itself without: `delete_many` reports what it matched, not what is
    gone, and the whole point of the residue report is to be accurate about damage

    Args:
        manager (GenericManager): The manager owning the collection
        id_key (str): Name of the collection's public_id field
        public_ids (list[int]): The ids the rollback tried to remove

    Returns:
        list[int]: The ids still present, sorted; empty when the cleanup finished
    """
    if not public_ids:
        return []

    try:
        found: list[dict[str, Any]] = manager.find(criteria={id_key: {'$in': public_ids}})
    except Exception as err:
        # The verification itself failed, so nothing can be promised about the cleanup. Reporting every
        # id as residue is the honest answer: it sends somebody to look, which is what this is for
        LOGGER.error("[_surviving] Verifying the rollback failed: %s", err, exc_info=True)

        return sorted(public_ids)

    return sorted(row[id_key] for row in found if id_key in row)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the orchestration                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

#pylint: disable=R0913, R0917
def create_batch(
        ports_manager: PortsManager,
        port_connections_manager: PortConnectionsManager,
        object_id: int,
        preview: dict[str, Any],
        author_id: int,
        base_candidate: dict[str, Any] | None = None) -> BulkCreateResult:
    """
    Creates every port of a preview, pairs a panel's faces, and undoes it all if anything fails

    Runs from the PREVIEW rather than from the request, so what is written is exactly what the customer
    was shown - the preview and the creation cannot drift because there is only one generator.

    A standard device has one face and no connections. A patch panel has two faces of equal length -
    equal by construction, since one count drives both - and gets one INTERNAL connection per pair

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        object_id (int): public_id of the owner CmdbObject
        preview (dict[str, Any]): The preview whose names are to be created
        author_id (int): public_id of the CmdbUser creating the batch
        base_candidate (dict[str, Any] | None): The field values every port shares. Defaults to none

    Returns:
        BulkCreateResult: What was created, and - when something failed - what the rollback could not
            remove
    """
    faces: list[dict[str, Any]] = preview.get(PortPreviewKey.FACES.value, [])
    port_ids: list[int] = []
    connection_ids: list[int] = []

    face_port_ids: list[list[int]] = []

    try:
        # An explicit loop, not a comprehension: the ledger has to be complete at the moment a face
        # raises, and a comprehension would discard every face that had already finished
        for face in faces:
            face_port_ids.append(create_face_ports(
                ports_manager, object_id, face, author_id, base_candidate or {}, port_ids,
            ))

        # A panel is exactly the two-face case: its pairing is what the second face exists for
        if len(face_port_ids) == 2:
            create_internal_connections(
                port_connections_manager, face_port_ids[0], face_port_ids[1], author_id,
                connection_ids,
            )
    except Exception as err:
        LOGGER.error("[create_batch] Bulk creation failed after %s port(s): %s",
                     len(port_ids), err, exc_info=True)

        residual_ports, residual_connections = roll_back(
            ports_manager, port_connections_manager, port_ids, connection_ids,
        )

        return BulkCreateResult(
            port_ids=port_ids,
            connection_ids=connection_ids,
            error=str(err),
            residual_port_ids=residual_ports,
            residual_connection_ids=residual_connections,
        )

    return BulkCreateResult(
        port_ids=port_ids,
        connection_ids=connection_ids,
        error=None,
        residual_port_ids=[],
        residual_connection_ids=[],
    )
