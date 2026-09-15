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
Implementation of GetMultiResponse
"""
from logging import Logger, getLogger
from typing import Any
from math import ceil

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.helpers.api_pagination import APIPagination
from cmdb.interface.rest_api.responses.helpers.api_pager import APIPager
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses.response_constants import ResponseHeader, ResponseKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               GetMultiResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class GetMultiResponse(BaseAPIResponse):
    """
    API Response for get calls with a collection of resources
    """
    def __init__(self,
                 results: list[dict],
                 total: int,
                 params: CollectionParameters,
                 url: str | None = None,
                 body: bool | None = None) -> None:
        """
        Initializes the GetMultiResponse

        Args:
            results (list[dict]): The elements of the requested page
            total (int): The complete number of elements matching the request, across all pages
            params (CollectionParameters): The parsed query parameters, consulted for a `?projection=`
                and reported back in the pager block
            url (str | None): The requested url, used to build the pagination links
            body (bool | None): Whether to answer with a payload; False answers without one (HEAD).
                None means yes
        """
        self.parameters: CollectionParameters = params
        self.results: list[dict] = self.apply_projection(results, params.projection)

        self.count: int = len(self.results)
        self.total: int = total

        if params.limit == 0:
            total_pages = 1
        else:
            total_pages = ceil(total / params.limit)

        self.pager = APIPager(page=params.page, page_size=params.limit, total_pages=total_pages)
        self.pagination = APIPagination.create(url, self.pager.page, self.pager.total_pages)

        super().__init__(operation_type=OperationType.GET, url=url, body=body)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response carrying the page

        The complete count is reported as a header as well, so a HEAD request answers how many
        resources match without a payload - which is what the Angular services read it for

        Args:
            *args (Any): Positional arguments forwarded to `export`
            **kwargs (Any): Keyword arguments forwarded to `export`, e.g. `pagination=False`

        Returns:
            Response: The http response with a HTTP 200 status code, without a payload when the
                caller asked for none
        """
        response: Response = self.make_body_response(*args, **kwargs)
        response.headers[ResponseHeader.TOTAL_COUNT.value] = self.total

        return response


    def export(self, pagination: bool = True) -> dict[str, Any]:
        """
        Get the response data as dict

        Args:
            pagination: Should the response include pagination data
        Returns:
            Instance as a dict
        """
        extra: dict[str, Any] = {}

        if pagination:
            extra = {
                ResponseKey.PARAMETERS.value: CollectionParameters.to_dict(self.parameters),
                ResponseKey.PAGER.value: self.pager.to_dict(),
                ResponseKey.PAGINATION.value: self.pagination.to_dict(),
            }

        return {
            ResponseKey.RESULTS.value: self.results,
            ResponseKey.COUNT.value: self.count,
            ResponseKey.TOTAL.value: self.total,
            **extra,
            **super().export(),
        }
