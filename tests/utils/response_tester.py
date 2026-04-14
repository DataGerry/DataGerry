# DATAGERRY - OpenSource Enterprise CMDB
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
Module for testing API responses

Provides utility functions to validate HTTP responses
"""
from flask import Response
# -------------------------------------------------------------------------------------------------------------------- #

def default_response_tests(response: Response):
    """
    Performs basic validation checks on a Flask Response object

    Args:
        response (Response): The Flask response object to be tested

    Raises:
        AssertionError: If the response status code is not 200 or if the content type is not 'application/json'
    """
    assert response.status_code == 200
    assert response.content_type == 'application/json'
