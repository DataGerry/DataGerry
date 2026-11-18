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
The rights a CmdbUser holds through all of its CmdbUserGroups

A user may be a member of several groups; what it may do is the union of what they grant. A right is held when any
of the groups holds it directly or through a wildcard of a parent segment (``CmdbUserGroup.has_extended_right``). No
group grants nothing - there is no deny, so a further group can only add rights

The union is also what a client is handed (``rights`` / ``rights_json``): every right any group holds, each once, in
the shape a group answers its own rights in - a wildcard right stays a wildcard, which the client widens the way
``grants`` does
"""
from typing import Any, Iterable

from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

class EffectiveRights:
    """
    The union of the rights of a user's groups
    """
    def __init__(self, groups: Iterable[CmdbUserGroup]) -> None:
        """
        Initialises the union over the given groups

        Args:
            groups (Iterable[CmdbUserGroup]): The user's groups that exist - a missing one is simply not among them
        """
        self.groups: tuple[CmdbUserGroup, ...] = tuple(groups)


    @property
    def group_ids(self) -> list[int]:
        """
        The public_ids of the groups the rights come from

        Returns:
            list[int]: The ids, sorted
        """
        return sorted(group.public_id for group in self.groups)


    @property
    def rights(self) -> list[BaseRight]:
        """
        Every right any of the groups holds, each once

        Returns:
            list[BaseRight]: The union, sorted by the right's name - two groups holding the same right add it once
        """
        by_name: dict[str, BaseRight] = {right.name: right for group in self.groups for right in group.rights}

        return [by_name[name] for name in sorted(by_name)]


    def rights_json(self) -> list[dict[str, Any]]:
        """
        The union of the rights as a client reads it - the shape ``CmdbUserGroup.to_json`` answers a group's rights in

        Returns:
            list[dict[str, Any]]: One ``BaseRight.to_dict`` per right of ``rights``
        """
        return [BaseRight.to_dict(right) for right in self.rights]


    def has_right(self, right_name: str) -> bool:
        """
        Whether any of the groups holds the right itself

        Args:
            right_name (str): The qualified name of the right

        Returns:
            bool: True when at least one group holds it
        """
        return any(group.has_right(right_name) for group in self.groups)


    def has_extended_right(self, right_name: str) -> bool:
        """
        Whether any of the groups holds a wildcard right of one of the right's parent segments

        Args:
            right_name (str): The qualified name of the right

        Returns:
            bool: True when at least one group holds such a wildcard
        """
        return any(group.has_extended_right(right_name) for group in self.groups)


    def grants(self, right_name: str) -> bool:
        """
        Whether the user holds the right - directly or through a wildcard, in any of its groups

        Args:
            right_name (str): The qualified name of the right

        Returns:
            bool: True when any group grants it
        """
        return self.has_right(right_name) or self.has_extended_right(right_name)
