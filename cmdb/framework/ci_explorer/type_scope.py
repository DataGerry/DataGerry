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
Which CmdbTypes a CI Explorer neighbour may be of

Two constraints decide it, and every source of the graph - object relations, dg_location, IPAM, port connections -
applies both **inside its Mongo read**, before its share of the ``item_limit`` budget is spent:

* the caller's own ``types`` filter (an allow-list; empty allows every type)
* the types the caller's group may not READ (a deny-list, resolved once per request)

So a capped graph counts readable neighbours only: an unreadable neighbour neither takes a slot nor - by leaving a
capped graph emptier than an uncapped one - reveals that it exists
"""
from dataclasses import dataclass, field
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'NeighbourTypeScope',
    'TYPE_ID_KEY',
]

#: The key a CmdbObject document carries its type under
TYPE_ID_KEY: str = 'type_id'

#: The Mongo operators the scope's type clause is built from
IN_OPERATOR: str = '$in'
NOT_IN_OPERATOR: str = '$nin'


@dataclass(frozen=True)
class NeighbourTypeScope:
    """
    The types a neighbour may be of: in ``allowed`` (when it is not empty) and not in ``denied``

    Attributes:
        allowed (frozenset[int]): The caller's ``types`` filter; empty allows every type
        denied (frozenset[int]): The types the caller's group may not READ
    """
    allowed: frozenset[int] = field(default_factory=frozenset)
    denied: frozenset[int] = field(default_factory=frozenset)

    def type_clause(self) -> dict[str, Any]:
        """
        The condition on a type_id value, for whichever key a read stores the type under

        Returns:
            dict[str, Any]: ``{'$in': [...], '$nin': [...]}`` - each half only when it constrains; empty when
                nothing does
        """
        clause: dict[str, Any] = {}

        if self.allowed:
            clause[IN_OPERATOR] = sorted(self.allowed)

        if self.denied:
            clause[NOT_IN_OPERATOR] = sorted(self.denied)

        return clause

    def object_criteria(self) -> dict[str, Any]:
        """
        The scope as a criteria fragment on a CmdbObject read

        Returns:
            dict[str, Any]: ``{'type_id': <type_clause>}``; empty when nothing constrains
        """
        clause: dict[str, Any] = self.type_clause()

        return {TYPE_ID_KEY: clause} if clause else {}

    def admits(self, type_id: Any) -> bool:
        """
        Whether an object of this type may be a neighbour - for a source that reads one object by id

        Args:
            type_id (Any): The object's type_id

        Returns:
            bool: True when the type is allowed and not denied
        """
        return (not self.allowed or type_id in self.allowed) and type_id not in self.denied
