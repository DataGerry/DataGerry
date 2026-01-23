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
import logging
from typing import Any
from math import ceil
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector
from cmdb.interface.rest_api.responses.helpers.api_pagination import APIPagination
from cmdb.interface.rest_api.responses.helpers.api_pager import APIPager
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

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
                 body: bool = None) -> None:
        """
        Constructor of GetMultiResponse

        Args:
            results: List of filtered elements in payload
            total: Complete number of elements
            params: HTTP query parameters
            url: Requested url
            body: If http response should not have a body
        """
        self.parameters: CollectionParameters = params

        if self.parameters.projection:
            project = APIProjection(self.parameters.projection)
            self.results = APIProjector(results, project).project
        else:
            self.results = results

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
        Make a valid http response.

        Args:
            *args:
            **kwargs:

        Returns:
            Instance of Response
        """
        if self.body:
            response = self.make_api_response(self.export(*args, **kwargs))
        else:
            response = self.make_api_response(None)

        response.headers['X-Total-Count'] = self.total

        return response


    def export(self, pagination: bool = True) -> dict[str, Any]:
        """
        Get the response data as dict

        Args:
            pagination: Should the response include pagination data
        Returns:
            Instance as a dict
        """
        extra = {}

        if pagination:
            extra = {
                'parameters': CollectionParameters.to_dict(self.parameters),
                'pager': self.pager.to_dict(),
                'pagination': self.pagination.to_dict()
            }

        return {**{
            'results': self.results,
            'count': self.count,
            'total': self.total,
            **extra
        }, **super().export()}
