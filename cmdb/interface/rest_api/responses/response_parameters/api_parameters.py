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
Implementation of APIParameters, the base of every REST request-parameter class

``from_data`` is the entry point the ``parse_*_parameters`` decorators in ``APIBlueprint`` call with the
raw query string. Two things follow from that and govern this whole package:

* **Every value arrives as a string.** Flask's query parser hands over ``'10'``, not ``10``, and a
  non-empty string is always truthy - which is why the numeric coercions in ``CollectionParameters``
  cannot lean on ``or`` for their defaults.
* **Raising here is how a bad parameter becomes an HTTP 400.** The decorators wrap the whole
  ``from_data`` call and abort 400 on any exception, so a ``ValueError`` or a ``JSONDecodeError`` raised
  in this package is already correctly classified as a client error. That is why the JSON parsing below
  is deliberately unguarded

``to_dict`` is the other half: ``GetMultiResponse`` echoes ``CollectionParameters.to_dict(...)`` back as
the response's ``parameters`` block, so those keys are frontend contract (see ``ParameterKey``)
"""
from typing import Any, Self
from json import loads

from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey
# -------------------------------------------------------------------------------------------------------------------- #

#: Query parameters whose value arrives as a JSON document and is parsed on the way in. Shared by every
#: subclass's from_data through parse_json_parameters, so the parsing lives in exactly one place
JSON_PARAMETERS: tuple[ParameterKey, ...] = (ParameterKey.FILTER, ParameterKey.PROJECTION)


def parse_json_parameters(optional: dict[str, Any]) -> None:
    """
    Parses the JSON-valued query parameters of ``optional`` in place

    ``filter`` and ``projection`` travel as JSON documents in the query string. Deliberately
    unguarded: a malformed value raises ``JSONDecodeError``, which the ``parse_*_parameters``
    decorator converts into an HTTP 400 - the correct answer for a malformed client parameter

    Args:
        optional (dict[str, Any]): The optional query parameters, modified in place

    Raises:
        JSONDecodeError: When a present value is not valid JSON
    """
    for parameter in JSON_PARAMETERS:
        if parameter.value in optional:
            optional[parameter.value] = loads(optional[parameter.value])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIParameters - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class APIParameters:
    """
    A base class for representing parameters used in REST API calls
    """

    def __init__(self, query_string: str = None, projection: dict = None, **optional: Any) -> None:
        """
        Initializes the API parameters with the provided values

        Args:
            query_string (str | None): The query string for filtering or searching data (default is empty string)
            projection (dict | None): A dictionary representing the projection for the response (default is None)
            **optional (Any): Additional optional parameters that can be passed as keyword arguments
        """
        self.query_string = query_string or ''
        self.projection = projection or {}
        self.optional = optional


    def __repr__(self) -> str:
        return f"Parameters: query_string:{self.query_string}, projection:{self.projection}, optional:{self.optional}"

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, query_string: str, **optional: Any) -> Self:
        """
        Creates an instance from the raw HTTP request parameters

        This is the one place the JSON-valued parameters are parsed; every subclass routes its own
        ``from_data`` through here rather than repeating the parsing. ``cls`` is the subclass, so the
        instance built is of the right type

        Args:
            query_string (str): The query string to filter or search data in the API request
            **optional (Any): Any additional parameters, including the optional ``filter`` and
                ``projection`` keys which arrive as JSON and are parsed here

        Raises:
            JSONDecodeError: When ``filter`` or ``projection`` is not valid JSON; the
                ``parse_*_parameters`` decorator turns that into an HTTP 400

        Returns:
            Self: An instance of the CALLING class with the parsed parameters - annotated ``Self`` so
                every subclass inherits an accurate return type and needs no override of its own
        """
        parse_json_parameters(optional)

        return cls(query_string, **optional)


    @staticmethod
    def to_dict(parameters: "APIParameters") -> dict[str, Any]:
        """
        Converts an APIParameters object into a dictionary representation

        Args:
            parameters (APIParameters): The `APIParameters` object to convert to a dictionary

        Returns:
            dict[str, Any]: A dictionary representing the API parameters
        """
        params: dict[str, Any] = {
            ParameterKey.QUERY_STRING.value: parameters.query_string,
            ParameterKey.OPTIONAL.value: parameters.optional,
        }

        if parameters.projection:
            params[ParameterKey.PROJECTION.value] = parameters.projection

        return params
