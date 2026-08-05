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
This module contains the classes of all SectionTemplatesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class SectionTemplatesManagerError(Exception):
    """
    Raised to catch all SectionTemplatesManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all SectionTemplatesManager related errors
        """
        super().__init__(err)

# ----------------------------------------- SectionTemplatesManager - ERRORS ----------------------------------------- #

class SectionTemplatesManagerInitError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not be initialised
    """


class SectionTemplatesManagerInsertError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not insert an CmdbSectionTemplate
    """


class SectionTemplatesManagerGetError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not retrieve an CmdbSectionTemplate
    """


class SectionTemplatesManagerUpdateError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not update an CmdbSectionTemplate
    """


class SectionTemplatesManagerDeleteError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not delete an CmdbSectionTemplate
    """


class SectionTemplatesManagerIterationError(SectionTemplatesManagerError):
    """
    Raised when SectionTemplatesManager could not iterate over CmdbSectionTemplates
    """
