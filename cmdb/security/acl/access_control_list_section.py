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
Implementation of AccessControlListSection

An AccessControlListSection maps a key (today: a CmdbUserGroup public_id) to the permissions that key
holds. **Permissions are stored as their string values** ('CREATE' / 'READ' / 'UPDATE' / 'DELETE'), not
as AccessControlPermission members, because that is the format every other party uses: the stored
document, the frontend (whose own enum carries the same strings) and the ACL aggregation stage in
`builder.py`, which matches with ``{'...includes.<group_id>': {'$all': [permission.value]}}``.

A section loaded from the database therefore arrives with **lists** of strings, while one built in
memory holds a set - so the mutators normalise the container before changing it, and ``to_json``
serialises either form back to a sorted list. ``PermissionValues`` names that container.

The ``includes`` setter is the one entry point for a new mapping: it checks that the value is a dict and
hands it to ``_normalise_keys``, which a section overrides to bring the keys into their in-memory type
(``GroupACL`` turns the stored string keys into ints).
"""
from logging import Logger, getLogger
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Any

from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

T = TypeVar('T')

#: A key's permissions: their string values, a list when loaded from the database, a set once mutated in memory
PermissionValues = list[str] | set[str]

# -------------------------------------------------------------------------------------------------------------------- #
#                                           AccessControlListSection - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessControlListSection(ABC, Generic[T]):
    """
    One section of an AccessControlList: a mapping of a key to the permissions that key holds

    ``T`` is the key's in-memory type. The mapping lives in ``includes``; ``grant_access``, ``revoke_access``
    and ``verify_access`` read and change it, ``_serialise_includes`` writes it back in its stored form
    """

    def __init__(self, includes: dict[Any, PermissionValues] | None = None) -> None:
        """
        Initializes an AccessControlListSection with a given mapping of included permissions

        Args:
            includes (dict[Any, PermissionValues] | None): Each key mapped to its permission values, with
                the keys as stored or already in their in-memory type. None or an empty mapping is an
                empty section
        """
        self.includes = includes or {}


    @property
    def includes(self) -> dict[T, PermissionValues]:
        """
        Returns the mapping of included permissions

        Returns:
            dict[T, PermissionValues]: Each key mapped to its permission values
        """
        return self._includes


    @includes.setter
    def includes(self, value: dict[Any, PermissionValues]) -> None:
        """
        Replaces the mapping of included permissions

        The keys are brought into their in-memory type by ``_normalise_keys``; the permission containers
        are kept as given (the mutators normalise a key's container when they change it)

        Args:
            value (dict[Any, PermissionValues]): Each key mapped to its permission values

        Raises:
            TypeError: If the provided value is not a dictionary
        """
        if not isinstance(value, dict):
            raise TypeError('`AccessControlListSection` only takes dict as include structure')

        self._includes = self._normalise_keys(value)


    @staticmethod
    def _normalise_keys(value: dict[Any, PermissionValues]) -> dict[T, PermissionValues]:
        """
        Brings the keys of a new `includes` mapping into their in-memory type

        The base section keeps the keys as given; a section whose stored keys differ from its in-memory
        ones overrides this

        Args:
            value (dict[Any, PermissionValues]): The mapping handed to the `includes` setter

        Returns:
            dict[T, PermissionValues]: The mapping to store
        """
        return value

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    @abstractmethod
    def from_data(cls, data: dict[str, Any]) -> "AccessControlListSection[T]":
        """
        Builds a section from its stored form

        Args:
            data (dict[str, Any]): The stored section, ``{'includes': {<key>: [permission values]}}``

        Returns:
            AccessControlListSection[T]: The section, with its keys in their in-memory type

        Raises:
            NotImplementedError: When a subclass does not implement it
        """
        raise NotImplementedError("Subclasses must implement this method")


    @classmethod
    @abstractmethod
    def to_json(cls, section: "AccessControlListSection[T]") -> dict[str, Any]:
        """
        Serialises a section into its stored form

        Args:
            section (AccessControlListSection[T]): The section to serialise

        Returns:
            dict[str, Any]: The stored section, ``{'includes': {str(key): [sorted permission values]}}``

        Raises:
            NotImplementedError: When a subclass does not implement it
        """
        raise NotImplementedError("Subclasses must implement this method")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _add_entry(self, key: T) -> T:
        """
        Adds an entry for a given key to `includes`, holding no permission (an empty set)

        Args:
            key (T): The key for which to add an entry (today: a CmdbUserGroup public_id)

        Returns:
            T: The key that was added to the dictionary
        """
        self.includes.update({key: set()})

        return key


    def grant_access(self, key: T, permission: AccessControlPermission) -> None:
        """
        Grants a permission to a specified key in the ACL section

        Idempotent: granting a permission the key already holds changes nothing. A key the section does
        not know yet is added. The permission is stored as its **string value**, so ``verify_access``,
        the stored document and the ACL query stage all agree on what is in the set

        Args:
            key (T): The key to which the permission will be granted
            permission (AccessControlPermission): The permission to grant
        """
        if key not in self.includes:
            self._add_entry(key)

        # A section read from the database carries lists, one built in memory carries a set
        self.includes[key] = self._as_permission_set(self.includes[key])
        self.includes[key].add(permission.value)


    def revoke_access(self, key: T, permission: AccessControlPermission) -> None:
        """
        Revokes a permission from a specified key in the ACL section

        Idempotent, and the mirror image of ``grant_access``: revoking a permission the key does not
        hold - or revoking from a key the section does not know - leaves the section unchanged instead
        of raising, so a caller does not have to guard a no-op

        Args:
            key (T): The key from which to revoke the permission
            permission (AccessControlPermission): The permission to revoke
        """
        if key not in self.includes:
            return

        self.includes[key] = self._as_permission_set(self.includes[key])
        self.includes[key].discard(permission.value)


    def verify_access(self, key: T, permission: AccessControlPermission) -> bool:
        """
        Checks whether a given key has a specific permission

        The access decision: fail closed - a key the section does not know holds no permission. Reads
        the stored string values, which is what both a database-loaded and a granted permission is

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


    @staticmethod
    def _as_permission_set(permissions: Any) -> set[str]:
        """
        Normalises a key's stored permissions into a set of their string values

        The same section can hold a list (loaded from the database), a set (built in memory) or - from
        older in-memory code - AccessControlPermission members; a mutator has to be able to change any
        of them

        Args:
            permissions (Any): The key's currently stored permissions

        Returns:
            set[str]: The permissions as a set of string values
        """
        if not permissions:
            return set()

        return {
            permission.value if isinstance(permission, AccessControlPermission) else permission
            for permission in permissions
        }


    @classmethod
    def _serialise_includes(cls, section: "AccessControlListSection[T]") -> dict[str, list[str]]:
        """
        Serialises a section's `includes` into a json / BSON compatible mapping

        Keys become strings and every permission container becomes a **sorted list**, so a section that
        was mutated in memory (holding a set) can be stored exactly like one that came from the database

        Args:
            section (AccessControlListSection[T]): The section to serialise

        Returns:
            dict[str, list[str]]: {str(key): [permission values]}
        """
        return {
            str(key): sorted(cls._as_permission_set(permissions))
            for key, permissions in section.includes.items()
        }
