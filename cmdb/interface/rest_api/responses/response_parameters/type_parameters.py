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

Adds the ``active`` flag to the collection pager. Everything about the pager itself - the coercion, the
validation and the JSON parsing - is inherited; this class only converts ``active`` and hands the rest
to ``CollectionParameters.from_data``

Note ``to_dict`` here is currently DEAD: ``GetMultiResponse`` calls ``CollectionParameters.to_dict``
explicitly, so ``active`` never reaches the response envelope. Nothing in the frontend reads it, so the
envelope is left alone; the method is kept because it is the correct serializer for this class and the
only thing missing is a caller
"""
from typing import Any, Self

from cmdb.interface.rest_api.responses.response_parameters.collection_parameters import CollectionParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
from cmdb.utils import str_to_bool
# -------------------------------------------------------------------------------------------------------------------- #


class TypeIterationParameters(CollectionParameters):
    """
    Represents parameters for type iteration, extending collection parameters

    Adds an ``active`` flag to the collection pager, used to restrict a type listing to active types
    """

    def __init__(self, query_string: str, active: bool = True, **kwargs: Any) -> None:
        """
        Initialize the TypeIterationParameters

        Args:
            query_string (str): The query string for the iteration
            active (bool): Indicates whether only active types are requested. Defaults to True
            **kwargs (Any): Additional keyword arguments passed to the parent class constructor

        Raises:
            ValueError: When a pager value is invalid (see CollectionParameters)
        """
        self.active: bool = active
        super().__init__(query_string=query_string, **kwargs)


    @classmethod
    def from_data(cls, query_string: str, **optional: Any) -> Self:
        """
        Create a TypeIterationParameters instance from HTTP request parameters

        Converts ``active`` (which arrives as a string) and delegates everything else - the wire
        ``filter`` mapping, the JSON parsing and the pager validation - to the parent

        Args:
            query_string (str): The query string for the iteration
            **optional (Any): Additional optional parameters passed from the HTTP request

        Raises:
            JSONDecodeError: When ``filter`` or ``projection`` is not valid JSON
            ValueError: When a pager value is invalid (see CollectionParameters)

        Returns:
            Self: An instance of the calling class with the parsed parameters
        """
        optional[ParameterKey.ACTIVE.value] = str_to_bool(
            optional.pop(ParameterKey.ACTIVE.value, True),
        )

        return super().from_data(query_string, **optional)


    @staticmethod
    def to_dict(parameters: "TypeIterationParameters") -> dict[str, Any]:
        """
        Convert TypeIterationParameters to a dictionary

        Args:
            parameters (TypeIterationParameters): The TypeIterationParameters to be converted

        Returns:
            dict[str, Any]: The collection pager plus the ``active`` flag
        """
        return {
            **CollectionParameters.to_dict(parameters),
            ParameterKey.ACTIVE.value: parameters.active,
        }
