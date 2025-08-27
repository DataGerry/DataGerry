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
Implementation of AccessControlListSection
"""
from logging import Logger, getLogger
from abc import ABC, abstractmethod
from typing import TypeVar, Set, Generic, Any

from cmdb.security.acl.access_control_section_dict import AccessControlSectionDict
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

T = TypeVar('T')

# -------------------------------------------------------------------------------------------------------------------- #
#                                           AccessControlListSection - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessControlListSection(ABC, Generic[T]):
    """`AccessControlListSection` are a config element inside the complete ac-dict."""

    def __init__(self, includes: AccessControlSectionDict | None = None) -> None:
        """
        Initializes an AccessControlListSection with a given dictionary of included permissions

        Args:
            includes (AccessControlSectionDict | None): A dictionary mapping keys to sets of permissions.
                                                        Defaults to an empty dictionary if not provided
        """
        self.includes = includes or AccessControlSectionDict()


    @property
    def includes(self) -> AccessControlSectionDict:
        """
        Returns the dictionary of included permissions

        Returns:
            AccessControlSectionDict: A dictionary mapping keys to sets of permissions
        """
        return self._includes


    @includes.setter
    def includes(self, value: AccessControlSectionDict) -> None:
        """
        Sets the `includes` attribute to a new dictionary, ensuring that it is of the correct type

        Args:
            value (AccessControlSectionDict): A dictionary to set as the new `includes` attribute

        Raises:
            TypeError: If the provided value is not a dictionary
        """
        if not isinstance(value, dict):
            raise TypeError('`AccessControlListSection` only takes dict as include structure')

        self._includes = value

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    @abstractmethod
    def from_data(cls, data: dict[str, Any]) -> "AccessControlListSection[T]":
        """
        Abstract method that creates an AccessControlListSection instance from a dictionary of data.
        """
        raise NotImplementedError("Subclasses must implement this method")


    @classmethod
    @abstractmethod
    def to_json(cls, section: "AccessControlListSection[T]") -> dict:
        """
        Abstract method that serializes the ACL section to a dictionary.
        """
        raise NotImplementedError("Subclasses must implement this method")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _add_entry(self, key: T) -> T:
        """
        Adds an entry for a given key to the `includes` dictionary with an empty set of permissions

        Args:
            key (T): The key for which to add an entry (e.g., user, group, role)

        Returns:
            T: The key that was added to the dictionary
        """
        self.includes.update({key: Set[AccessControlPermission]()})
        return key


    def _update_entry(self, key: T, permissions: Set[AccessControlPermission]) -> None:
        """
        Updates the permissions for a given key

        Args:
            key (T): The key whose permissions to update
            permissions (Set[AccessControlPermission]): The new set of permissions to assign to the key
        """
        self.includes.update({key: permissions})


    def grant_access(self, key: T, permission: AccessControlPermission) -> None:
        """
        Grants a permission to a specified key in the ACL section

        Args:
            key (T): The key to which the permission will be granted
            permission (AccessControlPermission): The permission to grant

        Raises:
            KeyError: If the key does not exist in the `includes` dictionary
        """
        if key not in self.includes:
            self._add_entry(key)

        self.includes[key].add(permission)


    def revoke_access(self, key: T, permission: AccessControlPermission) -> None:
        """
        Revokes a permission from a specified key in the ACL section

        Args:
            key (T): The key from which to revoke the permission
            permission (AccessControlPermission): The permission to revoke

        Raises:
            KeyError: If the key does not exist in the `includes` dictionary
            ValueError: If the permission is not found for the specified key
        """
        if key not in self.includes:
            raise KeyError(f"The key {key} does not exist in the ACL section.")
        try:
            self.includes[key].remove(permission)
        except KeyError as err:
            raise ValueError(f"The permission {permission} is not granted to key {key}.") from err


    def verify_access(self, key: T, permission: AccessControlPermission) -> bool:
        """
        Checks whether a given key has a specific permission

        Args:
            key (T): Identifier for the entity (e.g., user ID, role ID) to check access for
            permission (AccessControlPermission): Permission to verify against the key's allowed actions

        Returns:
            bool: True if the key has the specified permission, False otherwise
        """
        try:
            return permission.value in self.includes[key]
        except KeyError:
            return False
