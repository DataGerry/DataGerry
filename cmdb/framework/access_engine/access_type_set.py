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
A set of CmdbTypes as a scope role names them: some Type ids, or every Type - also the ones created later
"""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from cmdb.models.access_model import ALL_TYPES
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TypeSet:
    """
    Some CmdbTypes by public_id, or every Type

    Attributes:
        every_type (bool): True for every Type, also the ones created later - ``ids`` is then empty
        ids (frozenset[int]): The public_ids, when not every Type
    """
    every_type: bool = False
    ids: frozenset[int] = frozenset()

    @classmethod
    def everything(cls) -> 'TypeSet':
        """
        The set of every Type

        Returns:
            TypeSet: Every Type
        """
        return cls(every_type=True)

    @classmethod
    def of(cls, type_ids: Iterable[int]) -> 'TypeSet':
        """
        The set of the given Types

        Args:
            type_ids (Iterable[int]): The public_ids

        Returns:
            TypeSet: Those Types
        """
        return cls(ids=frozenset(type_ids))

    @classmethod
    def from_role_types(cls, types: Any) -> 'TypeSet':
        """
        Reads a stored scope role's ``types`` value: ``ALL_TYPES`` is every Type, a list its ids. Any other value names
        no Type - a role the schema would refuse grants and restricts nothing

        Args:
            types (Any): The stored value

        Returns:
            TypeSet: The Types it names
        """
        if types == ALL_TYPES:
            return cls.everything()

        if isinstance(types, list):
            return cls.of(type_id for type_id in types if isinstance(type_id, int) and not isinstance(type_id, bool))

        return cls()

    @classmethod
    def union_of(cls, type_sets: Iterable['TypeSet']) -> 'TypeSet':
        """
        All the given sets together

        Args:
            type_sets (Iterable[TypeSet]): The sets

        Returns:
            TypeSet: Their union; empty for no sets
        """
        union: TypeSet = cls()

        for type_set in type_sets:
            union = union.union(type_set)

        return union

    def contains(self, type_id: int) -> bool:
        """
        Whether a Type is in the set

        Args:
            type_id (int): The Type's public_id

        Returns:
            bool: True when it is
        """
        return self.every_type or type_id in self.ids

    def union(self, other: 'TypeSet') -> 'TypeSet':
        """
        Both sets together

        Args:
            other (TypeSet): The other set

        Returns:
            TypeSet: Every Type when either is, else the ids of both
        """
        if self.every_type or other.every_type:
            return TypeSet.everything()

        return TypeSet.of(self.ids | other.ids)

    def covers(self, other: 'TypeSet') -> bool:
        """
        Whether this set holds every Type of the other

        Args:
            other (TypeSet): The other set

        Returns:
            bool: True when this is every Type, or the other is no wider and its ids are all here
        """
        if self.every_type:
            return True

        return not other.every_type and other.ids <= self.ids

    def is_empty(self) -> bool:
        """
        Whether the set names no Type at all

        Returns:
            bool: True when it is neither every Type nor holds an id
        """
        return not self.every_type and not self.ids
