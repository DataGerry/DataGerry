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
# along with this program. If not, see <https://www.gnu.org/licenses/>
"""
Implementation of BuilderParameters
"""

# -------------------------------------------------------------------------------------------------------------------- #
#                                               BuilderParameters - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class BuilderParameters:
    """
    A class to represent query parameters for a builder.

    This class encapsulates filtering, pagination, and sorting parameters
    for constructing database queries or similar operations.
    """

    def __init__(self,
                 criteria: dict | list[dict],
                 limit: int = 0,
                 skip: int = 0,
                 sort: str = 'public_id',
                 order: int = 1):
        """
        Initializes the BuilderParameters

        Args:
            criteria (dict | list[dict]): The filtering criteria for the query
            limit (int, optional): The maximum number of results to return. Defaults to 0 (no limit)
            skip (int, optional): The number of results to skip for pagination. Defaults to 0
            sort (str, optional): The field to sort by. Defaults to 'public_id'
            order (int, optional): The sorting order (1 for ascending, -1 for descending). Defaults to 1
        """
        self.criteria = criteria
        self.limit = limit
        self.skip = skip
        self.sort = sort
        self.order = order


    def __repr__(self):
        """
        Returns a string representation of the BuilderParameters instance

        Returns:
            str: A formatted string displaying the parameter values
        """
        return (f"BuilderParameters(criteria={self.criteria}, limit={self.limit}, "
                f"skip={self.skip}, sort='{self.sort}', order={self.order})")


    def get_criteria(self) -> dict | list[dict]:
        """
        Retrieves the filtering criteria

        Returns:
            dict | list[dict]: The criteria used for filtering the query
        """
        return self.criteria


    def get_limit(self) -> int:
        """
        Retrieves the limit on the number of results

        Returns:
            int: The maximum number of results to retrieve (0 means no limit)
        """
        return self.limit


    def has_limit(self) -> bool:
        """
        Checks whether a limit is set

        Returns:
            bool: True if a limit greater than 0 is set, otherwise False
        """
        return self.limit > 0


    def get_skip(self) -> int:
        """
        Retrieves the number of results to skip

        Returns:
            int: The number of records to skip for pagination
        """
        return self.skip


    def get_sort(self) -> str:
        """
        Retrieves the sorting field

        Returns:
            str: The field by which the results are sorted
        """
        return self.sort


    def get_order(self) -> int:
        """
        Retrieves the sorting order

        Returns:
            int: 1 for ascending order, -1 for descending order
        """
        return self.order
