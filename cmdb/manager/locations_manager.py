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
This module contains the implementation of the LocationsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.framework.results import IterationResult

from cmdb.errors.models.cmdb_location import CmdbLocationToJsonError
from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.locations_manager import (
    LocationsManagerInitError,
    LocationsManagerInsertError,
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerDeleteError,
    LocationsManagerIterationError,
    LocationsManagerChildrenError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

class LocationsManager(BaseManager):
    """
    The LocationsManager manages the interaction between CmdbLocations and the database

    Extends: BaseManager
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection for the LocationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            LocationsManagerInitError: If the LocationsManager could not be initialised
        """
        try:
            super().__init__(CmdbLocation.COLLECTION, dbm, database)
        except Exception as err:
            raise LocationsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_location(self, location: CmdbLocation | dict) -> int:
        """
        Insert a CmdbLocation into the database

        Args:
            location (CmdbLocation | dict): Raw data of the CmdbLocation

        Raises:
            LocationsManagerInsertError: When a CmdbLocation could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbLocation
        """
        try:
            if isinstance(location, CmdbLocation):
                location = CmdbLocation.to_json(location)

            return self.insert(location)
        except (BaseManagerInsertError, CmdbLocationToJsonError) as err:
            raise LocationsManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbLocation]:
        """
        Retrieves multiple CmdbLocations

        Args:
            builder_params (BuilderParameters): Filter for which CmdbLocations should be retrieved

        Raises:
            LocationsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbRelation]: All CmdbLocations matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            result: IterationResult[CmdbLocation] = IterationResult(aggregation_result, total, CmdbLocation)

            return result
        except BaseManagerIterationError as err:
            raise LocationsManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerIterationError(err) from err


    def get_location(self, public_id: int) -> dict | None:
        """
        Retrieves a CmdbLocation from the database

        Args:
            public_id (int): public_id of the CmdbLocation

        Raises:
            LocationsManagerGetError: When a CmdbLocation could not be retrieved

        Returns:
            dict | None: A dictionary representation of the CmdbLocation if successful, otherwise None
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(err) from err


    def get_location_for_object(self, object_id: int) -> dict[str, Any] | None:
        """
        Retrieves a single CmdbLocation for the given CmdbObject's public_id

        Args:
            object_id (int): public_id of the CmdbObject

        Raises:
            LocationsManagerGetError: If CmdbLocation could not be retrieved

        Returns:
            dict[str, Any] | None: The requested CmdbLocation as dict if found, else None
        """
        try:
            return self.get_one_by({'object_id':object_id})
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err


    def get_locations_by(self, **requirements: dict) -> list[CmdbLocation]:
        """
        Retrieves all CmdbLocations matching the key-value pairs

        Args:
            requirements (dict): Filter for CmdbLocations

        Raises:
            LocationsManagerGetError: If CmdbLocation could not be retrieved

        Returns:
            list[CmdbLocation]: All CmdbLocations matching the requirements
        """
        try:
            locations_list: list[CmdbLocation] = []

            locations: list[dict[str, Any]] = self.get_many(**requirements)

            for location in locations:
                locations_list.append(CmdbLocation.from_data(location))

            return locations_list
        except Exception as err:
            LOGGER.error("[get_locations_by] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_all_locations_excluding_root(self) -> list[dict[str, Any]]:
        """
        Returns all locations except the root (public_id = 1)
        """
        try:
            build_params = BuilderParameters([{"$match": {"public_id": {"$gt": 1}}}])

            iteration_result: IterationResult[CmdbLocation] = self.iterate(build_params)

            return [location_.__dict__ for location_ in iteration_result.results]
        except Exception as err:
            LOGGER.error("[get_all_locations_excluding_root] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_all_children(
            self,
            public_id: int,
            all_locations: list[dict[str,Any]],
            visited: set = None
        ) -> list[dict[str, Any]]:
        """
        Retrieves all children for a given CmdbLocation with the public_id

        Args:
            public_id (int): public_id of the parent CmdbLocation
            all_locations (list[dict[str,Any]]): all CmdbLocations
            visited (set): Set of already visited public_ids

        Returns:
            list[dict[str, Any]]: Returns all child CmdbLocations
        """
        try:
            if visited is None:
                visited = set()

            # Add the current public_id to the visited set to avoid infinite recursion
            visited.add(public_id)

            # Initialize the list of children with direct children
            children: list[dict[str, Any]] = [location for location in all_locations if location['parent'] == public_id]

            # Now recursively find and add all children of each direct child, but skip already visited ones
            for child in children[:]:  # Iterate over a copy of the list to avoid modifying it during iteration
                if child['public_id'] not in visited:
                    children.extend(self.get_all_children(child['public_id'], all_locations, visited))

            return children
        except Exception as err:
            LOGGER.error("[get_all_children] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerChildrenError(str(err)) from err


    def get_child_locations_object_ids(self, public_id: int) -> list[int]:
        """TODO: document"""
        target_location = self.get_location_for_object(public_id)

        if not target_location:
            return []

        all_locations: list[dict[str, Any]] = self.get_all_locations_excluding_root()
        all_children: list[dict[str, Any]] = self.get_all_children(target_location['public_id'], all_locations)

        if not all_children:
            return []

        childen_public_ids: list[int] = [
            child["object_id"]
            for child in all_children
            if child.get("object_id") is not None
        ]

        return childen_public_ids

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_location(self, object_id:int, data: CmdbLocation | dict, per_object: bool = True) -> None:
        """
        Updates a CmdbLocation in the database

        Args:
            object_id (int): object_id of the CmdbLocation which should be updated
            data: (CmdbLocation | dict): The new data for the CmdbLocation

        Raises:
            LocationsManagerUpdateError: When the update operation fails
        """
        try:
            if isinstance(data, CmdbLocation):
                data = CmdbLocation.to_json(data)

            update_key: str = 'object_id' if per_object else 'public_id'

            self.update({update_key: object_id}, data)
        except Exception as err:
            LOGGER.error("[update_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerUpdateError(str(err)) from err


    def update_locations_by_type(self, type_id: int, data: dict[str, Any]) -> None:
        """
        Updates all CmdbLocations of the provided CmdbTypes public_id

        Args:
            type_id (int): public_id of CmdbType for which the CmdbLocations should be updated
            data (dict[str, Any]): the data which should be applied

        Raises:
            LocationsManagerUpdateError: When the Update-Operation fails
        """
        try:
            if not data:
                LOGGER.error("No data provided to [update_locations_by_type] therefore no update executed!")
                return

            self.update_many(criteria={"type_id": type_id}, update=data)
        except BaseManagerUpdateError as err:
            raise LocationsManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_location(self, public_id: int) -> bool:
        """
        Deletes a CmdbLocation from the database

        Args:
            public_id (int): public_id of the CmdbLocation which should be deleted

        Raises:
            LocationsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete({'public_id':public_id})
        except BaseManagerDeleteError as err:
            raise LocationsManagerDeleteError(str(err)) from err


    def delete_locations(self, locations: list[dict[str, Any]]) -> None:
        """
        Deletes all given locations

        Args:
            public_ids (list[dict[str, Any]]): list of CmdbLocations which should be deleted
        """
        try:
            location_ids: list[int] = [location['public_id'] for location in locations]
            self.delete_many_raw({"public_id": {"$in": location_ids}})
        except BaseManagerDeleteError as err:
            raise LocationsManagerDeleteError(str(err)) from err
