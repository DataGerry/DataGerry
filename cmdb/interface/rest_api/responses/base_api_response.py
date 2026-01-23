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
Implementation of BaseAPIResponse
"""
import logging
from typing import Any
from json import dumps
from datetime import datetime, timezone

from flask import abort, make_response as flask_response
from werkzeug.wrappers import Response

from cmdb.database.database_utils import default
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

DEFAULT_MIME_TYPE = 'application/json'
API_VERSION = '1.0'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                BaseAPIResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseAPIResponse:
    """
    Base class for API responsess
    """
    def __init__(self, operation_type: OperationType, url: str | None = None, body: bool = True) -> None:
        """
        Constructor of a basic api response.

        Args:
            operation_type:
            url:
            model:
            body
        """
        if operation_type.value not in set(item.value for item in OperationType):
            raise TypeError(f'{operation_type} is not a valid response operation')

        self.operation_type: OperationType = operation_type
        self.url: str = url or ''
        self.body = body or True
        self.time: str = datetime.now(timezone.utc).isoformat()


    def make_response(self, status: int = 200) -> Response:
        """
        Abstract method for http response

        Returns:
            http Response
        """
        raise NotImplementedError


    def export(self) -> dict[str, Any]:
        """
        Get the raw information about this response.

        Returns:
            raw data information
        """
        return {
            'response_type': self.operation_type.value,
            'time': self.time
        }


    def make_api_response(
        self,
        body: Any,
        status: int = 200,
        mime: str = DEFAULT_MIME_TYPE,
        indent: int = 2
    ) -> Response:
        """
        Make a valid http response.

        Args:
            body: http body content
            status: http status code
            mime: mime type
            indent: display indent

        Returns:
            Response
        """
        try:
            # Sanitize input if it's a dictionary
            # if isinstance(body, dict):
            #     body = {key: html.escape(str(value)) for key, value in body.items()}

            response = flask_response(dumps(body, default=default, indent=indent), status)
            response.mimetype = mime
            response.headers['X-API-Version'] = API_VERSION

            return response
        except Exception as err:
            LOGGER.debug("[make_response] Exception: %s, Type: %s", err, type(err))
            abort(500, "Failed to create a response from the given data!")
