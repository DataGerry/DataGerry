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
This module contains the classes of all CI Explorer errors

The graph builder is deliberately independent of Flask, so it reports what it cannot build by raising
rather than by aborting; the ``/ci_explorer/items`` route maps these to HTTP statuses
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CiExplorerError(Exception):
    """
    Raised to catch all CI Explorer related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all CI Explorer related errors
        """
        super().__init__(err)

# ----------------------------------------------- CI Explorer - ERRORS ----------------------------------------------- #

class CiExplorerTargetNotFoundError(CiExplorerError):
    """
    Raised when the focal CmdbObject of the requested graph does not exist

    The route answers 404: an empty graph and a graph of nothing are otherwise the same response
    """


class CiExplorerGraphBuildError(CiExplorerError):
    """
    Raised when the graph cannot be built from data that should be there

    Currently only the focal object's CmdbType: without it there is no root node to draw the
    neighbours around, and inventing a label would be worse than reporting the inconsistency
    """
