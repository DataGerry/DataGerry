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
Unit tests for cmdb.models.right_model.base_right

Pure: no Mongo, no Flask. `BaseRight` is the only node type of the static rights tree and its `level`
setter is the ONLY validation the tree has, so the boundary cases are what most of this pins - in
particular that a raw int equal to a level's value is refused: since Python 3.12 `Enum.__contains__`
answers value lookups too, so the membership test the setter used to do accepted `50` and then failed
on `level.value` with an AttributeError instead of InvalidLevelRightError.

The other half is the name/label contract. `__init__` prefixes the caller's name with the subclass
PREFIX, and those qualified names are what CmdbUserGroup stores and what
`APIBlueprint.protect(right=...)` names, so the prefixing is part of the authorisation contract and
not presentation.
"""
from typing import Any

import pytest

from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER

from cmdb.errors.security import InvalidLevelRightError, MinLevelRightError, MaxLevelRightError
# -------------------------------------------------------------------------------------------------------------------- #

RIGHT_NAME: str = 'view'
CUSTOM_LABEL: str = 'A custom label'
DESCRIPTION: str = 'View something'

# A PREFIX with several segments, as every real subclass has (e.g. base.framework.object)
NESTED_PREFIX: str = 'base.framework.object'

# Values that are not Levels members. NON_MEMBER_MATCHING_VALUE is the regression case: it equals
# Levels.SECURE.value, so `in Levels` is True on Python >= 3.12
NON_MEMBER_MATCHING_VALUE: int = 50
NON_MEMBER_UNKNOWN_VALUE: int = 42
NON_MEMBER_STRING: str = 'SECURE'

UNKNOWN_ATTRIBUTE: str = 'not_an_attribute'


class NestedRight(BaseRight):
    """A right whose PREFIX has several segments, like every real domain right."""
    PREFIX = NESTED_PREFIX


class BoundedRight(BaseRight):
    """A right that narrows the accepted level window, which subclasses are allowed to do."""
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.SECURE


class TestLevelValidation:
    """Tests for the BaseRight.level property and its setter"""

    def test_accepts_every_levels_member(self) -> None:
        """Every member of Levels is accepted by the default (unnarrowed) bounds."""
        for level in Levels:
            assert BaseRight(level, RIGHT_NAME).level is level

    def test_rejects_int_equal_to_a_level_value(self) -> None:
        """A raw int equal to a level's value is refused, not silently accepted (Python 3.12)."""
        with pytest.raises(InvalidLevelRightError):
            BaseRight(NON_MEMBER_MATCHING_VALUE, RIGHT_NAME)

    def test_rejects_int_matching_no_level_value(self) -> None:
        """An int that matches no level value is refused."""
        with pytest.raises(InvalidLevelRightError):
            BaseRight(NON_MEMBER_UNKNOWN_VALUE, RIGHT_NAME)

    def test_rejects_string_and_none(self) -> None:
        """Neither a level name nor None is a Levels member."""
        for candidate in (NON_MEMBER_STRING, None):
            with pytest.raises(InvalidLevelRightError):
                BaseRight(candidate, RIGHT_NAME)

    def test_rejects_level_below_a_narrowed_minimum(self) -> None:
        """A subclass that raises MIN_LEVEL refuses anything under it."""
        with pytest.raises(MinLevelRightError):
            BoundedRight(Levels.PERMISSION, RIGHT_NAME)

    def test_rejects_level_above_a_narrowed_maximum(self) -> None:
        """A subclass that lowers MAX_LEVEL refuses anything over it."""
        with pytest.raises(MaxLevelRightError):
            BoundedRight(Levels.CRITICAL, RIGHT_NAME)

    def test_accepts_the_narrowed_bounds_themselves(self) -> None:
        """The narrowed bounds are inclusive on both ends."""
        assert BoundedRight(BoundedRight.MIN_LEVEL, RIGHT_NAME).level is Levels.PROTECTED
        assert BoundedRight(BoundedRight.MAX_LEVEL, RIGHT_NAME).level is Levels.SECURE

    def test_setter_rejects_a_reassignment_too(self) -> None:
        """The validation lives in the setter, so it also guards a later assignment."""
        right = BaseRight(Levels.NOTSET, RIGHT_NAME)

        with pytest.raises(InvalidLevelRightError):
            right.level = NON_MEMBER_MATCHING_VALUE

        assert right.level is Levels.NOTSET


class TestNameAndLabel:
    """Tests for the qualified name, the generated label and the master flag"""

    def test_name_is_prefixed(self) -> None:
        """The stored name is PREFIX + '.' + the given name."""
        assert NestedRight(Levels.NOTSET, RIGHT_NAME).name == f'{NESTED_PREFIX}.{RIGHT_NAME}'

    def test_label_is_generated_from_the_last_prefix_segment(self) -> None:
        """A generated label joins the last PREFIX segment with the last name segment."""
        assert NestedRight(Levels.NOTSET, RIGHT_NAME).label == f'object.{RIGHT_NAME}'

    def test_explicit_label_wins(self) -> None:
        """A label passed in is kept verbatim."""
        assert NestedRight(Levels.NOTSET, RIGHT_NAME, label=CUSTOM_LABEL).label == CUSTOM_LABEL

    def test_get_prefix_returns_the_last_segment(self) -> None:
        """get_prefix is the last dotted segment of PREFIX."""
        assert NestedRight(Levels.NOTSET, RIGHT_NAME).get_prefix() == 'object'
        assert BaseRight(Levels.NOTSET, RIGHT_NAME).get_prefix() == 'base'

    def test_wildcard_name_is_master(self) -> None:
        """The '*' right of a branch is flagged as a master right."""
        assert NestedRight(Levels.NOTSET, GLOBAL_RIGHT_IDENTIFIER).is_master is True

    def test_ordinary_name_is_not_master(self) -> None:
        """Any other right is not a master right."""
        assert NestedRight(Levels.NOTSET, RIGHT_NAME).is_master is False


class TestItemAccess:
    """Tests for BaseRight.__getitem__, the mechanism RightsManager sorts through"""

    def test_reads_an_attribute_by_name(self) -> None:
        """Dictionary-style access returns the attribute value."""
        right = NestedRight(Levels.SECURE, RIGHT_NAME)

        assert right['name'] == f'{NESTED_PREFIX}.{RIGHT_NAME}'
        assert right['level'] is Levels.SECURE

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """An unknown key raises AttributeError - what an unknown ?sort= value produces."""
        with pytest.raises(AttributeError):
            NestedRight(Levels.NOTSET, RIGHT_NAME)[UNKNOWN_ATTRIBUTE]  # pylint: disable=expression-not-assigned


class TestToDict:
    """Tests for BaseRight.to_dict, the serialiser every rights response goes through"""

    def test_carries_every_field(self) -> None:
        """to_dict exposes exactly the five documented keys with the instance's values."""
        right = NestedRight(Levels.SECURE, RIGHT_NAME, description=DESCRIPTION)
        result: dict[str, Any] = BaseRight.to_dict(right)

        assert result == {
            'level': Levels.SECURE,
            'name': f'{NESTED_PREFIX}.{RIGHT_NAME}',
            'label': f'object.{RIGHT_NAME}',
            'description': DESCRIPTION,
            'is_master': False,
        }

    def test_description_defaults_to_none(self) -> None:
        """A right created without a description serialises it as None."""
        assert BaseRight.to_dict(BaseRight(Levels.NOTSET, RIGHT_NAME))['description'] is None
