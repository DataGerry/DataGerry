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
This module contains the implementation of the ConnectionStatus
"""
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ConnectionStatus - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ConnectionStatus:
    """
    ConnectionStatus represents the status of the connection to the database
    """

    def __init__(self, connected: bool, message: str = 'No message given'):
        """
        Initialises the ConnectionStatus attributes

        Args:
            `connected` (bool): True if connected to database, else False
            `message` (str, optional): Descriptive message of the connection status. Defaults to 'No message given'.
        """
        self.connected = connected
        self.message = message


    def get_status(self) -> bool:
        """
        Returns the current status of the database connection

        Returns:
            bool: True if connected to database, else False
        """
        return self.connected
