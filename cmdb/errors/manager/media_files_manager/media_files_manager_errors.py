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
This module contains the classes of all MediaFilesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class MediaFileManagerError(Exception):
    """
    Raised to catch all MediaFilesManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all MediaFilesManager related errors
        """
        super().__init__(err)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              MediaFilesManager - ERRORS                                              #
# -------------------------------------------------------------------------------------------------------------------- #

class MediaFileManagerGetError(MediaFileManagerError):
    """
    Raised when MediaFilesManager could not retrieve a file
    """


class MediaFileManagerInsertError(MediaFileManagerError):
    """
    Raised when MediaFilesManager could not create a file
    """


class MediaFileManagerUpdateError(MediaFileManagerError):
    """
    Raised when MediaFilesManager could not update a file
    """


class MediaFileManagerDeleteError(MediaFileManagerError):
    """
    Raised when MediaFilesManager could not delete a file
    """
