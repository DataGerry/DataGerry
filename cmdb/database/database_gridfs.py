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
This module provides the implementation of DatabaseGridFS class
"""
from gridfs import GridFS
from pymongo.database import Database
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                                DatabaseGridFS - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class DatabaseGridFS(GridFS):
    """
    DatabaseGridFS handles files that can exceed 16 MB

    `Extends`: GridFS
    """
    def __init__(self, database: Database, collection_name: str):
        """
        Initializes the `DatabaseGridFS` with the specified database and collection

        Args:
            `database` (Database): The MongoDB database instance to connect to
            `collection_name` (str): The name of the collection where files will be stored in GridFS
        """
        super().__init__(database, collection_name)
