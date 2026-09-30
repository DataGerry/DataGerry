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
Reading a CmdbCategory's ``types`` array

The write routes hold every entry to a positive integer naming an existing CmdbType. What is already
stored may predate that rule, so every reader goes through ``readable_type_ids``: an entry that is not a
positive integer is skipped instead of breaking the read - an unhashable one would otherwise make the
category tree and the "uncategorized types" listing answer 500 for every user
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['is_type_id', 'readable_type_ids']


def is_type_id(value: Any) -> bool:
    """
    Reports whether a stored entry can be a CmdbType public_id

    Args:
        value (Any): One entry of a category's ``types`` array

    Returns:
        bool: True for a positive integer (a bool is not one)
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def readable_type_ids(values: Any) -> list[int]:
    """
    Answers the entries of a stored ``types`` array that can be CmdbType ids, in their stored order

    Args:
        values (Any): The stored ``types`` value - normally a list, but read defensively

    Returns:
        list[int]: The positive-integer entries; empty for anything that is not a list
    """
    if not isinstance(values, list):
        return []

    return [value for value in values if is_type_id(value)]
