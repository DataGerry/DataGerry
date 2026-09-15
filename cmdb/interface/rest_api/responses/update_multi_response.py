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
Implementation of UpdateMultiResponse
"""
from logging import Logger, getLogger
from typing import Any

from werkzeug.wrappers import Response

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_constants import ResponseKey
from cmdb.framework.importer.messages.response_failed_message import ResponseFailedMessage
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              UpdateMultiResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class UpdateMultiResponse(BaseAPIResponse):
    """
    API Response for update call of multiple resources
    """
    def __init__(self, results: list[dict], failed: list[ResponseFailedMessage] | None = None) -> None:
        """
        Initialises the UpdateMultiResponse

        Args:
            results: Updated resources
            failed: Failed data update
        """
        self.results: list[dict] = results
        self.failed: list[ResponseFailedMessage] = failed or []
        super().__init__(operation_type=OperationType.UPDATE)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response for the bulk update

        Args:
            *args (Any): Unused; kept so every response answers to the same call
            **kwargs (Any): Unused; kept so every response answers to the same call

        Returns:
            Response: The http response with a HTTP 202 status code
        """
        return self.make_api_response(self.export(), 202)


    def export(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Returns the response payload as a dict

        Args:
            *args (Any): Forwarded to the base envelope
            **kwargs (Any): Forwarded to the base envelope

        Returns:
            dict[str, Any]: The updated resources under `results` and the rejected ones under
                `failed`, plus the envelope keys
        """
        return {
            ResponseKey.RESULTS.value: self.results,
            ResponseKey.FAILED.value: self.failed,
            **super().export(*args, **kwargs),
        }
