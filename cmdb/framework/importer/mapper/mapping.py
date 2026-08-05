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
This module handles the mapping of data connections to respective memory areas, such as fields.
It provides functionality to manage mappings, retrieve mapped entries, and manipulate mappings dynamically
"""
from logging import Logger, getLogger
from typing import Iterator
from collections.abc import Iterable

from cmdb.framework.importer.mapper.map_entry import MapEntry
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    Mapping - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class Mapping(Iterable):
    """
    Handles mappings between data sources and their respective memory fields
    """
    def __init__(self, entries: list[MapEntry] | None = None) -> None:
        """
        Initializes a Mapping

        Args:
            entries (list[MapEntry] | None): List of MapEntry objects. Defaults to an empty list
        """
        self.__entries: list[MapEntry] = entries or []


    def __iter__(self) -> Iterator[MapEntry]:
        """
        Returns an iterator over the mapping entries
        
        Returns:
            Iterator[MapEntry]: An iterator over the stored entries
        """
        return iter(self.get_entries())


    def __len__(self) -> int:
        """
        Returns the number of mapping entries
        
        Returns:
            int: Number of entries in the mapping
        """
        return len(self.get_entries())

# ------------------------------------------------------ METHODS ----------------------------------------------------- #

    def get_entries(self) -> list[MapEntry]:
        """
        Retrieves all mapping entries
        
        Returns:
            list[MapEntry]: A list of MapEntry objects
        """
        return self.__entries


    def get_entries_with_option(self, query: dict) -> list[MapEntry]:
        """
        Retrieves mapping entries that match a given query
        
        Args:
            query (dict): A dictionary representing the search criteria
        
        Returns:
            list[MapEntry]: A list of MapEntry objects that match the query
        """
        return [entry for entry in self if entry.has_option(query)]


    def add_entry(self, entry: MapEntry) -> None:
        """
        Adds a new mapping entry
        
        Args:
            entry (MapEntry): The MapEntry object to be added
        """
        self.__entries.append(entry)


    def add_entries(self, entries: list[MapEntry]) -> None:
        """
        Adds multiple mapping entries
        
        Args:
            entries (list[MapEntry]): A list of MapEntry objects to be added
        """
        self.__entries.extend(entries)


    def remove_entry(self, entry: MapEntry) -> None:
        """
        Removes a mapping entry
        
        Args:
            entry (MapEntry): The MapEntry object to be removed
        """
        self.__entries.remove(entry)

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def generate_mapping_from_list(cls, map_list: list[dict]) -> "Mapping":
        """
        Generates a Mapping instance from a list of dictionaries
        
        Args:
            map_list (list[dict]): A list of dictionary representations of mappings
        
        Returns:
            Mapping: A Mapping instance with the provided entries
        """
        maps = cls()

        for mapper in map_list:
            maps.add_entry(MapEntry(**mapper))

        return maps
