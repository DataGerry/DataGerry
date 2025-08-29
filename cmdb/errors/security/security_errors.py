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
Contains Security error classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class SecurityError(Exception):
    """
    Raised to catch all Security related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all Security related errors
        """
        super().__init__(err)

# ------------------------------------------------- Security - ERRORS ------------------------------------------------ #

class TokenValidationError(SecurityError):
    """
    Raised when a jwt token could not be decoded
    """


class AccessDeniedError(SecurityError):
    """
    Raised when access was denied
    """


class InvalidLevelRightError(SecurityError):
    """
    Raised when a right level is not valid
    """


class MinLevelRightError(SecurityError):
    """
    Raised when min level for a right was violated
    """


class MaxLevelRightError(SecurityError):
    """
    Raised when max level for a right was violated
    """


class NoAccessTokenError(SecurityError):
    """
    Raised when AccessToken is not available
    """


class MissingApiKeyError(SecurityError):
    """
    Raised when an API key is required but missing
    """


class InvalidCloudUserError(SecurityError):
    """
    Raised when Cloud Login failed
    """


class RequestTimeoutError(SecurityError):
    """
    Raised when a request timed out
    """


class RequestError(SecurityError):
    """
    Raised when a request had an error
    """


class DisallowedActionError(SecurityError):
    """
    Raised when an illegal action is requested
    """
