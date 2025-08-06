# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of APIProjection
"""
import logging
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIProjection - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class APIProjection:
    """
    ApiProjection is a wrapper for the api http parameters under `projection`.
    """
    def __init__(self, projection: dict | list = None):
        if isinstance(projection, list):
            projection = dict.fromkeys(projection, 1)
        self.projection = projection or {}
        self.__includes = None
        self.__has_includes = None
        self.__excludes = None
        self.__has_excludes = None

# ---------------------------------------------------- PROPERTIES ---------------------------------------------------- #

    @property
    def includes(self) -> list[str]:
        """
        Get all keys which includes (value set to 1)
        """
        if not self.__includes:
            self.__includes = APIProjection.__validate_inclusion(self.projection)

        return self.__includes


    @property
    def excludes(self) -> list[str]:
        """
        Get all keys which excludes (value set to 0)
        """
        if not self.__excludes:
            self.__excludes = APIProjection.__validate_inclusion(self.projection, match=0)

        return self.__excludes

# -------------------------------------------------- STATIC METHODS -------------------------------------------------- #

    @staticmethod
    def __validate_inclusion(projection: dict, match: int = 1) -> list[str]:
        """
        Validation helper function to check the projection inclusion
        
        Args:
            projection (dict): Projection parameters
            match (int): Matching value in dict or list. Must be 0 or 1

        Returns:
            list[str]: List of all keys with the matching parameters

        Raises:
            ValueError: If match is not 0 or 1
        """
        if match not in [0, 1]:
            raise ValueError('Projection parameter must be 0 or 1.')

        return [key for key, value in projection.items() if value == match]

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def has_includes(self) -> bool:
        """
        Has include values
        """
        if not self.__has_includes:
            self.__has_includes = len(self.includes) > 0

        return self.__has_includes


    def has_excludes(self) -> bool:
        """
        Has excludes values
        """
        if not self.__has_excludes:
            self.__has_excludes = len(self.excludes) > 0

        return self.__has_excludes
