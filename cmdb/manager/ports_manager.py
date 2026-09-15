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

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.ports_manager import (
    PORTS_MANAGER_ERRORS,
    PortsManagerDeleteError,
    PortsManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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

        Raises:
            PortsManagerInitError: If the PortsManager could not be initialised
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
        except (BaseManagerGetError, Exception) as err:
            raise PortsManagerGetError(str(err)) from err


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
        except (BaseManagerGetError, Exception) as err:
            raise PortsManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_ports_of_object(self, object_id: int) -> int:
        """
        Deletes every CmdbPort of one CmdbObject in one operation

        Used when the owner CmdbObject goes away. One statement rather than a per-port loop

        Args:
            object_id (int): public_id of the owner CmdbObject

        Raises:
            PortsManagerDeleteError: If the CmdbPorts could not be deleted

        Returns:
            int: The number of deleted ports
        """
        try:
            return self.delete_many({PortKey.OBJECT_ID.value: object_id}).deleted_count
        except (BaseManagerDeleteError, Exception) as err:
            raise PortsManagerDeleteError(str(err)) from err
