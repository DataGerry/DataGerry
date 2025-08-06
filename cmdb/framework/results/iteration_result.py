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
This module provides the implementation of IterationResult
"""
from typing import TypeVar, Generic, Type

from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

C = TypeVar('C', bound=CmdbDAO)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                IterationResult - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class IterationResult(Generic[C]):
    """
    A result container for an iteration call over a collection.
    This class holds the query results along with additional metadata such as the total number of items.
    It also provides functionality to convert the raw results into specific CmdbDAO subtypes if necessary.
    """

    def __init__(self, results: list[C | dict], total: int, c: Type[C] = None):
        """
        Initialises the IterationResult

        Args:
            results: A list of raw or generic database results (either CmdbDAO or dict)
            total: The total number of elements in the query
            c: The class type (CmdbDAO subtype) to which the results should be converted. 
               If provided, the results will be converted to instances of this type.
        """
        self.results = results
        self.count = len(self.results)
        self.total = total

        if c is not None:
            self.convert_to(c)


    def convert_to(self, c: Type[C]) -> None:
        """
        Converts the results inside the instance to a specified CmdbDAO subtype.

        Args:
            c: The CmdbDAO subclass to convert the results to. This class must implement a `from_data` method.
        
        Raises:
            AttributeError: If the provided class `c` does not have a `from_data` method.
        """
        if not hasattr(c, 'from_data'):
            raise AttributeError(f"Class '{c.__name__}' does not have a 'from_data' method.")

        self.results = [c.from_data(result) for result in self.results]
