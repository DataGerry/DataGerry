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
Implementation of OptionType
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class OptionType(str, Enum):
    """
    Available OptionTypes for CmdbExtendableOptions
    """
    OBJECT_GROUP = 'OBJECT_GROUP'
    THREAT_VULNERABILITY = 'THREAT_VULNERABILITY'
    IMPLEMENTATION_STATE = 'IMPLEMENTATION_STATE'
    CONTROL_MEASURE = 'CONTROL_MEASURE'
    RISK = 'RISK'


    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a valid OptionType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing OptionType, False otherwise
        """
        return value in OptionType.__members__
