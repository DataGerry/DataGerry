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
Constants consumed by the rights routes

The rights catalogue is static product metadata; what varies is who holds each right. These are the
route paths and the keys the overview response adds on top of a serialised right
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Route paths of the rights blueprint (registered under '/rights')
RIGHTS_COLLECTION_ROUTE: str = '/'
RIGHT_ITEM_ROUTE: str = '/<string:name>'
RIGHT_LEVELS_ROUTE: str = '/levels'
RIGHTS_OVERVIEW_ROUTE: str = '/overview'


class RightHolderKey(BaseStrEnum):
    """
    Keys of an overview entry - a serialised right plus who holds it

    NAME is the right's own key, read to look its holders up; the other two are what the overview
    adds. GROUPS carries the holding groups themselves so a client can list them without a second
    request, and GROUPS_COUNT is the same answer as the number beside them

    Attributes:
        NAME: The right's name, its identifier
        GROUPS: The CmdbUserGroups holding the right, each as public_id / name / label
        GROUPS_COUNT: How many groups hold it
    """
    NAME = 'name'
    GROUPS = 'groups'
    GROUPS_COUNT = 'groups_count'
