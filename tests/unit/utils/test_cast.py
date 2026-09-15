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
Unit tests for cmdb.utils.cast
"""
from typing import Any

import pytest

from cmdb.utils import auto_cast
from cmdb.utils.cast import boolify, noneify
# -------------------------------------------------------------------------------------------------------------------- #


class TestBoolify:
    """Converting a string spelling of a boolean."""

    @pytest.mark.parametrize('value', ['true', 'True', 'TRUE', 'TrUe', ' true ', '\ttrue\n'])
    def test_accepts_every_capitalisation_of_true(self, value: str) -> None:
        """A spreadsheet writes TRUE, a hand-written file writes true - both are the same boolean."""
        assert boolify(value) is True

    @pytest.mark.parametrize('value', ['false', 'False', 'FALSE', 'FaLsE', ' false ', '\tfalse\n'])
    def test_accepts_every_capitalisation_of_false(self, value: str) -> None:
        """Same for the falsy spelling."""
        assert boolify(value) is False

    @pytest.mark.parametrize('value', ['yes', 'no', '1', '0', 'y', 'n', 'on', 'off', '', '  ', 'truthy'])
    def test_rejects_every_other_spelling(self, value: str) -> None:
        """Only true/false are booleans here - yes/no and 1/0 must fall through to auto_cast's
        numeric casters, which is what makes '1' an int rather than True."""
        with pytest.raises(ValueError):
            boolify(value)

    @pytest.mark.parametrize('value', [None, 1, 0, 1.0, [], {}, object()])
    def test_rejects_non_strings(self, value: Any) -> None:
        """A non-string carries no spelling to interpret."""
        with pytest.raises(ValueError):
            boolify(value)

    def test_a_real_bool_is_not_accepted(self) -> None:
        """Unlike str_to_bool, boolify does not pass a native bool through - auto_cast's int caster
        handles it, which is why auto_cast(True) is 1 and not True."""
        with pytest.raises(ValueError):
            boolify(True)


class TestNoneify:
    """Converting a string spelling of an absent value."""

    @pytest.mark.parametrize('value', ['None', 'null'])
    def test_accepts_the_two_exact_spellings(self, value: str) -> None:
        """These two, written exactly like this, are the only accepted spellings."""
        assert noneify(value) is None

    @pytest.mark.parametrize('value', ['NULL', 'Null', 'NONE', 'none', ' None ', 'nil', ''])
    def test_rejects_every_other_spelling(self, value: str) -> None:
        """Deliberately case-sensitive and not stripped, unlike boolify - see discussion-backlog
        #193. Pinned so a later change to noneify is a deliberate one."""
        with pytest.raises(ValueError):
            noneify(value)

    @pytest.mark.parametrize('value', [None, 0, [], {}])
    def test_rejects_non_strings(self, value: Any) -> None:
        """A real None is not a *spelling* of None and is rejected like anything else."""
        with pytest.raises(ValueError):
            noneify(value)


class TestAutoCast:
    """The caster chain applied to every config value and every CSV cell."""

    @pytest.mark.parametrize(
        'value, expected',
        [
            ('true', True), ('True', True), ('TRUE', True),
            ('false', False), ('False', False), ('FALSE', False),
        ],
    )
    def test_booleans_are_case_insensitive(self, value: str, expected: bool) -> None:
        """The B1 fix: a column of TRUE/FALSE cells and a column of true/false cells now import as
        the same type. Before, only the exact spellings 'True'/'true' became booleans and 'TRUE'
        stayed the string 'TRUE', so one logical column could store both a bool and a str."""
        result = auto_cast(value)

        assert result is expected

    @pytest.mark.parametrize('value, expected', [('0', 0), ('42', 42), ('-7', -7), ('+42', 42)])
    def test_integers(self, value: str, expected: int) -> None:
        """Whole numbers become ints, and '1'/'0' are numbers rather than booleans."""
        result = auto_cast(value)

        assert result == expected
        assert isinstance(result, int)
        assert not isinstance(result, bool)

    @pytest.mark.parametrize('value, expected', [('4.2', 4.2), ('0.0', 0.0), ('-1.5', -1.5), ('1e5', 100000.0)])
    def test_floats(self, value: str, expected: float) -> None:
        """Anything int() rejects but float() accepts becomes a float."""
        result = auto_cast(value)

        assert result == expected
        assert isinstance(result, float)

    @pytest.mark.parametrize('value', ['None', 'null'])
    def test_the_none_spellings_become_none(self, value: str) -> None:
        """A cell reading None or null is erased."""
        assert auto_cast(value) is None

    @pytest.mark.parametrize('value', ['hello', '', '  ', 'NULL', 'yes', '#4CAF50', '2026-09-01'])
    def test_everything_else_stays_a_string(self, value: str) -> None:
        """The string fallback: no caster claimed it, so the text survives unchanged."""
        result = auto_cast(value)

        assert result == value
        assert isinstance(result, str)

    def test_a_non_string_that_no_caster_claims_is_stringified(self) -> None:
        """The fallback applies to non-strings too - a list has no type to cast to, so it becomes
        its repr. Both current callers hand over strings, so this is a contract note, not a path
        anything exercises."""
        assert auto_cast(['a']) == "['a']"

    def test_none_becomes_the_string_none(self) -> None:
        """Pinning today's behaviour, not endorsing it: a real None survives every caster (boolify
        and noneify both compare it against *spellings*) and reaches the string fallback, so it
        comes back as 'None'. Discussion-backlog #192."""
        assert auto_cast(None) == 'None'

    @pytest.mark.parametrize('value, expected', [('007', 7), ('1_000', 1000), ('0042', 42)])
    def test_numeric_looking_identifiers_lose_their_spelling(self, value: str, expected: int) -> None:
        """Pinned, deferred behaviour: int() accepts leading zeros and Python's numeric underscore,
        so an asset tag or serial that looks numeric is stored as a number and its spelling is gone.
        Discussion-backlog #194."""
        assert auto_cast(value) == expected

    @pytest.mark.parametrize('value', ['nan', 'inf', '-inf', 'Infinity'])
    def test_non_finite_floats_are_produced(self, value: str) -> None:
        """Pinned, deferred behaviour: float() accepts these spellings, so a cell reading 'nan'
        becomes a float NaN that no equality or range query matches. Discussion-backlog #192."""
        result = auto_cast(value)

        assert isinstance(result, float)

    def test_a_bool_is_cast_by_int_not_boolify(self) -> None:
        """boolify rejects a native bool, so the int caster claims it - True becomes 1. Worth
        pinning because it is the one input where auto_cast does not round-trip."""
        assert auto_cast(True) == 1
        assert auto_cast(False) == 0
