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
Collection of system readers which loads configuration files and settings
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SystemReader - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SystemReader:
    """
    Base class for system readers
    """

    def get_value(self, name: str, section: str) -> Any:
        """
        Retrieve a specific value from a section

        Args:
            name (str): key name of value
            section (str): section identifier

        Returns:
            Any: The requested value if any
        """
        raise NotImplementedError


    def get_sections(self) -> list[str]:
        """
        Get all sections from config
        
        Returns:
            list: list of config names
        """
        raise NotImplementedError


    def get_all_values_from_section(self, section: str) -> dict:
        """
        Get a dict of all values in section
        
        Args:
            section (str): section key

        Returns:
            dict: Dict of all values inside a section
        """
        raise NotImplementedError
