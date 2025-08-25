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
Implementation of DefaultResponse
"""
import logging
from typing import Any
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                DefaultResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultResponse(BaseAPIResponse):
    """
    A response class that represents a default API response containing a value

    Extends: BaseAPIResponse
    """
    def __init__(self, value: Any) -> None:
        """
        Initializes the DefaultResponse instance with the provided value

        This constructor takes the provided value and sets it as an attribute of the response
        It also sets the operation type to `GET` by calling the constructor of the parent class (`BaseAPIResponse`)

        Args:
            value (Any): The value to be included in the response body
        """
        self.value = value

        super().__init__(OperationType.GET)


    def make_response(self, status: int = 200) -> Response:
        """
        Constructs and returns a valid HTTP response with the given status code

        This method generates a response using the `value` stored in the instance. By default, 
        the status code is set to 200 (OK), but this can be customized by passing a different 
        status code

        Args:
            status (int, optional): The HTTP status code for the response. Defaults to 200 (OK)

        Returns:
            Response: The HTTP response instance containing the `value` and the provided status code
        """
        return self.make_api_response(self.value, status)
