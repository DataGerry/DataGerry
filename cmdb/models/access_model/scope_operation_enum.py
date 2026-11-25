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
The scope operations: what a scope role allows on the objects of its Types
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ScopeOperation(BaseStrEnum):
    """
    The operations a scope role grants, each checked against a different state of the object

    Values:
        VIEW: Read the object - its current state, as a database filter
        CREATE: Create the object - the object as it would be saved
        EDIT: Change the object - its state before and its state after
        DELETE: Delete the object - its state before
    """
    VIEW = 'view'
    CREATE = 'create'
    EDIT = 'edit'
    DELETE = 'delete'
