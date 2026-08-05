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
Implementation of UpdateSingleResponse
"""
from logging import Logger, getLogger
from typing import Any

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             UpdateSingleResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class UpdateSingleResponse(BaseAPIResponse):
    """
    API Response for update call of a single resource.
    """
    def __init__(self, result: dict[str, Any]) -> None:
        """
        Constructor of UpdateSingleResponse

        Args:
            result: Updated resource
        """
        self.result: dict[str, Any] = result
        super().__init__(operation_type=OperationType.UPDATE)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Make a valid http response.

        Args:
            *args:
            **kwargs:

        Returns:
            Instance of Response with http status code 202
        """
        return self.make_api_response(self.export(), 202)


    def export(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Get the update instance as dict
        """
        return {
            **{
                'result': self.result
            },
            **super().export(*args, **kwargs)
        }
