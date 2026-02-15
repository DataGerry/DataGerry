# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Mapping module for associating data to specific memory areas, such as fields or attributes

This module provides a `MapEntry` class that allows you to create mappings where each entry consists of:
- A `name` (which can be any data type) representing the key or identifier of the mapping
- A `value` (which can also be any data type) representing the data associated with the `name`
- An optional set of configuration `options` that can be used to store additional metadata about the entry
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

class MapEntry:
    """
    Represents an entry in a mapping, where a name is associated with a value
    and additional options. This class encapsulates the mapping of data to 
    respective memory areas (e.g., fields)
    """
    def __init__(self, name: Any, value: Any, **options: dict):
        """
        Initialises the MapEntry

        Args:
            name (Any): The name or key associated with this mapping entry
            value (Any): The value or data associated with the name
            options (dict[str, Any]): Optional additional configuration options for this entry.
        """
        self.name: Any = name
        self.value: Any = value
        self.options: dict = options


    def get_name(self) -> Any:
        """
        Get the name of this MapEntry

        Returns:
            Any: The name associated with this MapEntry
        """
        return self.name


    def get_value(self) -> Any:
        """
        Get the value of this MapEntry

        Returns:
            Any: The value associated with this MapEntry
        """
        return self.value


    def has_option(self, option: dict) -> bool:
        """
        Check if the given option is present in the mapping entry's options

        Args:
            option (dict): A dictionary representing the option to check

        Returns:
            bool: True if the option is present in the mapping entry's options, otherwise False
        """
        return option.items() <= self.get_options().items()


    def get_options(self) -> dict:
        """
        Get the options associated with this mapping entry.

        Returns:
            dict: A dictionary of options associated with the entry.
        """
        return self.options
