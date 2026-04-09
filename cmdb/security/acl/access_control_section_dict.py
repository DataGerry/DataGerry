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
Implementation of AccessControlSectionDict
"""
from typing import TypeVar, Dict, Set

from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

T = TypeVar('T')

# -------------------------------------------------------------------------------------------------------------------- #
#                                           AccessControlSectionDict - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessControlSectionDict(Dict[T, Set[AccessControlPermission]]):
    """
    A dictionary representing an access control section, where each key is associated with a set of permissions

    This class is a specialized dictionary, where:
        - The key type `T` represents the entity (e.g., user, group, role) the permissions are associated with
        - The value type is a set of `AccessControlPermission` instances, representing the specific permissions
          granted to the entity
    """
    def __init__(self, *args, **kwargs):
        """
        Initializes the AccessControlSectionDict with the provided arguments

        Args:
            *args: Variable positional arguments passed to the parent class constructor
            **kwargs: Variable keyword arguments passed to the parent class constructor
        """
        super().__init__(*args, **kwargs)
