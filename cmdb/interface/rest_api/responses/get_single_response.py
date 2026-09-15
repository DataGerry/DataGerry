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
Implementation of GetSingleResponse
"""
from logging import Logger, getLogger
from typing import Any

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_constants import ResponseKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               GetSingleResponse - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class GetSingleResponse(BaseAPIResponse):
    """
    API Response for get calls with a single resource.
    """

    def __init__(self, result: dict, body: bool | None = None, projection: dict | None = None) -> None:
        """
        Initializes the GetSingleResponse

        Args:
            result (dict): The resource to answer with
            body (bool | None): Whether to answer with a payload; False answers without one (HEAD).
                None means yes
            projection (dict | None): An optional client `?projection=` to trim the result with
        """
        self.result: dict = self.apply_projection(result, projection)

        super().__init__(operation_type=OperationType.GET, body=body)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response carrying the single resource

        Args:
            *args (Any): Positional arguments forwarded to `export`
            **kwargs (Any): Keyword arguments forwarded to `export`

        Returns:
            Response: The http response with a HTTP 200 status code, without a payload when the
                caller asked for none
        """
        return self.make_body_response(*args, **kwargs)


    def export(self) -> dict[str, Any]:
        """
        Returns the response payload as a dict

        Returns:
            dict[str, Any]: The resource under `result`, plus the envelope keys
        """
        return {
            ResponseKey.RESULT.value: self.result,
            **super().export(),
        }
