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
Represents a CategoryMeta of a CmdbCategory in DataGerry
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CategoryMeta - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoryMeta:
    """
    Implementation of a CategoryMeta for a CmdbCategory
    """
    def __init__(self, icon: str = '', order: int = None):
        self.icon = icon
        self.order = order


    def has_icon(self) -> bool:
        """
        Checks whether an icon is set for the CmdbCategory

        Returns:
            bool: True if an icon is set, otherwise False
        """
        return bool(self.icon)


    def get_icon(self) -> str:
        """
        Retrieves the icon associated with the CmdbCategory

        Returns:
            str: The icon, which may be a string or a Unicode symbol
        """
        return self.icon


    def get_order(self) -> int:
        """
        Retrieves the order of the CmdbCategory

        Returns:
            int: The order value, which determines the CmdbCategory's position
        """
        return self.order
