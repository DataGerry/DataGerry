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
This module contains the classes of all UserSettingsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class UserSettingsManagerError(Exception):
    """
    Raised to catch all UserSettingsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all UserSettingsManager related errors
        """
        super().__init__(err)

# ------------------------------------------- UserSettingsManager - ERRORS ------------------------------------------- #

class UserSettingsManagerInitError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not be initialised
    """


class UserSettingsManagerInsertError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not insert an CmdbUserSetting
    """


class UserSettingsManagerGetError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not retrieve an CmdbUserSetting
    """


class UserSettingsManagerUpdateError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not update an CmdbUserSetting
    """


class UserSettingsManagerDeleteError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not delete an CmdbUserSetting
    """


class UserSettingsManagerIterationError(UserSettingsManagerError):
    """
    Raised when UserSettingsManager could not iterate over CmdbUserSettings
    """
