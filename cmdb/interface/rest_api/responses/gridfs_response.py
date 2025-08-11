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
Implementation of GridFsResponse
"""
# -------------------------------------------------------------------------------------------------------------------- #

class GridFsResponse:
    """
    Represents a response object for GridFS queries
    """
    def __init__(self, result, total: int = None) -> None:
        """
        Initializes a GridFsResponse instance
        
        Args:
            result (list): The list of results retrieved
            total (int, optional): The total number of available items. Defaults to 0
        """
        self.result = result
        self.count: int = len(result)
        self.total: int = total or 0
