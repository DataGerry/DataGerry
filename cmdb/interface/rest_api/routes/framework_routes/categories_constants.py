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
String constants used by the CmdbCategory REST routes

The ``CategoryListView`` enum captures the ``?view=`` query-string values understood by
the list endpoint - ``list`` for the standard paginated flat listing, ``tree`` for the
nested CategoryTree representation. Extends BaseStrEnum so members compare equal to and
serialize as their raw string values
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class CategoryListView(BaseStrEnum):
    """
    ``?view=`` query-string values accepted by ``GET /rest/categories/``
    """
    LIST = 'list'
    TREE = 'tree'
