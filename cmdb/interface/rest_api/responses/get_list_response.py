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
import logging
from typing import Any
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_parameters.api_parameters import APIParameters
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                GetListResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class GetListResponse(BaseAPIResponse):
    """
    API Response for a simple list without iteration
    """
    def __init__(self, results: list[dict], body: bool = None, params: APIParameters = None) -> None:
        self.params = params

        if self.params and self.params.projection:
            projection = APIProjection(self.params.projection)
            self.results = APIProjector(results, projection).project
        else:
            self.results: list[dict] = results

        super().__init__(operation_type=OperationType.GET, body=body)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Make a valid http response.

        Args:
            *args:
            **kwargs:

        Returns:
            Instance of Response with a HTTP 200 status code.
        """
        if self.body:
            response = self.make_api_response(self.export(*args, **kwargs))
        else:
            response = self.make_api_response(None)

        response.headers['X-Total-Count'] = len(self.results)

        return response


    def export(self) -> dict[str, Any]:
        """
        Get the list response
        """
        return {**{
            'results': self.results
        }, **super().export()}
