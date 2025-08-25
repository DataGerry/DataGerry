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
This module contains the classes of all Provider errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ProviderError(Exception):
    """
    Raised to catch all Provider related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RelationsManager related errors
        """
        super().__init__(err)

# ------------------------------------------------- Provider - ERRORS ------------------------------------------------ #

class GroupMappingError(ProviderError):
    """
    Raised if a LDAP mapping was not found or failed
    """


class AuthenticationProviderNotActivated(ProviderError):
    """
    Raised if auth provider is not activated
    """


class AuthenticationProviderNotFoundError(ProviderError):
    """
    Raised if auth provider does not exist
    """


class AuthenticationError(ProviderError):
    """
    Raised when user could not be authenticated via provider
    """
