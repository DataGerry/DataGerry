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
The CI Explorer's neighbour budget: what one ``item_limit`` slot is

``item_limit`` is an upper bound on neighbour NODES (`CiExplorerGraphRequest.item_limit`). A source that reaches one
neighbour by several edges - two cables to the same switch, a subnet that is both a VLAN's and an interface's - spends
one slot on it and keeps all its edges. ``cut_to_neighbour_budget`` applies that to a list a source has already sorted
by neighbour id, so the cut is deterministic: the same request keeps the same, lowest-id neighbours
"""
from typing import Any, Callable, TypeVar
# -------------------------------------------------------------------------------------------------------------------- #

Entry = TypeVar('Entry')


def cut_to_neighbour_budget(entries: list[Entry],
                            remaining: int,
                            neighbour_id: Callable[[Entry], int]) -> tuple[list[Entry], bool]:
    """
    Keeps the entries of the first ``remaining`` distinct neighbours, with every entry of a neighbour it keeps

    The entries must be sorted by neighbour id already, so the entries of one neighbour sit together and the kept
    neighbours are the lowest ids

    Args:
        entries (list[Entry]): The source's entries (edges), sorted by neighbour id
        remaining (int): How many distinct neighbours may still be shown
        neighbour_id (Callable[[Entry], int]): The neighbour an entry reaches

    Returns:
        tuple[list[Entry], bool]: The kept entries in their order, and whether any neighbour was cut off
    """
    kept: list[Entry] = []
    kept_ids: set[int] = set()

    for entry in entries:
        entry_neighbour: int = neighbour_id(entry)

        if entry_neighbour not in kept_ids:
            if len(kept_ids) >= remaining:
                return kept, True

            kept_ids.add(entry_neighbour)

        kept.append(entry)

    return kept, False


def count_neighbours(entries: list[Entry], neighbour_id: Callable[[Entry], Any]) -> int:
    """
    How many distinct neighbours a source's entries reach - what it spends of the shared budget

    Args:
        entries (list[Entry]): The source's kept entries
        neighbour_id (Callable[[Entry], Any]): The neighbour an entry reaches; any hashable id

    Returns:
        int: The number of distinct neighbours
    """
    return len({neighbour_id(entry) for entry in entries})
