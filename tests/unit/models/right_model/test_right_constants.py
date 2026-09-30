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

Pure: no Mongo, no Flask. Two things live in the module. The wildcard segment the whole extended-right
walk depends on - the level catalogue moved onto the enum that owns the members (`Levels.as_name_map`,
tested in `test_levels_enum.py`), so the hand-written copy these tests used to police no longer exists.

And `ObjectRightName`, the one spelling of the CmdbObject rights. It has to stay the SAME set the
rights tree declares: a member the tree does not know denies every caller of the route guarded by it,
and a right the tree gains without a member here is a right no route can name without spelling it. The
tripwire below keeps it the one spelling: no module under `cmdb/` writes an object right out.
"""
import re
from pathlib import Path

import pytest

import cmdb
from cmdb.manager.rights_manager import RightsManager
from cmdb.models.right_model.framework_rights import ObjectRight
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER, ObjectRightName
# -------------------------------------------------------------------------------------------------------------------- #

EXPECTED_WILDCARD: str = '*'

CMDB_ROOT: Path = Path(cmdb.__file__).parent

# A string literal naming an object right: the quote, the family prefix and one more segment
OBJECT_RIGHT_LITERAL: re.Pattern = re.compile(rf"""['"]{re.escape(ObjectRight.PREFIX)}\.[\w*]+['"]""")

# The one module allowed to spell them: the enum's own
ENUM_MODULE: Path = CMDB_ROOT / 'models' / 'right_model' / 'right_constants.py'


def _declared_object_right_names() -> set[str]:
    """The qualified names of every ObjectRight the rights tree declares."""
    return {right.name for right in RightsManager().rights if isinstance(right, ObjectRight)}


class TestGlobalRightIdentifier:
    """Tests for the wildcard segment the whole extended-right walk depends on"""

    def test_is_the_wildcard_segment(self) -> None:
        """The identifier is '*'; group documents and route rights are written against it."""
        assert GLOBAL_RIGHT_IDENTIFIER == EXPECTED_WILDCARD


class TestTheEnumMatchesTheRightsTree:
    """The enum and all_rights declare the same object rights."""

    @pytest.mark.parametrize('member', list(ObjectRightName), ids=[member.name for member in ObjectRightName])
    def test_every_member_is_a_declared_right(self, member: ObjectRightName) -> None:
        """user_has_right resolves the name against the tree; an unknown one never matches"""
        assert RightsManager().get_right(member.value) is not None, member.value

    def test_every_declared_object_right_has_a_member(self) -> None:
        """A right added to the tree has to be added here too, or routes start spelling it again"""
        assert _declared_object_right_names() == {member.value for member in ObjectRightName}

    def test_all_is_the_familys_wildcard(self) -> None:
        """ALL is the master right of the object family, granting every other member"""
        assert ObjectRightName.ALL.value == f'{ObjectRight.PREFIX}.{GLOBAL_RIGHT_IDENTIFIER}'
        assert RightsManager().get_right(ObjectRightName.ALL.value).is_master


class TestNoModuleSpellsAnObjectRight:
    """The enum is the one spelling."""

    def test_no_module_writes_an_object_right_out(self) -> None:
        """Every surface guarded by an object right names it through ObjectRightName"""
        offenders: list[str] = [
            f'{path.relative_to(CMDB_ROOT)}:{number}'
            for path in sorted(CMDB_ROOT.rglob('*.py')) if path != ENUM_MODULE
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1)
            if OBJECT_RIGHT_LITERAL.search(line)
        ]

        assert not offenders, offenders

    def test_the_tripwire_recognises_a_literal(self) -> None:
        """The pattern itself: a quoted object right is caught, a mere mention of the prefix is not"""
        assert OBJECT_RIGHT_LITERAL.search("right='base.framework.object.view'")
        assert OBJECT_RIGHT_LITERAL.search('"base.framework.object.*"')
        assert not OBJECT_RIGHT_LITERAL.search('the base.framework.object.view right')
