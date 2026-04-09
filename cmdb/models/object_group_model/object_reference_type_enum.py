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
Implementation of ObjectReferenceType enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectReferenceType(str, Enum):
    """
    Enumeration of available reference types for CmdbObjects.

    This enumeration defines the different modes of referencing objects in the system. 
    Each reference type corresponds to how a CmdbObject or CmdbObjectGroup is linked or identified.

    Attributes:
        OBJECT (str): A reference to a single CmdbObject
        OBJECT_GROUP (str): A reference to a CmdbObjectGroup, which is a collection of CmdbObjects
    """
    OBJECT = 'OBJECT'
    OBJECT_GROUP = 'OBJECT_GROUP'


    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a valid ObjectReferenceType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing ObjectReferenceType, False otherwise
        """
        return value in ObjectReferenceType.__members__
