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
import re
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.framework.results import IterationResult

from cmdb.database.predefined_data.predefined_data_constants import LocationKey, RootLocationDefault

from cmdb.errors.manager import (
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

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None):
        """
        Set the database connection for the LocationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE

        Raises:
            LocationsManagerInitError: If the LocationsManager could not be initialised
        """
        try:
            super().__init__(CmdbLocation.COLLECTION, dbm, database)
        except Exception as err:
            raise LocationsManagerInitError(str(err)) from err

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
        except Exception as err:
            LOGGER.error("[insert_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerInsertError(str(err)) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbLocation]:
        """
        Retrieves multiple CmdbLocations

        Args:
            builder_params (BuilderParameters): Filter for which CmdbLocations should be retrieved

        Raises:
            LocationsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbLocation]: All CmdbLocations matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            result: IterationResult[CmdbLocation] = IterationResult(aggregation_result, total, CmdbLocation)

            return result
        except BaseManagerIterationError as err:
            raise LocationsManagerIterationError(str(err)) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerIterationError(str(err)) from err


    def get_location(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbLocation from the database

        Args:
            public_id (int): public_id of the CmdbLocation

        Raises:
            LocationsManagerGetError: When a CmdbLocation could not be retrieved

        Returns:
            dict[str, Any] | None: A dictionary representation of the CmdbLocation if successful, otherwise None
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err


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


    def get_locations_by(self, **requirements: Any) -> list[CmdbLocation]:
        """
        Retrieves all CmdbLocations matching the key-value pairs

        Args:
            **requirements (Any): Key-value pairs used to filter the CmdbLocations

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


    def get_all_descendant_locations(self, public_id: int) -> list[dict[str, Any]]:
        """
        Retrieves every descendant CmdbLocation beneath the given CmdbLocation

        Resolves the full subtree in a single ``$graphLookup`` aggregation (following
        ``parent`` -> ``public_id`` edges) instead of loading the whole collection and walking
        it in Python. ``$graphLookup`` detects cycles internally, so a malformed parent chain
        cannot cause infinite recursion. Requires MongoDB 3.4+ (well within the 7.0 floor)

        Args:
            public_id (int): public_id of the CmdbLocation whose descendants should be retrieved

        Raises:
            LocationsManagerChildrenError: If the descendant CmdbLocations could not be retrieved

        Returns:
            list[dict[str, Any]]: All descendant CmdbLocations (the location itself is excluded)
        """
        try:
            pipeline: list[dict[str, Any]] = [
                {"$match": {"public_id": public_id}},
                {
                    "$graphLookup": {
                        "from": CmdbLocation.COLLECTION,
                        "startWith": "$public_id",
                        "connectFromField": "public_id",
                        "connectToField": "parent",
                        "as": "descendants",
                    }
                },
                {"$project": {"_id": 0, "descendants": 1}},
            ]

            result: list[dict[str, Any]] = list(self.aggregate(pipeline))

            if not result:
                return []

            return result[0].get("descendants", [])
        except BaseManagerIterationError as err:
            raise LocationsManagerChildrenError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_all_descendant_locations] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerChildrenError(str(err)) from err


    def location_has_children(self, public_id: int) -> bool:
        """
        Checks whether a CmdbLocation has any direct child CmdbLocations

        Args:
            public_id (int): public_id of the CmdbLocation to check

        Raises:
            LocationsManagerGetError: If the child count could not be retrieved

        Returns:
            bool: True if at least one CmdbLocation has this location as its parent
        """
        try:
            return self.count_documents({LocationKey.PARENT: public_id}) > 0
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err


    def get_parents_with_children(self, parent_ids: list[int]) -> set[int]:
        """
        Determines which of the given CmdbLocations have at least one direct child

        Resolves the has-children hint for a whole tree level in a single grouped aggregation
        (``$match`` on the candidate parents, then ``$group`` by parent) instead of one count per
        node, so a lazily-expanded tree level stays a single query

        Args:
            parent_ids (list[int]): public_ids of the CmdbLocations to test for children

        Raises:
            LocationsManagerGetError: If the grouped lookup could not be executed

        Returns:
            set[int]: The subset of parent_ids that have at least one direct child location
        """
        if not parent_ids:
            return set()

        pipeline: list[dict[str, Any]] = [
            {"$match": {LocationKey.PARENT.value: {"$in": parent_ids}}},
            {"$group": {"_id": f"${LocationKey.PARENT.value}"}},
        ]

        try:
            return {doc["_id"] for doc in self.aggregate(pipeline)}
        except Exception as err:
            LOGGER.error("[get_parents_with_children] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def search_locations_with_ancestors(self, query: str) -> list[dict[str, Any]]:
        """
        Finds locations whose name matches the query and returns them plus their ancestor chains

        Reproduces the location tree's search on the backend: a case-insensitive, literal-substring
        match on the stored location ``name`` (regex metacharacters in the query are escaped so it
        stays a literal substring). Each match is returned together with every ancestor up to - but
        excluding - the synthetic root, resolved in a single ``$graphLookup`` (parent -> public_id)
        so the ancestor paths cost one aggregation instead of a walk per match. The flat,
        de-duplicated result (sorted by public_id) is meant to be assembled into a pruned forest by
        build_location_forest: non-matching descendants of a match are intentionally absent.
        Requires MongoDB 3.4+ (well within the 7.0 floor)

        Args:
            query (str): The search string; an empty/whitespace query yields no matches

        Raises:
            LocationsManagerGetError: If the search aggregation fails

        Returns:
            list[dict[str, Any]]: matching locations + their ancestors, flat and de-duplicated
        """
        if not query.strip():
            return []

        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    LocationKey.NAME.value: {"$regex": re.escape(query), "$options": "i"},
                    LocationKey.PUBLIC_ID.value: {"$gt": RootLocationDefault.PUBLIC_ID},
                }
            },
            {
                "$graphLookup": {
                    "from": CmdbLocation.COLLECTION,
                    "startWith": f"${LocationKey.PARENT.value}",
                    "connectFromField": LocationKey.PARENT.value,
                    "connectToField": LocationKey.PUBLIC_ID.value,
                    "as": "ancestors",
                }
            },
        ]

        try:
            matches: list[dict[str, Any]] = list(self.aggregate(pipeline))
        except BaseManagerIterationError as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[search_locations_with_ancestors] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err

        # collapse every match + its ancestors into a de-duplicated set, dropping the synthetic root
        collected: dict[int, dict[str, Any]] = {}

        for match in matches:
            ancestors: list[dict[str, Any]] = match.pop("ancestors", [])

            for location in [match, *ancestors]:
                public_id: int = location[LocationKey.PUBLIC_ID.value]

                if public_id == RootLocationDefault.PUBLIC_ID or public_id in collected:
                    continue

                collected[public_id] = location

        return sorted(collected.values(), key=lambda location: location[LocationKey.PUBLIC_ID.value])


    def get_locations_on_path_to(self, public_id: int) -> list[dict[str, Any]]:
        """
        Retrieves the location tree expanded along the ancestor path of a single CmdbLocation

        Powers the location picker's "open to the current selection" case: given a target location
        (the value stored in an object's location field), returns the flat set of all locations
        needed to render the tree already expanded down to that target - every ROOT location plus
        every direct child of each ancestor on the path from the root to the target (i.e. the full
        set of siblings at each level along the path, so the user keeps sideways context). The
        target itself and its own siblings are included (they are the deepest expanded level); the
        target's own children are NOT - like the rest of the lazy tree they load on demand via
        get_locations_by.

        The ancestor chain is resolved in a single ``$graphLookup`` (parent -> public_id); the
        sibling levels are then one ``$in`` query over {root} + {ancestors}. Returns an empty list
        when the target does not exist. Requires MongoDB 3.4+ (well within the 7.0 floor)

        Args:
            public_id (int): public_id of the target CmdbLocation to expand the tree to

        Raises:
            LocationsManagerGetError: If the path/level aggregation fails

        Returns:
            list[dict[str, Any]]: flat, de-duplicated list of every root location plus all direct
                children of each ancestor on the path to the target (which includes the target and
                its siblings); empty when the target does not exist
        """
        ancestor_pipeline: list[dict[str, Any]] = [
            {"$match": {LocationKey.PUBLIC_ID.value: public_id}},
            {
                "$graphLookup": {
                    "from": CmdbLocation.COLLECTION,
                    "startWith": f"${LocationKey.PARENT.value}",
                    "connectFromField": LocationKey.PARENT.value,
                    "connectToField": LocationKey.PUBLIC_ID.value,
                    "as": "ancestors",
                }
            },
        ]

        try:
            matches: list[dict[str, Any]] = list(self.aggregate(ancestor_pipeline))

            # Target does not exist -> nothing to expand to
            if not matches:
                return []

            ancestors: list[dict[str, Any]] = matches[0].get("ancestors", [])

            # The parents whose direct children make up the expanded levels: the synthetic root plus
            # every ancestor of the target (the synthetic root is excluded from the ancestor chain)
            expand_parents: set[int] = {RootLocationDefault.PUBLIC_ID}
            expand_parents |= {
                ancestor[LocationKey.PUBLIC_ID.value]
                for ancestor in ancestors
                if ancestor[LocationKey.PUBLIC_ID.value] != RootLocationDefault.PUBLIC_ID
            }

            # One $in over all sibling levels at once (children of the root + of each ancestor)
            return self.get_many(**{LocationKey.PARENT.value: {"$in": list(expand_parents)}})
        except (BaseManagerGetError, BaseManagerIterationError) as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_locations_on_path_to] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_location(self, object_id: int, data: CmdbLocation | dict) -> None:
        """
        Updates the CmdbLocation linked to the given CmdbObject

        Args:
            object_id (int): object_id of the CmdbLocation which should be updated
            data (CmdbLocation | dict): The new data for the CmdbLocation

        Raises:
            LocationsManagerUpdateError: When the update operation fails
        """
        try:
            if isinstance(data, CmdbLocation):
                data = CmdbLocation.to_json(data)

            self.update({'object_id': object_id}, data)
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

    def _reparent_children_to_grandparent(self, public_id: int) -> None:
        """
        Re-parents the direct children of a CmdbLocation onto that location's own parent

        Looks up the location's ``parent`` and points every CmdbLocation currently parented to
        ``public_id`` at it, in a single ``update_many`` (cost independent of the number of
        children). A no-op when the location does not exist or has no children. Called by
        :meth:`delete_location` so a deleted node's subtree is promoted one level instead of
        being orphaned

        Args:
            public_id (int): public_id of the CmdbLocation whose children should be promoted

        Raises:
            BaseManagerGetError: If the location lookup fails
            BaseManagerUpdateError: If the re-parenting update fails
        """
        location: dict[str, Any] | None = self.get_one_by({LocationKey.PUBLIC_ID.value: public_id})

        if not location:
            return

        self.update_many(
            criteria={LocationKey.PARENT.value: public_id},
            update={LocationKey.PARENT.value: location[LocationKey.PARENT.value]},
        )


    def delete_location(self, public_id: int) -> bool:
        """
        Deletes a CmdbLocation from the database, promoting its direct children

        Before the location is removed, every CmdbLocation that has it as ``parent`` is re-parented
        onto the deleted location's own parent (its grandparent). This keeps the location tree
        connected: the deleted node's subtree simply shifts up one level rather than being orphaned

        Args:
            public_id (int): public_id of the CmdbLocation which should be deleted

        Raises:
            LocationsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            self._reparent_children_to_grandparent(public_id)

            return self.delete({LocationKey.PUBLIC_ID.value: public_id})
        except (BaseManagerGetError, BaseManagerUpdateError, BaseManagerDeleteError) as err:
            raise LocationsManagerDeleteError(str(err)) from err
