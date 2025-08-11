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
Implementation of GetSingleResponse
"""
import logging
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               GetSingleResponse - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class GetSingleResponse(BaseAPIResponse):
    """
    API Response for get calls with a single resource.
    """

    def __init__(self, result: dict, body: bool = None, projection: dict = None) -> None:
        """
        Constructor of GetSingleResponse
        """
        if projection:
            projection = APIProjection(projection)
            self.result = APIProjector(result, projection).project
        else:
            self.result: dict = result
        super().__init__(operation_type=OperationType.GET, body=body)


    def make_response(self, *args, **kwargs) -> Response:
        """
        Make a valid http response

        Args:
            *args:
            **kwargs:

        Returns:
            Instance of Response with a HTTP 200 status code
        """
        if self.body:
            response = self.make_api_response(self.export(*args, **kwargs))
        else:
            response = self.make_api_response(None)

        return response


    def export(self) -> dict:
        """Get content of the response as dict"""
        return {**{
            'result': self.result
        }, **super().export()}
