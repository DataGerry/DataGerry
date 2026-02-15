# DataGerry - OpenSource Enterprise CMDB
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
Implementation of BaseParserResponse
"""
from abc import ABC, abstractmethod
# -------------------------------------------------------------------------------------------------------------------- #

class BaseParserResponse(ABC):
    """
    Base class for parser responses

    Extends: ABC
    """
    def __init__(self, count: int) -> None:
        """
        Initializes the BaseParserResponse with the given count of parsed elements

        Args:
            count (int): The number of elements that have been parsed
        """
        self.count = count


    @abstractmethod
    def output(self) -> dict:
        """
        Abstract method to be implemented by subclasses to return specific response data
        
        Returns:
            dict: The response data, typically a dictionary containing details about the parsed elements
        
        Raises:
            NotImplementedError: If this method is not overridden in a subclass
        """
        raise NotImplementedError("The output() method must be implemented by subclasses.")
