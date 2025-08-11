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
Implementation of InsertSingleResponse
"""
import logging
from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             InsertSingleResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class InsertSingleResponse(BaseAPIResponse):
    """
    API Response for insert call of a single resource
    """
    def __init__(self, raw: dict, result_id: str | int = None) -> None:
        """
        Constructor of InsertSingleResponse

        Args:
            raw: The raw document
            result_id: The new public id or a identifier of the inserted resource
        """
        self.raw: dict = raw
        self.result_id: int = int(result_id)
        super().__init__(operation_type=OperationType.INSERT)


    def make_response(self, *args, **kwargs) -> Response:
        """
        Make a vaid http response.

        Args:
            prefix: URL route prefix for header location settings.
            *args:
            **kwargs:

        Returns:
            Instance of Response with http status code 201.
        """
        response = self.make_api_response(self.export(), 201)

        return response


    def export(self, *args, **kwargs) -> dict:
        """
        Get the data response payload as dict
        """
        return {
            **{
                'result_id': self.result_id,
                'raw': self.raw,
            },
            **super().export(*args, **kwargs)
        }
