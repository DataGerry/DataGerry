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
Implementation of ListResult
"""
from typing import TypeVar, Generic

from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

C = TypeVar('C', bound=CmdbDAO)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ListResult - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class ListResult(Generic[C]):
    """
    A class to represent the result of a list query over a collection
    """
    def __init__(self, results: list[C | dict]):
        """
        Initialises a ListResult

        Args:
            results (list[C | dict]): A list of results, either `CmdbDAO` objects
                                             or dictionaries representing the results
        """
        self.results = results
        self.total = len(self.results)
