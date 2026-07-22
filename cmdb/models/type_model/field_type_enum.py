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
Enumeration of all available FieldTypes for CmdbTypes
"""
<<<<<<< HEAD
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class FieldType(str, Enum):
=======
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class FieldType(BaseStrEnum):
>>>>>>> origin/version-3.2
    """
    Enumeration of field types in CmdbTypes
    """
    TEXT = 'text'
    NUMBER = 'number'
    PASSWORD = 'password'
    TEXTAREA = 'textarea'
    CHECKBOX = 'checkbox'
    RADIO = 'radio'
    SELECT = 'select'
    DATE = 'date'
    REFERENCE = 'ref'
    LOCATION = 'location'
    REF_SECTION = 'ref-section-field'
<<<<<<< HEAD



    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a valid FieldType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing SectionType, False otherwise
        """
        return value in cls._value2member_map_
=======
>>>>>>> origin/version-3.2
