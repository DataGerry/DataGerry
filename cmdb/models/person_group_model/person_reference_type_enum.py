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
Implementation of PersonReferenceType enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class PersonReferenceType(str, Enum):
    """
    Enumeration of available reference types for CmdbPersons.

    This enumeration defines the different modes of referencing persons in the system. 
    Each reference type corresponds to how a CmdbPerson or CmdbPersonGroup is linked or identified.

    Attributes:
        PERSON (str): A reference to a single CmdbPerson
        PERSON_GROUP (str): A reference to a CmdbPersonGroup, which is a collection of CmdbPersons
    """
    PERSON = 'PERSON'
    PERSON_GROUP = 'PERSON_GROUP'


    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a valid PersonReferenceType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing PersonReferenceType, False otherwise
        """
        return value in PersonReferenceType.__members__
