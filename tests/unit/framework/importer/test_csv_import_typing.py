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
How a CSV cell gets its type - the two layers, composed

A cell passes through two casters on its way into an object, and the order they run in is what
decides whether the value survives:

1. `auto_cast`, in the **parser** (`csv_object_parser`), which sees only text and no field
2. `_coerce_scalar_value`, in the **validator**, which knows the target field's declared `type`

A first layer of bare `int()` / `float()` destroys the value before the layer that actually knows the
type can look at it: `'007'` arrives at the TEXT field as an `int` and is stored as `'7'`.

**This file is the proof that they compose**, and it tests them together deliberately - each half in
isolation is already covered by its own unit tests, and the composition is what a regression breaks.

The property in one line: **a value is typed by the column it lands in, never by how it is spelled.**
"""
from typing import Any

import pytest

from cmdb.framework.importer.helper.object_import_validator import _coerce_scalar_value
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.utils import auto_cast
# -------------------------------------------------------------------------------------------------------------------- #


def _import_cell(raw_text: str, field_type: FieldType) -> Any:
    """
    Runs one CSV cell through both layers, in the order the import runs them

    Args:
        raw_text (str): The cell exactly as `csv.reader` hands it over
        field_type (FieldType): The declared type of the field it is mapped to

    Returns:
        Any: The stored value, or None when the validator refused it
    """
    parsed = auto_cast(raw_text)
    coerced, error = _coerce_scalar_value(field_type.value, parsed)

    return None if error else coerced


class TestAnIdentifierKeepsItsSpelling:
    """
    The case with the most reachable consequence

    Asset tags, serial numbers, part numbers and postcodes are exactly the columns that look numeric
    and are not, and the original spelling was gone once stored - an export would not round-trip it.
    """

    @pytest.mark.parametrize('raw', ['007', '0042', '00815'])
    def test_a_leading_zero_survives_into_a_text_field(self, raw: str) -> None:
        """What a user sees in the object afterwards: exactly what was in the file."""
        assert _import_cell(raw, FieldType.TEXT) == raw

    @pytest.mark.parametrize('raw', ['+49123456', '1_000', '٧'])
    def test_the_other_destroyed_spellings_survive_too(self, raw: str) -> None:
        """A phone number, a Python numeric literal and a non-ASCII digit."""
        assert _import_cell(raw, FieldType.TEXT) == raw

    @pytest.mark.parametrize('raw', ['007', '0042'])
    def test_the_same_cell_in_a_number_field_is_still_a_number(self, raw: str) -> None:
        """
        The half that must not regress while fixing the other

        A NUMBER column asked for a number, so `_coerce_number` applies `int()` - which is correct
        *there*, because the type was declared rather than guessed.
        """
        result = _import_cell(raw, FieldType.NUMBER)

        assert result == int(raw)
        assert isinstance(result, int)

    def test_an_ordinary_number_still_reaches_a_number_field(self) -> None:
        """The common case, unchanged: a numeric column of a spreadsheet stores as numbers."""
        assert _import_cell('42', FieldType.NUMBER) == 42


class TestTheNonFiniteSpellings:
    """
    `'nan'` / `'inf'` cast to doubles that BSON stores and no query ever matches

    `NaN != NaN` also broke the importer's own whole-row comparison, so re-importing an unchanged
    file reported every row as changed.
    """

    @pytest.mark.parametrize('raw', ['nan', 'inf', '-inf', 'Infinity'])
    def test_they_are_text_in_a_text_field(self, raw: str) -> None:
        """A product called `inf` keeps its name."""
        assert _import_cell(raw, FieldType.TEXT) == raw

    @pytest.mark.parametrize('raw', ['nan', 'inf', 'Infinity'])
    def test_a_number_field_refuses_them_instead_of_storing_them(self, raw: str) -> None:
        """
        The right answer for a NUMBER column: an error the user can see

        Silently storing a NaN is the outcome that cannot be noticed; a rejected row can be.
        """
        _, error = _coerce_scalar_value(FieldType.NUMBER.value, auto_cast(raw))

        assert error is not None


class TestTheNoneSpellings:
    """Erasing them catches two spellings out of four, so capitalisation would decide."""

    @pytest.mark.parametrize('raw', ['null', 'None', 'NULL', 'none'])
    def test_every_spelling_is_stored_as_written(self, raw: str) -> None:
        """
        All four behave identically now, which is the fix - the asymmetry is what made it a bug

        A genuinely empty cell is a different thing and is still turned into None, by
        `CsvObjectImporter._blank_to_none`, which is the layer that knows an empty cell was the
        user's intent.
        """
        assert _import_cell(raw, FieldType.TEXT) == raw


class TestBooleansAreUnaffected:
    """The one cast that was never in question, pinned so the tightening did not catch it."""

    @pytest.mark.parametrize('raw', ['true', 'TRUE', 'false'])
    def test_a_checkbox_column_still_reads_a_boolean(self, raw: str) -> None:
        """A spreadsheet writes TRUE; the CHECKBOX coercion reads it either way."""
        assert _import_cell(raw, FieldType.CHECKBOX) is (raw.lower() == 'true')
