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
Implementation of the RackMountsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.rack_model.cmdb_rack_mount import CmdbRackMount
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey

from cmdb.errors.manager.rack_mounts_manager import (
    RACK_MOUNTS_MANAGER_ERRORS,
    RackMountsManagerGetError,
    RackMountsManagerDeleteError,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             RackMountsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RackMountsManager(GenericManager):
    """
    The RackMountsManager handles the interaction between the CmdbRackMounts-API and the database

    `Extends`: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the RackMountsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None

        Raises:
            RackMountsManagerInitError: If the RackMountsManager could not be initialised
        """
        super().__init__(dbm, CmdbRackMount, RACK_MOUNTS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_mount_of_object(self, object_id: int) -> dict[str, Any] | None:
        """
        Retrieves the CmdbRackMount of a CmdbObject, if it is mounted anywhere

        An object belongs to at most one rack (enforced by the unique index on 'object_id'), so this
        answers "where is this object?" with a single document

        Args:
            object_id (int): public_id of the CmdbObject

        Raises:
            RackMountsManagerGetError: If the CmdbRackMount could not be retrieved

        Returns:
            dict[str, Any] | None: The mount as dict if the object is mounted, else None
        """
        try:
            return self.get_one_by({RackMountKey.OBJECT_ID.value: object_id})
        except BaseManagerGetError as err:
            raise RackMountsManagerGetError(str(err)) from err


    def get_mounts_of_rack(self, rack_id: int, area: str | None = None) -> list[dict[str, Any]]:
        """
        Retrieves every CmdbRackMount of a rack, optionally limited to one area

        Served by the compound (rack_id, area) index. Returns raw dicts rather than model instances
        because every caller either serialises them straight out or reads their geometry

        Args:
            rack_id (int): public_id of the Rack CmdbObject
            area (str | None): A RackArea value to filter by; None returns every area

        Raises:
            RackMountsManagerGetError: If the CmdbRackMounts could not be retrieved

        Returns:
            list[dict[str, Any]]: The rack's mounts, empty when the rack holds nothing
        """
        criteria: dict[str, Any] = {RackMountKey.RACK_ID.value: rack_id}

        if area is not None:
            criteria[RackMountKey.AREA.value] = area

        try:
            return self.find(criteria=criteria)
        except Exception as err:
            raise RackMountsManagerGetError(str(err)) from err


    def get_mounts_in_areas(self, rack_id: int, areas: set[str]) -> list[dict[str, Any]]:
        """
        Retrieves a rack's mounts across several areas in one read

        Used by the overlap check, which has to look at every area a placement competes with (a
        FULL_DEPTH mount blocks the front AND the back), and must not do one query per area

        Args:
            rack_id (int): public_id of the Rack CmdbObject
            areas (set[str]): The RackArea values to include; an empty set returns nothing

        Raises:
            RackMountsManagerGetError: If the CmdbRackMounts could not be retrieved

        Returns:
            list[dict[str, Any]]: The mounts in those areas
        """
        if not areas:
            return []

        try:
            return self.find(criteria={
                RackMountKey.RACK_ID.value: rack_id,
                RackMountKey.AREA.value: {'$in': sorted(areas)},
            })
        except Exception as err:
            raise RackMountsManagerGetError(str(err)) from err


    def get_next_position(self, rack_id: int, area: str) -> int:
        """
        Returns the position index to append a mount at the end of an ordered area

        The side lists and the unassigned bucket have no geometry to sort by, so their order is an
        explicit index. A new member is appended, which means one past the highest index in use

        Args:
            rack_id (int): public_id of the Rack CmdbObject
            area (str): The RackArea value of the ordered area

        Raises:
            RackMountsManagerGetError: If the existing positions could not be read

        Returns:
            int: The next free position, 0 when the area is empty
        """
        mounts: list[dict[str, Any]] = self.get_mounts_of_rack(rack_id, area)

        positions: list[int] = [
            mount[RackMountKey.POSITION.value]
            for mount in mounts
            if isinstance(mount.get(RackMountKey.POSITION.value), int)
        ]

        return max(positions) + 1 if positions else 0


    def count_mounts_of_rack(self, rack_id: int) -> int:
        """
        Counts how many CmdbObjects are members of a rack, placed or not

        Args:
            rack_id (int): public_id of the Rack CmdbObject

        Raises:
            RackMountsManagerGetError: If the count failed

        Returns:
            int: The number of mounts belonging to the rack
        """
        try:
            return self.count_documents({RackMountKey.RACK_ID.value: rack_id})
        except Exception as err:
            raise RackMountsManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_mounts_of_rack(self, rack_id: int) -> int:
        """
        Deletes every CmdbRackMount of a rack in one operation

        Used when the Rack CmdbObject itself goes away: the mounted objects survive, only their
        membership is removed. One statement rather than a per-mount loop

        Args:
            rack_id (int): public_id of the Rack CmdbObject

        Raises:
            RackMountsManagerDeleteError: If the CmdbRackMounts could not be deleted

        Returns:
            int: The number of deleted mounts
        """
        try:
            return self.delete_many({RackMountKey.RACK_ID.value: rack_id}).deleted_count
        except (BaseManagerDeleteError, Exception) as err:
            raise RackMountsManagerDeleteError(str(err)) from err


    def delete_mount_of_object(self, object_id: int) -> int:
        """
        Deletes the CmdbRackMount of a CmdbObject, if it has one

        Used when the mounted object itself is deleted, so no mount is left pointing at a gone object

        Args:
            object_id (int): public_id of the CmdbObject

        Raises:
            RackMountsManagerDeleteError: If the CmdbRackMount could not be deleted

        Returns:
            int: The number of deleted mounts (0 or 1)
        """
        try:
            return self.delete_many({RackMountKey.OBJECT_ID.value: object_id}).deleted_count
        except (BaseManagerDeleteError, Exception) as err:
            raise RackMountsManagerDeleteError(str(err)) from err

# ------------------------------------------------- GENERAL FUNCTIONS ------------------------------------------------ #

    def is_object_mounted(self, object_id: int, exclude_mount_id: int | None = None) -> bool:
        """
        Reports whether a CmdbObject already belongs to some rack

        Lets the mount routes reject a second membership with a readable 400 instead of surfacing the
        unique index's duplicate-key error. 'exclude_mount_id' is for an update, where the mount being
        changed is obviously allowed to be the one holding the object

        Args:
            object_id (int): public_id of the CmdbObject
            exclude_mount_id (int | None): public_id of a CmdbRackMount to ignore

        Raises:
            RackMountsManagerGetError: If the lookup failed

        Returns:
            bool: True when another mount already holds this object
        """
        existing: dict[str, Any] | None = self.get_mount_of_object(object_id)

        if existing is None:
            return False

        return existing.get(RackMountKey.PUBLIC_ID.value) != exclude_mount_id


    def get_unassigned_mounts(self, rack_id: int) -> list[dict[str, Any]]:
        """
        Retrieves the rack members that carry no placement

        Convenience wrapper over get_mounts_of_rack for the UNASSIGNED bucket - the objects assigned
        to the rack but not placed in it, including everything a height shrink displaced

        Args:
            rack_id (int): public_id of the Rack CmdbObject

        Raises:
            RackMountsManagerGetError: If the CmdbRackMounts could not be retrieved

        Returns:
            list[dict[str, Any]]: The unplaced members of the rack
        """
        return self.get_mounts_of_rack(rack_id, RackArea.UNASSIGNED.value)
