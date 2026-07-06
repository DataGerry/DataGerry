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
This module contains the classes of all DocapiTemplatesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class DocapiTemplatesManagerError(Exception):
    """
    Raised to catch all DocapiTemplatesManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all DocapiTemplatesManager related errors
        """
        super().__init__(err)

# ------------------------------------------ DocapiTemplatesManager - ERRORS ----------------------------------------- #

class DocapiTemplatesManagerInitError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not be initialised
    """


class DocapiTemplatesManagerInsertError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not insert a DocapiTemplate
    """


class DocapiTemplatesManagerGetError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not retrieve a DocapiTemplate
    """


class DocapiTemplatesManagerIterationError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not aggregate DocapiTemplates
    """


class DocapiTemplatesManagerUpdateError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not update a DocapiTemplate
    """


class DocapiTemplatesManagerDeleteError(DocapiTemplatesManagerError):
    """
    Raised when DocapiTemplatesManager could not delete a DocapiTemplate
    """
