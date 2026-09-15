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
Implementation of GetListResponse
"""
from logging import Logger, getLogger
from typing import Any

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
from cmdb.interface.rest_api.responses.response_constants import ResponseHeader, ResponseKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                GetListResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class GetListResponse(BaseAPIResponse):
    """
    API Response for a simple list without iteration
    """
    def __init__(
            self,
            results: list[dict],
            body: bool | None = None,
            params: APIParameters | None = None) -> None:
        """
        Initializes the GetListResponse

        Args:
            results (list[dict]): The resources to answer with, in the order they were read
            body (bool | None): Whether to answer with a payload; False answers without one (HEAD).
                None means yes
            params (APIParameters | None): The request parameters, consulted for a `?projection=`
        """
        self.params: APIParameters | None = params
        self.results: list[dict] = self.apply_projection(
            results, params.projection if params else None,
        )

        super().__init__(operation_type=OperationType.GET, body=body)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response carrying the list

        The total count is reported as a header as well, so a HEAD request answers how many resources
        there are without a payload

        Args:
            *args (Any): Positional arguments forwarded to `export`
            **kwargs (Any): Keyword arguments forwarded to `export`

        Returns:
            Response: The http response with a HTTP 200 status code, without a payload when the
                caller asked for none
        """
        response: Response = self.make_body_response(*args, **kwargs)
        response.headers[ResponseHeader.TOTAL_COUNT.value] = len(self.results)

        return response


    def export(self) -> dict[str, Any]:
        """
        Returns the response payload as a dict

        Returns:
            dict[str, Any]: The resources under `results`, plus the envelope keys
        """
        return {
            ResponseKey.RESULTS.value: self.results,
            **super().export(),
        }
