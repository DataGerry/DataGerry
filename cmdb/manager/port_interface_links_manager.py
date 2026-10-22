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
from cmdb.models.port_interface_link_model.port_interface_link_constants import (
    INTERFACE_REFERENCE_KEYS,
    PortInterfaceLinkKey,
)

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.port_interface_links_manager import (
    PORT_INTERFACE_LINKS_MANAGER_ERRORS,
    PortInterfaceLinksManagerDeleteError,
    PortInterfaceLinksManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Read whole, MongoDB `_id` included: the database manager drops `_id` unless a projection is given, and a
# ledger snapshot must carry it so an undo re-inserts each link under its old identity
WHOLE_DOCUMENT: None = None

# What decides whether a link dangles: its id and the interface row it addresses
LINK_REFERENCE_PROJECTION: dict[str, int] = {
    PortInterfaceLinkKey.PUBLIC_ID.value: 1,
    **{key.value: 1 for key in INTERFACE_REFERENCE_KEYS},
    '_id': 0,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                        PortInterfaceLinksManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class PortInterfaceLinksManager(GenericManager):
    """
    The PortInterfaceLinksManager handles the interaction between the CmdbPortInterfaceLinks-API and
    the database

    The reads ask for a port's interfaces (served by the declared port index), for links by id, and - for the
    dangling-link report - for every link's interface row address. That a port is linked to the
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
        except BaseManagerGetError as err:
            raise PortInterfaceLinksManagerGetError(err) from err


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
        except BaseManagerGetError as err:
            raise PortInterfaceLinksManagerGetError(err) from err


    def get_all_link_references(self) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink in the installation, as its public_id and interface row address only

        The first read of the dangling-link report: whether a link dangles is decided by the row it addresses
        alone, so the whole collection is scanned for those four keys and only the dangling links are read in
        full afterwards (`get_links_by_ids`). The report is an explicit maintenance action, bounded by how much
        cabling the customer has documented

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: Every link as ``{public_id, interface_object_id, interface_section_id,
                interface_multi_data_id}``, empty when none exist
        """
        try:
            return self.find(projection=LINK_REFERENCE_PROJECTION)
        except BaseManagerGetError as err:
            raise PortInterfaceLinksManagerGetError(err) from err


    def get_links_by_ids(self, link_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves several CmdbPortInterfaceLinks by their public_ids in one query

        Args:
            link_ids (list[int]): public_ids of the links; an empty list reads nothing

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: The links that exist, in no guaranteed order
        """
        if not link_ids:
            return []

        try:
            return self.find(criteria={PortInterfaceLinkKey.PUBLIC_ID.value: {'$in': link_ids}})
        except BaseManagerGetError as err:
            raise PortInterfaceLinksManagerGetError(err) from err


    def snapshot_links_of_ports(self, port_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbPortInterfaceLink of the given CmdbPorts as stored, MongoDB `_id` included

        The snapshot a WriteLedger records before the links are deleted with their ports, so an undo can put
        each back under its old identity

        Args:
            port_ids (list[int]): public_ids of the CmdbPorts; an empty list reads nothing

        Raises:
            PortInterfaceLinksManagerGetError: If the CmdbPortInterfaceLinks could not be retrieved

        Returns:
            list[dict[str, Any]]: The whole link documents, empty when the ports hold none
        """
        if not port_ids:
            return []

        try:
            return self.find(
                criteria={PortInterfaceLinkKey.PORT_ID.value: {'$in': port_ids}}, projection=WHOLE_DOCUMENT,
            )
        except BaseManagerGetError as err:
            raise PortInterfaceLinksManagerGetError(err) from err

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
        except BaseManagerDeleteError as err:
            raise PortInterfaceLinksManagerDeleteError(err) from err
