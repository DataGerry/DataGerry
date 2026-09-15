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
Implementation of InsertSingleResponse
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
#                                             InsertSingleResponse - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class InsertSingleResponse(BaseAPIResponse):
    """
    API Response for insert call of a single resource
    """
    def __init__(self, raw: dict[str, Any], result_id: str | int | None = None) -> None:
        """
        Constructor of InsertSingleResponse

        Args:
            raw (dict[str, Any]): The raw document as it was stored
            result_id (str | int | None): The new public_id of the inserted resource. Coerced with
                `int()`, so omitting it - which this signature still allows - raises inside the
                constructor; all 28 call sites pass one, and whether the parameter should simply
                become a required int is discussion-backlog #217
        """
        self.raw: dict[str, Any] = raw
        self.result_id: int = int(result_id)
        super().__init__(operation_type=OperationType.INSERT)


    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response for the insert

        Args:
            *args (Any): Unused; kept so every response answers to the same call
            **kwargs (Any): Unused; kept so every response answers to the same call

        Returns:
            Response: The http response with a HTTP 201 status code
        """
        return self.make_api_response(self.export(), 201)


    def export(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Returns the response payload as a dict

        Args:
            *args (Any): Forwarded to the base envelope
            **kwargs (Any): Forwarded to the base envelope

        Returns:
            dict[str, Any]: The new id under `result_id` and the stored document under `raw`, plus
                the envelope keys
        """
        return {
            ResponseKey.RESULT_ID.value: self.result_id,
            ResponseKey.RAW.value: self.raw,
            **super().export(*args, **kwargs),
        }
