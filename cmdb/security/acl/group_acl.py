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
"""
from logging import Logger, getLogger
from typing import TypeVar, Any

from cmdb.security.acl.access_control_list_section import AccessControlListSection
from cmdb.security.acl.access_control_section_dict import AccessControlSectionDict
from cmdb.security.acl.acl_constants import AclKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

T = TypeVar('T')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   GroupACL - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupACL(AccessControlListSection[int]):
    """
    Wrapper class for the group section of an Access Control List (ACL)

    This class enforces that the `includes` dictionary uses integer keys
    """
    def __init__(self, includes: AccessControlSectionDict[T]) -> None:
        """
        Initializes the GroupACL

        Args:
            includes (AccessControlSectionDict[T]): A dictionary mapping integer keys to ACL values
        """
        super().__init__(includes=includes)


    @property
    def includes(self) -> dict:
        """
        Returns the access control section dictionary with integer keys
        """
        return self._includes


    @includes.setter
    def includes(self, value: AccessControlSectionDict) -> None:
        """
        Sets the includes dictionary, ensuring all keys are integers

        Args:
            value (AccessControlSectionDict[T]): A dictionary mapping keys to ACL values

        Raises:
            TypeError: If `value` is not a dictionary
        """
        if not isinstance(value, dict):
            raise TypeError("`AccessControlListSection` only accepts dictionaries as an include structure.")

        self._includes = {int(k): v for k, v in value.items()}


    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "GroupACL":
        """
        Initialises a GroupACL from a dict

        Args:
            data (dict): Data with which the GroupACL should be initialised

        Returns:
            GroupACL: GroupACL with the given data
        """
        return cls(data.get(AclKey.INCLUDES.value, {}))


    @classmethod
    def to_json(cls, section: "AccessControlListSection[T]") -> dict[str, Any]:
        """
        Converts a AccessControlListSection[T] into a json compatible dict

        Group keys are written back as strings (that is how they are stored) and every permission
        container as a sorted list of its string values, so a section mutated in memory - where the
        mutators keep a set - serialises exactly like one loaded from the database

        Args:
            section (AccessControlListSection[T]): The AccessControlListSection[T] which should be converted

        Returns:
            dict: Json compatible dict of the AccessControlListSection[T] values
        """
        return {
            AclKey.INCLUDES.value: cls._serialise_includes(section)
        }
