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
Unit tests for cmdb.utils.cast

The rule is **recognise only what is unambiguous**. The interesting half of this file is therefore
what is *refused*: every spelling below is one a permissive caster destroys - `'007'` renumbered to
`7`, `'null'` swallowed, `nan` produced, a real `3.5` truncated to `3` - and a regression that
re-admits one fails here rather than in a customer's data.

Where the type really is known, it is applied elsewhere and afterwards: the CSV importer coerces
every value against its target field's declared type, which is where the two layers compose.
"""
from typing import Any

import pytest

from cmdb.utils import auto_cast
from cmdb.utils.cast import boolify, numberify
# -------------------------------------------------------------------------------------------------------------------- #


class TestBoolify:
    """The only caster whose behaviour did not change."""

    @pytest.mark.parametrize('value', ['true', 'True', 'TRUE', ' true ', '\tTrUe\n'])
    def test_accepts_every_capitalisation_of_true(self, value: str) -> None:
        """A spreadsheet writes TRUE, a hand-written CSV writes true; both are one boolean."""
        assert boolify(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', 'FALSE', ' false '])
    def test_accepts_every_capitalisation_of_false(self, value: str) -> None:
        """Same rule, same reason."""
        assert boolify(value) is False

    @pytest.mark.parametrize('value', ['yes', 'no', '1', '0', 'y', 'n', 'on', 'off', ''])
    def test_rejects_every_other_spelling(self, value: str) -> None:
        """Rejecting `1` / `0` is what lets the numeric caster claim them."""
        with pytest.raises(ValueError):
            boolify(value)

    @pytest.mark.parametrize('value', [None, 1, 0, [], True])
    def test_rejects_non_strings(self, value: Any) -> None:
        """Including a real bool - it has a type already and needs no caster."""
        with pytest.raises(ValueError):
            boolify(value)


class TestNumberifyAccepts:
    """What a data file unambiguously spells as a number."""

    @pytest.mark.parametrize('value, expected', [
        ('0', 0), ('1', 1), ('27017', 27017), ('-12', -12), ('-0', 0), (' 7 ', 7), ('7\n', 7),
    ])
    def test_integers(self, value: str, expected: int) -> None:
        """Surrounding whitespace is ignored, the same normalisation `boolify` applies."""
        result = numberify(value)

        assert result == expected
        assert isinstance(result, int)

    @pytest.mark.parametrize('value, expected', [
        ('1.0', 1.0), ('0.5', 0.5), ('.5', 0.5), ('-12.5', -12.5), ('1e5', 100000.0), ('1E-3', 0.001),
    ])
    def test_floats(self, value: str, expected: float) -> None:
        """A fraction or an exponent makes it a float; everything else integral stays an int."""
        result = numberify(value)

        assert result == expected
        assert isinstance(result, float)


class TestNumberifyRefuses:
    """
    Every one of these is refused, because casting it destroys it

    Each case names the value a real installation loses. They are kept one per line rather than
    collapsed into a single list so that a failure names the spelling that regressed.
    """

    @pytest.mark.parametrize('value', ['007', '0042', '00', '007.5'])
    def test_a_leading_zero_means_an_identifier(self, value: str) -> None:
        """Asset tags, serials, part numbers and postcodes - casting `'007'` stores it as `7`."""
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', ['+7', '+49123', '+1 555'])
    def test_a_leading_plus_means_a_phone_number(self, value: str) -> None:
        """Casting `'+49123'` stores `49123`, with the country code silently removed."""
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', ['1_000', '1_0.5'])
    def test_the_underscore_separator_is_python_syntax_not_a_data_format(self, value: str) -> None:
        """`int('1_000')` is 1000 in Python; no spreadsheet means that."""
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', ['٧', '٠', '０７', '５'])
    def test_non_ascii_digits_are_not_numbers_here(self, value: str) -> None:
        """
        `int()` accepts every Unicode decimal digit, so a CSV from a localized spreadsheet would
        arrive as ASCII integers with the original text gone.
        """
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', ['nan', 'NaN', 'inf', '-inf', 'Infinity', 'INF'])
    def test_the_non_finite_spellings_are_not_numbers(self, value: str) -> None:
        """
        BSON stores them and no query ever matches them

        `NaN != NaN` also breaks the importer's own whole-row comparison, so a re-import of an
        unchanged file reported every row as changed.
        """
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', ['1e', '1.2.3', '0x10', '1,5', '', ' ', '-', '.'])
    def test_malformed_numbers_stay_text(self, value: str) -> None:
        """An exponent must carry its digits; a thousands comma is not a decimal point."""
        with pytest.raises(ValueError):
            numberify(value)

    @pytest.mark.parametrize('value', [None, 3.5, True, ['1'], {'a': 1}])
    def test_rejects_non_strings(self, value: Any) -> None:
        """It converts *spellings*; a value that already has a type is not its business."""
        with pytest.raises(ValueError):
            numberify(value)


class TestAutoCast:
    """The chain: bool, then number, then the string itself."""

    @pytest.mark.parametrize('value, expected', [('true', True), ('FALSE', False), (' True ', True)])
    def test_booleans_win_first(self, value: str, expected: bool) -> None:
        """Order matters only here - nothing else in the chain would claim them."""
        assert auto_cast(value) is expected

    @pytest.mark.parametrize('value, expected', [('27017', 27017), ('0', 0), ('-12', -12)])
    def test_integers(self, value: str, expected: int) -> None:
        """What the config file needs: `port = 27017` reaches the database manager as an int."""
        result = auto_cast(value)

        assert result == expected
        assert isinstance(result, int)

    @pytest.mark.parametrize('value, expected', [('1.5', 1.5), ('1e5', 100000.0)])
    def test_floats(self, value: str, expected: float) -> None:
        """A fraction or an exponent."""
        assert auto_cast(value) == expected

    @pytest.mark.parametrize('value', [
        '007', '+49123', '1_000', '٧', 'nan', 'inf', 'null', 'None', 'NULL', 'none',
        'yes', 'no', '0x10', '1,5', 'hello', '',
    ])
    def test_everything_else_is_returned_as_itself(self, value: str) -> None:
        """
        Not merely equal - **the same object**

        A caster that rebuilt the string would be a place a value could still change. Identity is
        the property that makes "auto_cast cannot damage a value it does not understand" checkable.
        """
        assert auto_cast(value) is value


class TestTheNoneSpellingsAreNoLongerErased:
    """
    Casting turns `'null'` and `'None'` into `None`, and only in those two spellings

    `'NULL'` and `'none'` survived, so whether a cell was erased depended on its capitalisation. The
    fix is not to erase more consistently - it is to stop erasing here. An untyped source has no way
    to spell "absent"; a genuinely empty CSV cell is turned into None by the importer, which is the
    layer that knows what an empty cell means.
    """

    @pytest.mark.parametrize('value', ['null', 'None', 'NULL', 'none', 'Null', 'NONE'])
    def test_every_spelling_survives_as_text(self, value: str) -> None:
        """All six now behave identically, which is the point - the asymmetry is gone."""
        assert auto_cast(value) == value


class TestNonStringsAreReturnedUnchanged:
    """
    Trying every caster against non-strings too lets `int()` claim whatever it can and `str()`
    catch the rest.
    """

    def test_a_real_float_is_not_truncated(self) -> None:
        """
        `int(3.5)` is `3`

        The declared return type includes `float`, so a float is a supported value - and casting one
        back destroys it.
        """
        assert auto_cast(3.5) == 3.5

    def test_a_real_bool_stays_a_bool(self) -> None:
        """`boolify` rejects a native bool, so `int()` would claim it and `True` become `1`."""
        assert auto_cast(True) is True
        assert auto_cast(False) is False

    def test_a_real_none_stays_none(self) -> None:
        """Without this it reaches the string fallback and comes back as the text `'None'`."""
        assert auto_cast(None) is None

    @pytest.mark.parametrize('value', [['a'], {'k': 1}, 0, 1, 42, -3])
    def test_everything_else_is_the_same_object(self, value: Any) -> None:
        """A list would become its repr. Nothing is stringified here."""
        assert auto_cast(value) is value
