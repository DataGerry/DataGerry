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
Implementation of GroupDeleteMode
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class GroupDeleteMode(BaseStrEnum):
    """
    Represents the deletion mode for a group

    Omitting the parameter entirely is how a caller asks for "delete the group, leave its members
    alone" - there is no member for that, and the group route treats a missing action as such

    Attributes:
        MOVE: The group's members are reassigned to another group before it is deleted
        DELETE: The group's members are deleted along with it
    """
    MOVE = 'MOVE'
    DELETE = 'DELETE'
