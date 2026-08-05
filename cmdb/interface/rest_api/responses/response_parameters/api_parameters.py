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
Implementation of APIParameters
"""
from logging import Logger, getLogger
from json import loads
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIParameters - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class APIParameters:
    """
    A base class for representing parameters used in REST API calls
    """

    def __init__(self, query_string: str = None, projection: dict = None, **optional) -> None:
        """
        Initializes the API parameters with the provided values

        Args:
            query_string (str | None): The query string for filtering or searching data (default is empty string)
            projection (dict | None): A dictionary representing the projection for the response (default is None)
            optional (dict | None): Additional optional parameters that can be passed as keyword arguments
        """
        self.query_string = query_string or ''
        self.projection = projection or {}
        self.optional = optional


    def __repr__(self) -> str:
        return f"Parameters: query_string:{self.query_string}, projection:{self.projection}, optional:{self.optional}"

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, query_string: str, **optional) -> "APIParameters":
        """
        Creates an instance of APIParameters from HTTP request parameters

        Args:
            query_string (str): The query string to filter or search data in the API request
            **optional (dict | None): Any additional parameters, including an optional `projection`
                                         key which will be parsed

        Returns:
            APIParameters: An instance of the APIParameters class with the provided query string
                           and optional parameters
        """
        if 'projection' in optional:
            optional['projection'] = loads(optional['projection'])

        return cls(query_string, **optional)


    @classmethod
    def to_dict(cls, parameters: "APIParameters") -> dict:
        """
        Converts an APIParameters object into a dictionary representation

        Args:
            parameters (APIParameters): The `APIParameters` object to convert to a dictionary

        Returns:
            dict: A dictionary representing the API parameters
        """
        params: dict = {
            'query_string': parameters.query_string
        }

        if parameters.projection:
            params['projection'] = parameters.projection

        return params
