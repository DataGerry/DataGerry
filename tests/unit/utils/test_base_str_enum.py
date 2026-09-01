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
Unit tests for cmdb.utils.base_str_enum

Verifies the is_valid classmethod on BaseStrEnum across the two patterns it must support:
membership lookup on a concrete subclass, and scoping so two different subclasses do not share
membership. One sanity test pins the (str, Enum) base order so an accidental swap (which would
break dict-key / JSON / BSON semantics across the codebase) fails loudly here. Defines two
sample BaseStrEnum subclasses for use as fixtures
"""
from typing import Any

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class _SampleColor(BaseStrEnum):
    """Sample concrete BaseStrEnum used only in this test module"""
    RED = 'red'
    GREEN = 'green'
    BLUE = 'blue'


class _SampleSize(BaseStrEnum):
    """A second sample to exercise per-subclass scoping of is_valid"""
    SMALL = 'small'
    LARGE = 'large'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    is_valid                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_is_valid_returns_true_for_each_defined_member_value() -> None:
    """Every value listed on the subclass is reported as valid"""
    for color in _SampleColor:
        assert _SampleColor.is_valid(color.value) is True


def test_is_valid_returns_false_for_unknown_string() -> None:
    """A string that does not match any subclass member is rejected"""
    assert _SampleColor.is_valid('yellow') is False


def test_is_valid_returns_false_for_empty_string() -> None:
    """An empty string is rejected when no member uses it"""
    assert _SampleColor.is_valid('') is False


def test_is_valid_is_case_sensitive() -> None:
    """Member matching is exact-case; 'RED' is not the same as 'red'"""
    assert _SampleColor.is_valid('RED') is False


def test_is_valid_does_not_raise_for_non_string_input() -> None:
    """A non-string argument returns False instead of raising"""
    arbitrary_non_string: Any = 42

    assert _SampleColor.is_valid(arbitrary_non_string) is False


def test_is_valid_does_not_raise_for_none() -> None:
    """None as the argument returns False instead of raising"""
    arbitrary_none: Any = None

    assert _SampleColor.is_valid(arbitrary_none) is False


def test_is_valid_is_scoped_per_subclass() -> None:
    """Each subclass exposes only its own members; membership does not leak across classes"""
    assert _SampleColor.is_valid('small') is False
    assert _SampleSize.is_valid('red') is False
    assert _SampleSize.is_valid('small') is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                         (str, Enum) inheritance sanity                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_member_is_string_equal_to_its_declared_value() -> None:
    """
    Members compare equal to their raw string value

    This protects against an accidental base-order swap to (Enum, str): such a swap would
    silently break the dict-key / JSON / BSON semantics that BaseStrEnum exists to provide
    """
    assert _SampleColor.RED == 'red'
    assert _SampleColor.BLUE == 'blue'


def test_member_is_usable_as_dict_key_alongside_raw_string() -> None:
    """A member and its raw-string equivalent hash to the same dict slot"""
    bucket: dict[str, int] = {_SampleColor.RED: 1}

    assert bucket['red'] == 1
