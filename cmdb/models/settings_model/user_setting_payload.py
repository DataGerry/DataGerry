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
Implementation of UserSettingPayload
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              UserSettingPayload - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class UserSettingPayload:
    """
    Payload wrapper for user settings
    """
    __slots__ = 'name', 'payload'

    def __init__(self, payload: dict):
        """
        Initialises  of UserSettingPayload

        Args:
            payload (dict): Settings option/body/payload
        """
        self.payload = payload


    @classmethod
    def from_data(cls, data: dict) -> "UserSettingPayload":
        """
        Initialises a UserSettingPayload from a dict

        Args:
            data (dict): Data with which the UserSettingPayload should be initialised

        Returns:
            UserSettingPayload: UserSettingPayload with the given data
        """
        return cls(
            payload=data
        )


    @classmethod
    def to_json(cls, instance: "UserSettingPayload") -> dict:
        """
        Converts a UserSettingPayload into a json compatible dict

        Args:
            instance (UserSettingPayload): The UserSettingPayload which should be converted

        Returns:
            dict: Json compatible dict of the UserSettingPayload values
        """
        return instance.payload
