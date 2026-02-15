# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of DateSettingsDAO
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                DateSettingsDAO - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class DateSettingsDAO:
    """
    Handles regional date settings, including date format and timezone preferences
    """

    __DEFAULT_SETTINGS__: dict[str, str] = {
            'date_format': 'YYYY-MM-DDThh:mm:ssZ',
            'timezone': 'UTC',
        }


    def __init__(self, date_format: str, timezone: str) -> None:
        """
        Initializes DateSettingsDAO

        Args:
            date_format (str): The date format to use
            timezone (str): The timezone setting
        """
        self._id: str = 'date'
        self.date_format: str = date_format
        self.timezone: str = timezone
