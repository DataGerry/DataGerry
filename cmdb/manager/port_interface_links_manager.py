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
Implementation of the PortInterfaceLinksManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.port_interface_link_model.cmdb_port_interface_link import CmdbPortInterfaceLink
from cmdb.models.port_interface_link_model.port_interface_link_constants import PortInterfaceLinkKey

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.port_interface_links_manager import (
    PORT_INTERFACE_LINKS_MANAGER_ERRORS,
    PortInterfaceLinksManagerDeleteError,
    PortInterfaceLinksManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                        PortInterfaceLinksManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class PortInterfaceLinksManager(GenericManager):
    """
    The PortInterfaceLinksManager handles the interaction between the CmdbPortInterfaceLinks-API and
    the database

    The reads come in two directions - a port's interfaces, and the links pointing into one object's
    interface rows - and each is served by one of the declared indexes. That a port is linked to the
    same interface row at most once is the unique index on the identity tuple, not this layer; whether
    the addressed row still exists is cmdb.framework.port.interface_links, because it is a question
    about a CmdbObject rather than about this collection

    `Extends`: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the PortInterfaceLinksManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None

        Raises:
            PortInterfaceLinksManagerInitError: If the PortInterfaceLinksManager could not be initialised
        """
        super().__init__(dbm, CmdbPortInterfaceLink, PORT_INTERFACE_LINKS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_links_of_port(self, port_id: int) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink of one CmdbPort

        The read the ports panel makes for a port's interface list. A port legitimately has several -
        a bond member, a stack of VLAN sub-interfaces - which is what makes the relationship N:M

        Args:
            port_id (int): public_id of the CmdbPort

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: The port's links, empty when it has none
        """
        try:
            return self.find(criteria={PortInterfaceLinkKey.PORT_ID.value: port_id})
        except (BaseManagerGetError, Exception) as err:
            raise PortInterfaceLinksManagerGetError(str(err)) from err


    def get_links_of_ports(self, port_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink of any of the given CmdbPorts

        One batched query for a whole page of ports rather than one per port - the same shape the
        computed `connected` flag uses, and what a later per-page interface projection would need

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: The links of those ports, empty when there are none
        """
        if not port_ids:
            return []

        try:
            return self.find(criteria={PortInterfaceLinkKey.PORT_ID.value: {'$in': port_ids}})
        except (BaseManagerGetError, Exception) as err:
            raise PortInterfaceLinksManagerGetError(str(err)) from err


    def get_links_of_interface_object(self, interface_object_id: int) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink pointing into one CmdbObject's interface rows

        The reverse direction - 'which ports reach the interfaces of this object' - and the read the
        dangling-link report groups by, since whether a row still exists is answered per object

        Args:
            interface_object_id (int): public_id of the CmdbObject holding the interface rows

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: The links pointing at that object, empty when there are none
        """
        try:
            return self.find(
                criteria={PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: interface_object_id},
            )
        except (BaseManagerGetError, Exception) as err:
            raise PortInterfaceLinksManagerGetError(str(err)) from err


    def get_all_links(self) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink in the installation

        Read by the dangling-link report alone, which is an explicit maintenance action rather than
        something a page load performs. The collection holds one document per port/interface pair, so
        it is bounded by how much cabling the customer has actually documented

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: Every link, empty when none exist
        """
        try:
            return self.find(criteria={})
        except (BaseManagerGetError, Exception) as err:
            raise PortInterfaceLinksManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_links_of_ports(self, port_ids: list[int]) -> int:
        """
        Deletes every CmdbPortInterfaceLink of the given CmdbPorts, in one operation

        Used when the ports themselves go away. Note the asymmetry with the INTERFACE side, and that it
        is deliberate: the port reference is hard - a link without its port is unreachable - while the
        interface reference is soft, so a vanished interface row leaves the link in place to be
        reported and repaired

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts being removed

        Raises:
            PortInterfaceLinksManagerDeleteError: If the CmdbPortInterfaceLinks could not be deleted

        Returns:
            int: The number of deleted links
        """
        if not port_ids:
            return 0

        try:
            return self.delete_many(
                {PortInterfaceLinkKey.PORT_ID.value: {'$in': port_ids}},
            ).deleted_count
        except (BaseManagerDeleteError, Exception) as err:
            raise PortInterfaceLinksManagerDeleteError(str(err)) from err
