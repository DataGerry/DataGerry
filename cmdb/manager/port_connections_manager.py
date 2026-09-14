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
Implementation of the PortConnectionsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.port_connection_model.cmdb_port_connection import CmdbPortConnection
from cmdb.models.port_connection_model.port_connection_constants import PortConnectionKey

from cmdb.errors.manager.port_connections_manager import (
    PORT_CONNECTIONS_MANAGER_ERRORS,
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerGetError,
    PortConnectionsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           PortConnectionsManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class PortConnectionsManager(GenericManager):
    """
    The PortConnectionsManager handles the interaction between the CmdbPortConnections-API and the
    database

    Every read here asks the same question - 'which connections touch these ports' - which is one
    indexed predicate against the plain multikey 'endpoints' index precisely because the two port ids
    share one array. The cardinality rules are NOT the manager's: no port in two cable connections,
    one internal connection per port and one cable CI per connection are all held by the collection's
    partial unique indexes, and the shape rules (sorted endpoints, no self-connection, no cable info
    on an INTERNAL link) by cmdb.framework.port.connection_validator

    `Extends`: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the PortConnectionsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None

        Raises:
            PortConnectionsManagerInitError: If the PortConnectionsManager could not be initialised
        """
        super().__init__(dbm, CmdbPortConnection, PORT_CONNECTIONS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_connections_of_port(self, port_id: int) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortConnection one CmdbPort takes part in

        A single indexed predicate on the array, which finds the port at either end - there is no 'a'
        side to also check, because the endpoints are one field. A panel port legitimately has two
        results: its cable and its internal pairing

        Args:
            port_id (int): public_id of the CmdbPort

        Raises:
            PortConnectionsManagerGetError: If the CmdbPortConnections could not be retrieved

        Returns:
            list[dict[str, Any]]: The port's connections, empty when it is free
        """
        try:
            return self.find(criteria={PortConnectionKey.ENDPOINTS.value: port_id})
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err


    def get_connection_of_port_by_type(self, port_id: int, connection_type: str) -> dict[str, Any] | None:
        """
        Retrieves the connection of one CmdbPort of one kind, if it has one

        The read behind the readable cardinality refusal: a port may hold at most one CABLE and at
        most one INTERNAL connection, so this answers 'is that slot taken'. It is NOT the guarantee -
        being a read followed by a write it cannot stop two concurrent requests; the two partial
        unique indexes on 'endpoints' are

        Args:
            port_id (int): public_id of the CmdbPort
            connection_type (str): The ConnectionType value to look for

        Raises:
            PortConnectionsManagerGetError: If the CmdbPortConnection could not be retrieved

        Returns:
            dict[str, Any] | None: The matching connection, or None when that slot is free
        """
        try:
            return self.get_one_by({
                PortConnectionKey.ENDPOINTS.value: port_id,
                PortConnectionKey.CONNECTION_TYPE.value: connection_type,
            })
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err


    def get_connection_by_cable_ci(self, cable_ci_id: int) -> dict[str, Any] | None:
        """
        Retrieves the connection claiming one cable CI, if any does

        One inventoried cable belongs to at most one connection. Like the read above this is the
        readable pre-check and not the guarantee, which is the partial unique index on 'cable_ci_id'

        Args:
            cable_ci_id (int): public_id of the CABLE SpecialType CmdbObject

        Raises:
            PortConnectionsManagerGetError: If the CmdbPortConnection could not be retrieved

        Returns:
            dict[str, Any] | None: The connection using that cable CI, or None when it is unused
        """
        try:
            return self.get_one_by({PortConnectionKey.CABLE_CI_ID.value: cable_ci_id})
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err


    def get_connections_by_cable_cis(self, cable_ci_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves the connections claiming any of the given Cable CIs

        The batched form of `get_connection_by_cable_ci`: the object-delete guard asks it once for a
        whole selection rather than once per candidate, so a bulk delete of 200 objects still costs
        one query. Served by the partial index on 'cable_ci_id', which is also why it reads through
        `find` like every other read here rather than through `get_many`: `get_many` always sorts by
        public_id, and a sort the caller did not ask for is a reason for the planner to leave the index
        this method is named after

        Args:
            cable_ci_ids (list[int]): public_ids of the CABLE SpecialType CmdbObjects to check

        Raises:
            PortConnectionsManagerGetError: If the CmdbPortConnections could not be retrieved

        Returns:
            list[dict[str, Any]]: The connections using any of those Cable CIs, empty when none do
        """
        if not cable_ci_ids:
            return []

        try:
            return self.find(criteria={PortConnectionKey.CABLE_CI_ID.value: {'$in': cable_ci_ids}})
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err


    def get_assigned_cable_ci_ids(self) -> list[int]:
        """
        Retrieves the public_ids of every Cable CI that some CmdbPortConnection already uses

        The complement of "unassigned": a Cable CI is free exactly when it is not in this list. One
        distinct query over the partial index on 'cable_ci_id', so no connection document is loaded.
        The criteria ask for the key's PRESENCE because `to_json` omits it rather than writing null,
        which is also what that partial index is filtered on

        Raises:
            PortConnectionsManagerGetError: If the lookup failed

        Returns:
            list[int]: The claimed Cable CI ids, empty when no connection names one
        """
        try:
            return [
                cable_ci_id
                for cable_ci_id in self.get_distinct(
                    PortConnectionKey.CABLE_CI_ID.value,
                    {PortConnectionKey.CABLE_CI_ID.value: {'$exists': True}},
                )
                if isinstance(cable_ci_id, int)
            ]
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err


    def get_connections_of_ports(self, port_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortConnection touching any of the given CmdbPorts

        One batched query for a whole page of ports, rather than one query per port. This is what the
        computed 'connected' flag is served by, so it stays a single round trip however many ports a
        response lists

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts

        Raises:
            PortConnectionsManagerGetError: If the CmdbPortConnections could not be retrieved

        Returns:
            list[dict[str, Any]]: The connections touching at least one of the ports, empty when none do
        """
        if not port_ids:
            return []

        try:
            return self.find(criteria={PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}})
        except Exception as err:
            raise PortConnectionsManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def replace_connection(self, public_id: int, document: dict[str, Any]) -> None:
        """
        Writes the cable information of one CmdbPortConnection, removing what the document omits

        NOT `update_item`, and the difference matters. `BaseManager.update` wraps its payload in
        `$set`, so a key the caller left out keeps whatever was stored - which is wrong here for one
        key in particular: 'cable_ci_id' is ABSENT rather than null when a connection names no cable
        CI (its unique index is filtered on the key's presence), so `$set` alone could never clear it
        and the connection would hold a cable CI the user had removed.

        The document is the connection's new cable information in full, since these routes take the
        whole object rather than a patch

        Args:
            public_id (int): public_id of the CmdbPortConnection to update
            document (dict[str, Any]): The fields to write. A missing 'cable_ci_id' is UNSET

        Raises:
            PortConnectionsManagerUpdateError: If the CmdbPortConnection could not be updated
        """
        update: dict[str, Any] = {'$set': document}

        if PortConnectionKey.CABLE_CI_ID.value not in document:
            update['$unset'] = {PortConnectionKey.CABLE_CI_ID.value: ''}

        try:
            self.update({PortConnectionKey.PUBLIC_ID.value: public_id}, update)
        except Exception as err:
            raise PortConnectionsManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_connections_of_ports(self, port_ids: list[int]) -> int:
        """
        Deletes every CmdbPortConnection touching any of the given CmdbPorts, in one operation

        Used when the ports themselves go away, so a connection can not outlive an endpoint. One
        statement rather than a per-port loop. The PEER port of each removed connection is simply free
        again - nothing about it is rewritten, because 'connected' is computed and never stored

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts being removed

        Raises:
            PortConnectionsManagerDeleteError: If the CmdbPortConnections could not be deleted

        Returns:
            int: The number of deleted connections
        """
        if not port_ids:
            return 0

        try:
            return self.delete_many(
                {PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}},
            ).deleted_count
        except Exception as err:
            raise PortConnectionsManagerDeleteError(str(err)) from err
