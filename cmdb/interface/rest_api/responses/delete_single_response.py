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
Implementation of DeleteSingleResponse
"""
import logging
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             DeleteSingleResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DeleteSingleResponse(BaseAPIResponse):
    """
    API Response for delete call of a single resource.
    """

    def __init__(self, raw: dict = None) -> None:
        """
        Constructor of DeleteSingleResponse

        Args:
            raw: Content of deleted resource
        """
        self.raw = raw
        super().__init__(operation_type=OperationType.DELETE)


    def make_response(self, *args, **kwargs) -> Response:
        """
        Make a valid http response

        Args:
            *args:
            **kwargs:
        Returns:
            Instance of Response with 204 if raw content was set else 202
        """
        status_code = 204 if not self.raw else 202

        return self.make_api_response(self.export(*args, **kwargs), status_code)


    def export(self) -> dict:
        """
        Get the delete instance as dict.
        """
        return {**{
            'raw': self.raw
        }, **super().export()}
