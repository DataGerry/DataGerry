# DataGerry - OpenSource Enterprise CMDB
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
Implementation of APIPager
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   APIPager - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class APIPager:
    """
    A utility class for paginating API responses.
    
    This class provides metadata about the pagination state, including the current page,
    page size, and total number of pages.
    """

    def __init__(self, page: int, page_size: int, total_pages: int | None = None) -> None:
        """
        Initialises the APIPager

        Args:
            page (int): The current page number
            page_size (int): The number of items per page
            total_pages (int | None): The total number of pages
        """
        self.page: int = page
        self.page_size: int = page_size
        self.total_pages: int | None = total_pages


    def to_dict(self) -> dict[str, int | None]:
        """
        Converts the APIPager properties to a dictionary

        Returns:
            dict: A dictionary containing APIPager properties
        """
        return {
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }
