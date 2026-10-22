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
Implementation of the PortsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.port_model.cmdb_port import CmdbPort
from cmdb.models.port_model.port_constants import PortKey

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.ports_manager import (
    PORTS_MANAGER_ERRORS,
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Read whole, MongoDB `_id` included: the database manager drops `_id` unless a projection is given, and a
# ledger snapshot must carry it so an undo re-inserts each port under its old identity
WHOLE_DOCUMENT: None = None

# The three keys that say which kind of device an object is, and which ports it holds
PORT_KIND_PROJECTION: dict[str, int] = {
    PortKey.PUBLIC_ID.value: 1,
    PortKey.OBJECT_ID.value: 1,
    PortKey.SIDE.value: 1,
    '_id': 0,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                PortsManager - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class PortsManager(GenericManager):
    """
    The PortsManager handles the interaction between the CmdbPorts-API and the database

    Plain CRUD on framework.ports, so GenericManager covers it whole. The rules a port has to satisfy
    are not the manager's: name uniqueness is the collection's unique index, and the write guards
    (the owner object exists, its type declares uses_ports, a select value is one its
    CmdbExtendableOption list offers) belong to the route layer's validator

    `Extends`: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the PortsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None
        """
        super().__init__(dbm, CmdbPort, PORTS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_ports_of_object(self, object_id: int) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPort of one CmdbObject, ordered the way the frontend lists them

        Sorted by port_number and then by name, so a port without a number still has a stable place.
        Served by the declared (object_id, port_number) index

        Args:
            object_id (int): public_id of the owner CmdbObject

        Raises:
            PortsManagerGetError: If the CmdbPorts could not be retrieved

        Returns:
            list[dict[str, Any]]: The object's ports, empty when it has none
        """
        try:
            return self.find(
                criteria={PortKey.OBJECT_ID.value: object_id},
                sort=[(PortKey.PORT_NUMBER.value, self.model.DAO_ASCENDING),
                      (PortKey.NAME.value, self.model.DAO_ASCENDING)],
            )
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err


    def get_ports_of_objects(self, object_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPort of several CmdbObjects in one query

        The read behind a view that draws more than one object at a time: asking per object would be
        one query per node. Ordered the way the frontend lists them - by owner, then port number, then
        name - so a caller can group without re-sorting

        Args:
            object_ids (list[int]): public_ids of the owner CmdbObjects; an empty list reads nothing

        Raises:
            PortsManagerGetError: If the CmdbPorts could not be retrieved

        Returns:
            list[dict[str, Any]]: The ports of those objects, empty when they have none
        """
        if not object_ids:
            return []

        try:
            return self.find(
                criteria={PortKey.OBJECT_ID.value: {'$in': object_ids}},
                sort=[(PortKey.OBJECT_ID.value, self.model.DAO_ASCENDING),
                      (PortKey.PORT_NUMBER.value, self.model.DAO_ASCENDING),
                      (PortKey.NAME.value, self.model.DAO_ASCENDING)],
            )
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err


    def get_ports_by_ids(self, port_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves several CmdbPorts by their public_ids in one query

        The read behind naming what a page of cables ends on: the far end of a connection is a port
        id, and the ports it names belong to other CmdbObjects. One indexed '$in' answers the whole
        page, where asking per port would be one query per cable

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts to read; an empty list reads nothing

        Raises:
            PortsManagerGetError: If the CmdbPorts could not be retrieved

        Returns:
            list[dict[str, Any]]: The ports that exist, in no guaranteed order
        """
        if not port_ids:
            return []

        try:
            return self.find(criteria={PortKey.PUBLIC_ID.value: {'$in': port_ids}})
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err


    def get_port_by_name(self, object_id: int, side: str, name: str) -> dict[str, Any] | None:
        """
        Retrieves the CmdbPort with the given name on one face of one CmdbObject

        The read behind the create/update pre-check that turns a duplicate name into a readable 400.
        It is NOT the guarantee - being a read followed by a write it cannot stop two concurrent
        requests; the unique (object_id, side, name) index is

        Args:
            object_id (int): public_id of the owner CmdbObject
            side (str): A PortSide value
            name (str): The port name to look for

        Raises:
            PortsManagerGetError: If the CmdbPort could not be retrieved

        Returns:
            dict[str, Any] | None: The matching port, or None when the name is free
        """
        try:
            return self.get_one_by({
                PortKey.OBJECT_ID.value: object_id,
                PortKey.SIDE.value: side,
                PortKey.NAME.value: name,
            })
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err

    def get_port_kinds_of_object(self, object_id: int) -> list[dict[str, Any]]:
        """
        Retrieves one CmdbObject's ports as `{public_id, object_id, side}` only

        The read behind the questions that need no more than that - which kind of device the object is, which
        port ids it holds - so a device with 96 ports does not load 96 whole documents to answer them

        Args:
            object_id (int): public_id of the owner CmdbObject

        Raises:
            PortsManagerGetError: If the CmdbPorts could not be retrieved

        Returns:
            list[dict[str, Any]]: The object's ports in that shape, empty when it has none
        """
        try:
            return self.find(criteria={PortKey.OBJECT_ID.value: object_id}, projection=PORT_KIND_PROJECTION)
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err


    def snapshot_ports(self, port_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves several CmdbPorts as stored, MongoDB `_id` included

        The snapshot a WriteLedger records before the ports are deleted, so an undo can put each back under its
        old identity

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts; an empty list reads nothing

        Raises:
            PortsManagerGetError: If the CmdbPorts could not be retrieved

        Returns:
            list[dict[str, Any]]: The whole port documents that exist
        """
        if not port_ids:
            return []

        try:
            return self.find(criteria={PortKey.PUBLIC_ID.value: {'$in': port_ids}}, projection=WHOLE_DOCUMENT)
        except BaseManagerGetError as err:
            raise PortsManagerGetError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_ports(self, port_ids: list[int], values: dict[str, Any]) -> None:
        """
        Writes the same field values to several CmdbPorts, in one operation

        The bulk edit: the values are identical for every port of the selection by definition

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts to update
            values (dict[str, Any]): The field values to set

        Raises:
            PortsManagerUpdateError: If the CmdbPorts could not be updated
        """
        if not port_ids:
            return

        try:
            self.update_many(criteria={PortKey.PUBLIC_ID.value: {'$in': port_ids}}, update=values)
        except BaseManagerUpdateError as err:
            raise PortsManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_ports_by_ids(self, port_ids: list[int]) -> int:
        """
        Deletes several CmdbPorts by their public_ids, in one operation

        The last step of a port delete - single, bulk or the owner object's - once the ports' connections and
        interface links are gone

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts to delete

        Raises:
            PortsManagerDeleteError: If the CmdbPorts could not be deleted

        Returns:
            int: The number of deleted ports
        """
        if not port_ids:
            return 0

        try:
            return self.delete_many({PortKey.PUBLIC_ID.value: {'$in': port_ids}}).deleted_count
        except BaseManagerDeleteError as err:
            raise PortsManagerDeleteError(err) from err
