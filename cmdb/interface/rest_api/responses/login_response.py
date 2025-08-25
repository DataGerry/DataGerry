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
Implementation of LoginResponse
"""
import logging
from werkzeug.wrappers import Response

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 LoginResponse - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class LoginResponse(BaseAPIResponse):
    """
    Represents a login response containing user details and authentication token
    
    Extends: BaseAPIResponse
    """
    def __init__(self, user: CmdbUser, token: bytes, token_issued_at: int, token_expire: int) -> None:
        """
        Initializes a `LoginResponse` instance

        Args:
            user (CmdbUser): The authenticated user instance
            token (bytes): A valid JWT authentication token
            token_issued_at (int): The UNIX timestamp indicating when the token was issued
            token_expire (int): The UNIX timestamp indicating when the token will expire
        """
        self.user: CmdbUser = user
        self.token = token
        self.token_issued_at = token_issued_at
        self.token_expire = token_expire

        super().__init__(OperationType.GET)


    def make_response(self, status: int = 200) -> Response:
        """
        Creates a valid HTTP response containing the login data

        Args:
            status (int, optional): HTTP status code for the response. Defaults to 200

        Returns:
            Response: An HTTP response instance containing the login data
        """
        response = self.make_api_response(self.export(), status)

        return response


    def export(self) -> dict:
        """
        Exports the login response data as a dictionary

        Returns:
            dict: A dictionary containing user data and authentication token details
        """
        return {
            'user': CmdbUser.to_json(self.user),
            'token': self.token.decode('UTF-8'),
            'token_issued_at': self.token_issued_at,
            'token_expire': self.token_expire
        }
