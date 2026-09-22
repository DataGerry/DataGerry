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
Unit tests for cmdb.models.right_model.right_constants

Pure: no Mongo, no Flask. What is left in the module is the wildcard segment the whole extended-right
walk depends on - the level catalogue moved onto the enum that owns the members
(`Levels.as_name_map`, tested in `test_levels_enum.py`), so the hand-written copy these tests used to
police no longer exists.
"""
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

EXPECTED_WILDCARD: str = '*'


class TestGlobalRightIdentifier:
    """Tests for the wildcard segment the whole extended-right walk depends on"""

    def test_is_the_wildcard_segment(self) -> None:
        """The identifier is '*'; group documents and route rights are written against it."""
        assert GLOBAL_RIGHT_IDENTIFIER == EXPECTED_WILDCARD
