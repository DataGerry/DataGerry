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
Implementation of the Levels enumeration

A level is the sensitivity of a right, and the enum is an `IntEnum` because the **ordering is
load-bearing**: `BaseRight`'s level setter compares a candidate against the subclass `MIN_LEVEL` /
`MAX_LEVEL` bounds, so a subclass narrows what it accepts purely by naming two members.

The values are spaced in steps of 10-30 rather than 1-6 so a level can be inserted between two
existing ones later without renumbering the others - stored group documents reference rights by
name, but any code comparing raw values would shift underneath.
"""
from enum import IntEnum
# -------------------------------------------------------------------------------------------------------------------- #

class Levels(IntEnum):
    """
    Class wrapper for different security levels
    """
    CRITICAL = 100
    DANGER = 80
    SECURE = 50
    PROTECTED = 30
    PERMISSION = 10
    NOTSET = 0

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def as_name_map(cls) -> dict[str, "Levels"]:
        """
        Builds the name -> level mapping `GET /rest/rights/levels` serves

        Keyed by NAME because that is the direction a catalogue is read in: a client shows the names
        and works with the numbers. The enum owns it so the catalogue cannot fall out of step with
        the members - it used to be a hand-written dict beside the enum, and only a unit test kept
        the two in agreement.

        The order is the enum's own declaration order (CRITICAL first, descending) and it survives
        into the JSON response, so a member added between two existing ones appears where it was
        declared. A fresh dict is built per call: the previous module-level constant was handed to
        the response by reference, so anything mutating it would have changed the catalogue for the
        rest of the process.

        Returns:
            dict[str, Levels]: Each member keyed by its own name, in declaration order
        """
        return {level.name: level for level in cls}
