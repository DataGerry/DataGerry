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
Unit tests for cmdb.framework.docapi.docapi_template.docgen_helpers

Pure tests: mm->pt conversion (numeric, string, unset and unparseable inputs) and CSS value
formatting (unitless line-height, pt-suffixed numbers, stringified fallback).
"""
from cmdb.framework.docapi.docapi_template.docgen_helpers import (
    mm_to_pt,
    format_value,
    MM_TO_PT_FACTOR,
    LINE_HEIGHT_PROP,
)
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT: int = 7
FONT_SIZE: str = "font-size"


class TestMmToPt:
    """mm_to_pt converts numbers, falls back on unset / unparseable input."""

    def test_numeric_value_converted(self) -> None:
        """A numeric mm value is converted to pt and rounded down."""
        assert mm_to_pt(10, DEFAULT) == int(10 * MM_TO_PT_FACTOR)

    def test_numeric_string_converted(self) -> None:
        """A numeric string is parsed and converted."""
        assert mm_to_pt("10", DEFAULT) == int(10 * MM_TO_PT_FACTOR)

    def test_none_returns_default(self) -> None:
        """A None value is treated as unset and yields the default."""
        assert mm_to_pt(None, DEFAULT) == DEFAULT

    def test_zero_returns_default(self) -> None:
        """A zero value is treated as unset and yields the default."""
        assert mm_to_pt(0, DEFAULT) == DEFAULT

    def test_empty_string_returns_default(self) -> None:
        """An empty string is falsy and yields the default."""
        assert mm_to_pt("", DEFAULT) == DEFAULT

    def test_unparseable_string_returns_default(self) -> None:
        """A non-numeric string cannot be parsed and yields the default (except branch)."""
        assert mm_to_pt("abc", DEFAULT) == DEFAULT

    def test_unparseable_type_returns_default(self) -> None:
        """A value of an unconvertible type yields the default (except branch)."""
        assert mm_to_pt([1, 2], DEFAULT) == DEFAULT


class TestFormatValue:
    """format_value keeps line-height unitless, adds pt to numbers, stringifies the rest."""

    def test_line_height_unitless(self) -> None:
        """The line-height property is returned unitless."""
        assert format_value(LINE_HEIGHT_PROP, 1.4) == "1.4"

    def test_int_gets_pt(self) -> None:
        """An integer value for a normal property gets a pt unit."""
        assert format_value(FONT_SIZE, 9) == "9pt"

    def test_float_gets_pt(self) -> None:
        """A float value for a normal property gets a pt unit."""
        assert format_value(FONT_SIZE, 9.5) == "9.5pt"

    def test_string_returned_as_is(self) -> None:
        """A non-numeric value is stringified without a unit."""
        assert format_value(FONT_SIZE, "9pt") == "9pt"
