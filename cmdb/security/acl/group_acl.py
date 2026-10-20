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
Implementation of GroupACL

The ``groups`` section of an AccessControlList: each CmdbUserGroup public_id mapped to the permissions
that group holds. The stored document keys the groups by string (a BSON / JSON key is always one), a
CmdbUser's ``group_id`` is an int - so the keys are ints in memory and written back as strings.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.security.acl.access_control_list_section import AccessControlListSection, PermissionValues
from cmdb.security.acl.acl_constants import AclKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   GroupACL - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupACL(AccessControlListSection[int]):
    """
    The group section of an Access Control List (ACL), keyed by CmdbUserGroup public_id

    Every mapping it is given has its keys converted to int, whether they come as stored (strings) or
    already as ints
    """
    def __init__(self, includes: dict[str | int, PermissionValues] | None = None) -> None:
        """
        Initializes the GroupACL

        Args:
            includes (dict[str | int, PermissionValues] | None): Each group public_id, as a string or an
                int, mapped to its permission values. None or an empty mapping grants no group anything
        """
        super().__init__(includes=includes)


    @staticmethod
    def _normalise_keys(value: dict[str | int, PermissionValues]) -> dict[int, PermissionValues]:
        """
        Converts every group key to the int a CmdbUser's group_id is

        Args:
            value (dict[str | int, PermissionValues]): The mapping handed to the `includes` setter

        Returns:
            dict[int, PermissionValues]: The same mapping, keyed by int

        Raises:
            ValueError: When a key is not a whole number - the type write schema only admits digit keys
        """
        return {int(key): permissions for key, permissions in value.items()}


    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "GroupACL":
        """
        Builds a GroupACL from its stored form

        Args:
            data (dict[str, Any]): The stored section, ``{'includes': {'<group_id>': [permission values]}}``;
                a missing or null ``includes`` is an empty section

        Returns:
            GroupACL: The section, keyed by int
        """
        return cls(data.get(AclKey.INCLUDES.value, {}))


    @classmethod
    def to_json(cls, section: AccessControlListSection[int]) -> dict[str, Any]:
        """
        Serialises a GroupACL into its stored form

        Group keys are written back as strings (that is how they are stored) and every permission
        container as a sorted list of its string values, so a section mutated in memory - where the
        mutators keep a set - serialises exactly like one loaded from the database

        Args:
            section (AccessControlListSection[int]): The section to serialise

        Returns:
            dict[str, Any]: ``{'includes': {'<group_id>': [sorted permission values]}}``
        """
        return {
            AclKey.INCLUDES.value: cls._serialise_includes(section)
        }
