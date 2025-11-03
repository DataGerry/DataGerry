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
Implementation of AccessControlList
"""
from logging import Logger, getLogger
from typing import TypeVar, Any

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.group_acl import GroupACL
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

T = TypeVar('T')

# -------------------------------------------------------------------------------------------------------------------- #
#                                               AccessControlList - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessControlList:
    """
    Represents an Access Control List (ACL) for managing access permissions

    The `AccessControlList` class is responsible for controlling access to resources based
    on a set of rules, and it includes the ability to manage groups and whether the ACL is activated
    """
    def __init__(self, activated: bool, groups: GroupACL | None = None) -> None:
        """
        Initializes an AccessControlList

        Args:
            activated (bool): A boolean indicating whether the ACL is active or inactive
            groups (GroupACL, optional): A GroupACL instance representing the groups
                                         and their associated permissions. Defaults to None
        """
        self.activated: bool = activated
        self.groups: GroupACL | None = groups


    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "AccessControlList":
        """
        Initialises an AccessControlList from a dict

        Args:
            data (dict): Data with which the AccessControlList should be initialised

        Returns:
            AccessControlList: AccessControlList with the given data
        """
        return cls(
            activated=data.get('activated', False),
            groups=GroupACL.from_data(data.get('groups', {}))
        )


    @classmethod
    def to_json(cls, acl: "AccessControlList") -> dict[str, Any]:
        """
        Converts an AccessControlList into a json compatible dict

        Args:
            instance (AccessControlList): The AccessControlList which should be converted

        Returns:
            dict: Json compatible dict of the AccessControlList values
        """
        return {
            'activated': acl.activated,
            'groups': GroupACL.to_json(acl.groups)
        }


    def grant_access(self, key: T, permission: AccessControlPermission, section: str | None = None) -> None:
        """
        Grants the specified permission to the given key in the specified section of the ACL

        This method checks if the provided section is valid (e.g., 'groups'). If valid, it delegates
        the task to the appropriate ACL section (in this case, groups). Otherwise, it raises a ValueError

        Args:
            key (T): The key (e.g., user, group, role) to which the permission is being granted
            permission (AccessControlPermission): The permission to be granted
            section (str | None): The section of the ACL in which to grant the permission. Defaults to None

        Raises:
            ValueError: If the section is not recognized or if the ACL section does not support the action
        """
        if section == 'groups':
            self.groups.grant_access(key, permission)
        else:
            raise ValueError(f'No ACL section with name: {section}')


    def revoke_access(self, key: T, permission: AccessControlPermission, section: str = None) -> None:
        """
        Revokes the specified permission from the given key in the specified section of the ACL

        This method checks if the provided section is valid (e.g., 'groups'). If valid, it delegates
        the task to the appropriate ACL section (in this case, groups). Otherwise, it raises a ValueError

        Args:
            key (T): The key (e.g., user, group, role) from which the permission is being revoked
            permission (AccessControlPermission): The permission to be revoked
            section (str | None): The section of the ACL in which to revoke the permission. Defaults to None

        Raises:
            ValueError: If the section is not recognized or if the ACL section does not support the action
        """
        if section == 'groups':
            self.groups.revoke_access(key, permission)
        else:
            raise ValueError(f'No ACL section with name: {section}')


    def verify_access(self, key: T, permission: AccessControlPermission) -> bool:
        """
        Verifies if the specified key has the required permission in the access control groups

        Args:
            key (T): Identifier for the entity (e.g., user ID, role ID) to check access for
            permission (AccessControlPermission): The permission to check for the specified key

        Returns:
            bool: True if the key has the specified permission in the access control groups, False otherwise
        """
        return self.groups.verify_access(key, permission)
