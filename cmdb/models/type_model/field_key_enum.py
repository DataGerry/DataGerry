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
Enumeration of dict keys allowed inside a single field entry of a CmdbType field schema
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class FieldKey(str, Enum):
    """
    Enumeration of dict keys allowed inside a single field entry

    A field entry lives inside the 'fields' list of a CmdbType (or SpecialType) schema and describes
    one input shown to the user. Use these members instead of bare string literals when constructing
    or reading a field dict so a typo becomes an ImportError or AttributeError instead of a silently
    ignored key
    """
    TYPE = 'type'
    NAME = 'name'
    LABEL = 'label'
    DESCRIPTION = 'description'
    REQUIRED = 'required'
    REGEX = 'regex'
    REF_TYPES = 'ref_types'
    OPTIONS = 'options'


    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known FieldKey

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing FieldKey, False otherwise
        """
        return value in cls._value2member_map_
