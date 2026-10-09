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
Implementation of AccessControlList

An AccessControlList is the ``acl`` property of a CmdbType: an ``activated`` switch plus the sections
that hold the permissions. ``groups`` (a GroupACL, keyed by CmdbUserGroup public_id) is the only
section there is, which is why every section-taking method defaults to it.

Access control is **opt-in**: an ACL that is absent or deactivated permits everything (see
``acl/helpers.py``). When it is activated, the decision is ``verify_access``, and it fails **closed** -
an ACL without groups permits nothing rather than raising.

Two class methods own the stored form: ``default_json`` is the block a Type nobody configured access control for
gets, and ``normalize_stored`` is the complete block any stored value reads as - what the type create writes and
what ``updater_20261003`` wrote back onto every older Type.
"""
from logging import Logger, getLogger
from typing import TypeVar, Any

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.acl.group_acl import GroupACL
from cmdb.security.acl.acl_constants import AclKey
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

        A stored ``groups`` of ``null`` is read as "no groups", the same as an absent one: the section
        below already tolerates a null ``includes``, and a document is free to carry either - the
        collection validates nothing inside ``acl``

        Args:
            data (dict): Data with which the AccessControlList should be initialised

        Returns:
            AccessControlList: AccessControlList with the given data
        """
        return cls(
            activated=data.get(AclKey.ACTIVATED.value, False),
            groups=GroupACL.from_data(data.get(AclKey.GROUPS.value) or {})
        )


    @classmethod
    def default_json(cls) -> dict[str, Any]:
        """
        The complete ``acl`` block of a CmdbType nobody configured access control for

        Switched off, no group granted anything - so the type is governed by the normal rights alone. The one
        spelling of the default: the type create, the type import's repair, the start assistant and the stored-
        shape migration all write it through here, so it cannot drift between them

        Returns:
            dict[str, Any]: ``{'activated': False, 'groups': {'includes': {}}}``, a new dict on every call
        """
        return cls.to_json(cls(activated=False))


    @classmethod
    def normalize_stored(cls, acl: Any) -> dict[str, Any]:
        """
        The complete ``acl`` block a stored value reads as

        Whatever shape a CmdbType's ``acl`` was stored in, this is the block the readers already take it for:
        a value that is no document reads as the default, a missing or null ``activated`` as False (a stored
        non-boolean by its truthiness, the single read's reading), a missing or null ``groups`` / ``includes``
        as no group. Writing it back therefore changes no access decision

        Args:
            acl (Any): The stored ``acl`` value, whatever its shape

        Returns:
            dict[str, Any]: The complete block, ``activated`` a real boolean
        """
        if not isinstance(acl, dict):
            return cls.default_json()

        normalized: dict[str, Any] = cls.to_json(cls.from_data(acl))
        normalized[AclKey.ACTIVATED.value] = bool(normalized[AclKey.ACTIVATED.value])

        return normalized


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
            AclKey.ACTIVATED.value: acl.activated,
            AclKey.GROUPS.value: GroupACL.to_json(acl.groups or GroupACL({}))
        }


    def grant_access(
            self,
            key: T,
            permission: AccessControlPermission,
            section: str = AclKey.GROUPS.value) -> None:
        """
        Grants the specified permission to the given key in the specified section of the ACL

        Defaults to the only section that exists ('groups'), so the natural two-argument call works;
        an unknown section name is a programming error and raises

        Args:
            key (T): The key (e.g., user, group, role) to which the permission is being granted
            permission (AccessControlPermission): The permission to be granted
            section (str): The section of the ACL in which to grant the permission. Defaults to 'groups'

        Raises:
            ValueError: If the section is not recognized
        """
        self._get_section(section).grant_access(key, permission)


    def revoke_access(
            self,
            key: T,
            permission: AccessControlPermission,
            section: str = AclKey.GROUPS.value) -> None:
        """
        Revokes the specified permission from the given key in the specified section of the ACL

        Defaults to the only section that exists ('groups'); revoking a permission the key does not hold
        is a no-op (see AccessControlListSection.revoke_access)

        Args:
            key (T): The key (e.g., user, group, role) from which the permission is being revoked
            permission (AccessControlPermission): The permission to be revoked
            section (str): The section of the ACL in which to revoke the permission. Defaults to 'groups'

        Raises:
            ValueError: If the section is not recognized
        """
        self._get_section(section).revoke_access(key, permission)


    def verify_access(self, key: T, permission: AccessControlPermission) -> bool:
        """
        Verifies if the specified key has the required permission in the access control groups

        Fails **closed**: an ACL that carries no groups section grants nothing. Raising here would turn
        an access check into a 500 on every read of the protected Type

        Args:
            key (T): Identifier for the entity (e.g., user ID, role ID) to check access for
            permission (AccessControlPermission): The permission to check for the specified key

        Returns:
            bool: True if the key has the specified permission in the access control groups, False otherwise
        """
        if not self.groups:
            return False

        return self.groups.verify_access(key, permission)


    def _get_section(self, section: str) -> GroupACL:
        """
        Resolves an ACL section by name, creating the groups section when the ACL carries none yet

        Args:
            section (str): Name of the section ('groups' is the only one today)

        Raises:
            ValueError: If the section name is not recognized

        Returns:
            GroupACL: The section to mutate
        """
        if section != AclKey.GROUPS.value:
            raise ValueError(f'No ACL section with name: {section}')

        if not self.groups:
            self.groups = GroupACL({})

        return self.groups
