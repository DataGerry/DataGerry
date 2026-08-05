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
Implementation of TypeIterationParameters
"""
from json import loads

from cmdb.interface.rest_api.responses.response_parameters.collection_parameters import CollectionParameters
from cmdb.utils.helpers import str_to_bool

# -------------------------------------------------------------------------------------------------------------------- #
class TypeIterationParameters(CollectionParameters):
    """
    Represents parameters for type iteration, extending collection parameters

    This class allows for the creation and conversion of parameters used for querying or iterating 
    through types in a collection. It includes the ability to specify a query string, an active flag, 
    and optional parameters like filters and projections
    """
    def __init__(self, query_string: str, active: bool = True, **kwargs) -> None:
        """
        Initialize the TypeIterationParameters

        Args:
            query_string (str): The query string for the iteration
            active (bool, optional): Indicates if the iteration is active. Defaults to True
            **kwargs: Additional keyword arguments passed to the parent class constructor
        """
        self.active: bool = active
        super().__init__(query_string = query_string, **kwargs)


    @classmethod
    def from_data(cls, query_string: str, **optional) -> "TypeIterationParameters":
        """Create a TypeIterationParameters instance from HTTP request parameters

        This method parses optional parameters like `active`, `filter`, and `projection` 
        from the HTTP request and converts them into the appropriate type

        Args:
            query_string (str): The query string for the iteration
            **optional: Additional optional parameters passed from the HTTP request

        Returns:
            TypeIterationParameters: An instance of the class with the parsed parameters
        """
        if 'active' in optional:
            active: bool = str_to_bool(optional.get('active', True))
            del optional['active']
        else:
            active = True

        if 'filter' in optional:
            optional['filter'] = loads(optional['filter'])
        if 'projection' in optional:
            optional['projection'] = loads(optional['projection'])

        return cls(query_string, active=active, **optional)


    @classmethod
    def to_dict(cls, parameters: "TypeIterationParameters") -> dict:
        """
        Convert TypeIterationParameters to a dictionary

        Args:
            parameters (TypeIterationParameters): The TypeIterationParameters to be converted

        Returns:
            dict: A dictionary representation of the TypeIterationParameters, including inherited and custom attributes
        """
        return {**CollectionParameters.to_dict(parameters), **{'active': parameters.active}}
