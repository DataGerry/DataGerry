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
Unit tests for cmdb.models.right_model.constants

Pure: no Mongo, no Flask. `NAME_TO_LEVEL` is a hand-written mapping that duplicates the member names
of `Levels`, and it is what `GET /rest/rights/levels` serves. Nothing enforced that the two stay in
step, so adding a level to the enum and forgetting the dict would silently ship a level the frontend
can never select. These tests are that enforcement until the mapping is derived from the enum.

The Levels enum itself is not tested separately: its ordering is what `BaseRight`'s MIN_LEVEL /
MAX_LEVEL bounds are pinned against in `test_base_right.py`, which is the only behaviour it has.
"""
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER, NAME_TO_LEVEL
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

EXPECTED_WILDCARD: str = '*'


class TestNameToLevel:
    """Tests for the NAME_TO_LEVEL mapping served by the levels route"""

    def test_covers_every_level(self) -> None:
        """Every Levels member is reachable by its own name."""
        assert set(NAME_TO_LEVEL) == {level.name for level in Levels}

    def test_maps_each_name_to_its_own_member(self) -> None:
        """No name points at a different level than the one it is named after."""
        for name, level in NAME_TO_LEVEL.items():
            assert level is Levels[name]

    def test_holds_no_extra_entries(self) -> None:
        """The mapping has exactly one entry per level, so no stale name survives a rename."""
        assert len(NAME_TO_LEVEL) == len(Levels)


class TestGlobalRightIdentifier:
    """Tests for the wildcard segment the whole extended-right walk depends on"""

    def test_is_the_wildcard_segment(self) -> None:
        """The identifier is '*'; group documents and route rights are written against it."""
        assert GLOBAL_RIGHT_IDENTIFIER == EXPECTED_WILDCARD
