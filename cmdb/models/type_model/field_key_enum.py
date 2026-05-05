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
Enumeration of dict keys used in CmdbType field, section and SpecialType schemas
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class FieldKey(str, Enum):
    """
    Enumeration of dict keys used in CmdbType field/section/SpecialType schemas

    Use these members instead of bare string literals when constructing or reading schema dicts
    so a typo becomes an ImportError or AttributeError instead of a silently ignored key
    """
    SPECIAL_TYPE = 'special_type'
    SECTIONS = 'sections'
    FIELDS = 'fields'
    TYPE = 'type'
    NAME = 'name'
    LABEL = 'label'
    DESCRIPTION = 'description'
    REF_TYPES = 'ref_types'
    REQUIRED = 'required'
    REGEX = 'regex'
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
