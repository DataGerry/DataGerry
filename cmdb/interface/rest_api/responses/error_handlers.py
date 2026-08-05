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
Error handling routines for all HTTP based errors.

These are executed automatically during an abort().
If an HTTP status code is not implemented, the respective Flask handler is used.

Notes:
    To pass user-defined error messages via the abort() function,
    the description field of the respective class is used.
    This field is used normally again after the message has been saved.
"""
from logging import Logger, getLogger

from flask import request, jsonify
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    BadRequest,
    Unauthorized,
    Forbidden,
    MethodNotAllowed,
    NotAcceptable,
    Gone,
    InternalServerError,
    ServiceUnavailable,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ErrorResponse - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ErrorResponse:
    """TODO: documentation"""
    def __init__(self, status: int, prefix: str, description: str, message: str):
        """TODO: documentation"""
        self.status: int = status
        self.response: str = f'{prefix}: {request.url}'
        self.description: str = description
        self.message: str = self._validate_message(message, description) or ''


    @staticmethod
    def _validate_message(message, description) -> str | None:
        """Checks if description and message are the same"""
        if message != description:
            return message

        return None


    def get_status_code(self) -> int:
        """Get the HTTP status code of this error"""
        return self.status


    def make_error(self, error: HTTPException) -> dict:
        """make a flask valid error response"""
        resp = jsonify(self.__dict__)
        resp.status_code = self.get_status_code()
        error.description = self.description
        resp.error = error

        return resp


# 4xx Client errors
def bad_request(error):
    """400 Bad Request"""

    resp = ErrorResponse(status=400, prefix='Bad Request', description=BadRequest.description,
                            message=error.description)
    return resp.make_error(error)


def unauthorized(error):
    """401 Unauthorized"""
    resp = ErrorResponse(status=401, prefix='Unauthorized', description=Unauthorized.description,
                         message=error.description)
    return resp.make_error(error)


def forbidden(error):
    """403 Forbidden"""
    resp = ErrorResponse(status=403, prefix='Forbidden', description=Forbidden.description,
                         message=error.description)
    return resp.make_error(error)


def page_not_found(error):
    """404 Not Found"""
    resp = ErrorResponse(status=404, prefix='Not Found', description=NotFound.description,
                         message=error.description)
    return resp.make_error(error)


def method_not_allowed(error):
    """405 Method Not Allowed"""
    resp = ErrorResponse(status=405, prefix='Method Not Allowed', description=MethodNotAllowed.description,
                         message=error.description)
    return resp.make_error(error)


def not_acceptable(error):
    """406 Not Acceptable"""
    resp = ErrorResponse(status=406, prefix='Not Acceptable', description=NotAcceptable.description,
                         message=error.description)
    return resp.make_error(error)


def page_gone(error):
    """410 Page Gone"""
    resp = ErrorResponse(status=410, prefix='Gone', description=Gone.description,
                         message=error.description)
    return resp.make_error(error)


# 5xx Server errors
def internal_server_error(error):
    """500 Internal Server Error"""
    resp = ErrorResponse(status=500, prefix='Internal Server Error', description=InternalServerError.description,
                         message=error.description)
    return resp.make_error(error)


def service_unavailable(error):
    """503 Service Unavailable"""
    resp = ErrorResponse(status=503, prefix='Service Unavailable', description=ServiceUnavailable.description,
                         message=error.description)
    return resp.make_error(error)
