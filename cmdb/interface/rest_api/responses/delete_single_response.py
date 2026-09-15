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
Implementation of DeleteSingleResponse
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
#                                             DeleteSingleResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DeleteSingleResponse(BaseAPIResponse):
    """
    API Response for delete call of a single resource.
    """

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        """
        Constructor of DeleteSingleResponse

        Args:
            raw: Content of deleted resource
        """
        self.raw: dict[str, Any] | None = raw
        super().__init__(operation_type=OperationType.DELETE)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response for the deletion

        Args:
            *args (Any): Positional arguments forwarded to `export`
            **kwargs (Any): Keyword arguments forwarded to `export`

        Returns:
            Response: The http response, 202 when the deleted resource is reported back, 204 when
                there is nothing to report
        """
        status_code: int = 204 if not self.raw else 202

        return self.make_api_response(self.export(*args, **kwargs), status_code)


    def export(self) -> dict[str, Any]:
        """
        Returns the response payload as a dict

        Returns:
            dict[str, Any]: The deleted resource under `raw`, plus the envelope keys
        """
        return {
            ResponseKey.RAW.value: self.raw,
            **super().export(),
        }
