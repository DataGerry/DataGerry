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
Implementation of DefaultResponse
"""
from logging import Logger, getLogger
from typing import Any

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                DefaultResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultResponse(BaseAPIResponse):
    """
    A response class that represents a default API response containing a value

    Extends: BaseAPIResponse
    """
    def __init__(self, value: Any, body: bool = True) -> None:
        """
        Initializes the DefaultResponse instance with the provided value

        This constructor takes the provided value and sets it as an attribute of the response
        It also sets the operation type to `GET` by calling the constructor of the parent class (`BaseAPIResponse`)

        Args:
            value (Any): The value to be included in the response body
            body (bool): Whether to answer WITH the payload. Defaults to True, because most callers
                are not HEAD-capable routes; a route that answers HEAD passes
                `routes_helper.request_wants_body()` so the payload is neither built nor serialized
                for a request that discards it
        """
        self.value = value

        super().__init__(OperationType.GET, body=body)


    def make_response(self, *args: Any, status: int = 200, **kwargs: Any) -> Response:
        """
        Constructs and returns a valid HTTP response with the given status code

        This method generates a response using the `value` stored in the instance. By default, 
        the status code is set to 200 (OK), but this can be customized by passing a different 
        status code

        Args:
            *args (Any): Unused; kept so every response answers to the same call
            status (int, optional): The HTTP status code for the response. Defaults to 200 (OK)
            **kwargs (Any): Unused; kept so every response answers to the same call

        Returns:
            Response: The HTTP response instance containing the `value` and the provided status code
        """
        return self.make_body_response(status=status)


    def export(self, *args: Any, **kwargs: Any) -> Any:
        """
        Returns the payload this response answers with

        The value as it was handed in: unlike the paginated responses, a DefaultResponse adds no
        envelope of its own

        Args:
            *args (Any): Unused; kept so every response answers to the same call
            **kwargs (Any): Unused; kept so every response answers to the same call

        Returns:
            Any: The response value
        """
        del args, kwargs

        return self.value
