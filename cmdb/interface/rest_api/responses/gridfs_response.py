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
Implementation of GridFsResponse

**Not an API response**, despite the name and the package it lives in: a plain container the media
library uses to carry a page of GridFS files plus the total, with no `make_response` and no envelope.
`media_file_routes` unpacks it and answers through a real response class.

It is constructed in `media_files_manager`, which is why the manager layer currently imports from
`cmdb.interface` - an upward dependency; where this container should move instead is
discussion-backlog #216
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
