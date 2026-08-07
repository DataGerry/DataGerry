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
Unit tests for cmdb.utils.helpers
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.utils.helpers import (
    coerce_datetime,
    coerce_whole_number,
    is_hex_color,
    is_truthy_query_arg,
    random_hex_color,
    str_to_bool,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestStrToBool:
    """str_to_bool strictly coerces 'true'/'false'/bool and raises on anything else."""

    @pytest.mark.parametrize('value', ['true', 'True', ' TRUE ', True])
    def test_truthy_values(self, value) -> None:
        """Recognised true-ish values coerce to True."""
        assert str_to_bool(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', ' FALSE ', False])
    def test_falsy_values(self, value) -> None:
        """Recognised false-ish values coerce to False."""
        assert str_to_bool(value) is False

    @pytest.mark.parametrize('value', [None, '1', 'yes', 0, 'maybe'])
    def test_unrecognised_raises(self, value) -> None:
        """Unrecognised values raise ValueError."""
        with pytest.raises(ValueError):
            str_to_bool(value)


class TestIsTruthyQueryArg:
    """is_truthy_query_arg leniently interprets query flags without raising."""

    @pytest.mark.parametrize('value', ['true', 'True', ' TRUE ', True])
    def test_truthy(self, value) -> None:
        """true-ish values return True."""
        assert is_truthy_query_arg(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', False])
    def test_falsy(self, value) -> None:
        """false-ish values return False."""
        assert is_truthy_query_arg(value) is False

    @pytest.mark.parametrize('value', [None, '1', 'yes', 'maybe', 0])
    def test_unrecognised_returns_default_false(self, value) -> None:
        """Missing / unrecognised values return the default (False) instead of raising."""
        assert is_truthy_query_arg(value) is False

    def test_custom_default_applied_to_unrecognised(self) -> None:
        """The provided default is returned for unrecognised input."""
        assert is_truthy_query_arg(None, default=True) is True
        assert is_truthy_query_arg('nonsense', default=True) is True

    def test_recognised_value_ignores_default(self) -> None:
        """A recognised value wins over the default."""
        assert is_truthy_query_arg('false', default=True) is False


class TestCoerceWholeNumber:
    """coerce_whole_number turns the shapes a client can send into an int, or reports None."""

    @pytest.mark.parametrize('value, expected', [
        (42, 42),
        (0, 0),
        (-7, -7),
        (42.0, 42),
        (-7.0, -7),
        ('42', 42),
        ('42.0', 42),
        ('  7 ', 7),
        ('-3', -3),
    ], ids=str)
    def test_accepts_whole_numbers(self, value, expected) -> None:
        """Ints, whole floats and strings holding either all coerce; range is the caller's business."""
        assert coerce_whole_number(value) == expected

    @pytest.mark.parametrize('value', [3.5, '3.5', '4,5', 'abc', '', '   ', None, [], {}], ids=str)
    def test_rejects_anything_that_is_not_whole(self, value) -> None:
        """A fractional or unparseable value is not a whole number."""
        assert coerce_whole_number(value) is None

    @pytest.mark.parametrize('value', [True, False], ids=str)
    def test_rejects_booleans(self, value) -> None:
        """
        bool is an int subclass in Python.

        Without the explicit guard True would coerce to 1, which every caller of this helper would
        then accept as a valid count, index or slot.
        """
        assert coerce_whole_number(value) is None

    def test_a_float_result_is_a_real_int(self) -> None:
        """The result is usable as an int, not a float that merely compares equal."""
        assert isinstance(coerce_whole_number(42.0), int)


class TestIsHexColor:
    """is_hex_color is the '#RRGGBB' predicate behind every user-supplied color."""

    @pytest.mark.parametrize('value', ['#4CAF50', '#4caf50', '#000000', '#FFFFFF', '#1a2B3c'])
    def test_accepts_a_six_digit_hex_color(self, value: str) -> None:
        """Either casing, since '#4caf50' and '#4CAF50' are the same color."""
        assert is_hex_color(value) is True

    @pytest.mark.parametrize('value', ['#4C5', '4CAF50', 'red', '#GGGGGG', '#4CAF5', '#4CAF500',
                                       '', ' #4CAF50', None, 42, True])
    def test_rejects_every_other_spelling(self, value: Any) -> None:
        """
        Strict on purpose.

        The shorthand '#RGB', a bare 'RRGGBB' and a CSS color name are all rejected, so a stored color
        is always the one spelling a frontend has to render - and the one random_hex_color produces.
        """
        assert is_hex_color(value) is False

    def test_accepts_what_random_hex_color_produces(self) -> None:
        """The generator and the validator must agree, or a defaulted color would fail validation."""
        assert is_hex_color(random_hex_color()) is True


class TestCoerceDatetime:
    """coerce_datetime parses a stored or request-supplied timestamp, reporting None rather than raising."""

    def test_passes_a_datetime_through(self) -> None:
        """A value already parsed by pymongo is not re-parsed."""
        stamp = datetime(2026, 9, 1, tzinfo=timezone.utc)

        assert coerce_datetime(stamp) is stamp

    @pytest.mark.parametrize('value', ['2026-09-01', '2026-09-01T12:30:00Z', '2026-09-01 12:30:00'])
    def test_parses_an_iso_string(self, value: str) -> None:
        """A JSON body carries a timestamp as a string."""
        assert isinstance(coerce_datetime(value), datetime)

    @pytest.mark.parametrize('value', [None, '', '   ', 'not-a-date', 42, True, [], {}])
    def test_reports_anything_else_as_none(self, value: Any) -> None:
        """
        Never raises.

        A drifted document still loads, and a malformed request value is refused by the caller with a
        readable message instead of a stack trace.
        """
        assert coerce_datetime(value) is None
