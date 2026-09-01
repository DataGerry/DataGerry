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

from cmdb.errors.utils import ClassLoadError
from cmdb.utils import (
    coerce_datetime,
    coerce_whole_number,
    duplicate_names,
    is_hex_color,
    is_non_blank_string,
    is_truthy_query_arg,
    load_class,
    parse_import_bool,
    process_bar,
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

    @pytest.mark.parametrize('value', ['#4CAF50\n', '#4CAF50\r\n', '#4CAF50 ', '#4CAF50\t'])
    def test_rejects_trailing_whitespace(self, value: str) -> None:
        """
        A trailing newline used to pass.

        The pattern was anchored with '$', which in Python also matches immediately before a final
        newline, so a color with a trailing newline validated and was stored. It is anchored with
        a \\Z now.
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


class TestLoadClass:
    """load_class resolves the config-driven dotted class paths the runtime is wired with."""

    def test_resolves_a_dotted_path(self) -> None:
        """The path is split at the last dot: module before it, attribute after it."""
        assert load_class('cmdb.utils.helpers.load_class') is load_class

    def test_resolves_a_nested_attribute_path(self) -> None:
        """Only the last dot separates - everything before it is the module path."""
        assert load_class('datetime.datetime') is datetime

    @pytest.mark.parametrize('classname', ['NoDotHere', '', 'load_class'])
    def test_a_path_without_a_dot_raises_class_load_error(self, classname: str) -> None:
        """
        Cannot be split, so there is no module to import.

        Raised as ClassLoadError rather than a bare Exception, so a caller can tell a malformed
        path from an import that genuinely failed.
        """
        with pytest.raises(ClassLoadError):
            load_class(classname)

    def test_an_unimportable_module_surfaces_the_import_error(self) -> None:
        """A well-formed path to a module that does not exist is not this function's failure."""
        with pytest.raises(ModuleNotFoundError):
            load_class('cmdb.utils.no_such_module.Thing')

    def test_a_missing_attribute_surfaces_the_attribute_error(self) -> None:
        """The module imported fine; the name on it is what is missing."""
        with pytest.raises(AttributeError):
            load_class('cmdb.utils.helpers.NoSuchName')

    def test_a_trailing_dot_is_a_missing_attribute(self) -> None:
        """'pkg.module.' splits into a valid module and an empty attribute name."""
        with pytest.raises(AttributeError):
            load_class('cmdb.utils.helpers.')


def _bar_of(written: str) -> str:
    """Return just the 50-char fill of a rendered progress bar, without the trailing counts."""
    return written[written.index('[') + 1:written.index(']')]


class TestProcessBar:
    """process_bar renders the database updater's single-line progress bar."""

    def test_writes_a_bar_at_partial_progress(self, capsys: pytest.CaptureFixture) -> None:
        """The bar is 50 chars wide, filled in proportion, with the raw step counts appended."""
        process_bar('Task', 100, 45)

        written = capsys.readouterr().out

        assert 'Task:' in written
        assert '45%' in written
        assert '[45/100]' in written
        assert len(_bar_of(written)) == 50
        assert _bar_of(written).count('#') == 22

    def test_a_completed_bar_ends_the_line(self, capsys: pytest.CaptureFixture) -> None:
        """A newline is emitted once, so the next stdout write starts on a clean line."""
        process_bar('Task', 10, 10)

        written = capsys.readouterr().out

        assert '100%' in written
        assert _bar_of(written) == '#' * 50
        assert written.endswith('\r\n')

    def test_an_unfinished_bar_does_not_end_the_line(self, capsys: pytest.CaptureFixture) -> None:
        """Successive calls have to overwrite the same terminal line."""
        process_bar('Task', 10, 9)

        assert not capsys.readouterr().out.endswith('\r\n')

    @pytest.mark.parametrize('total', [0, -1])
    def test_a_non_positive_total_writes_nothing(self, capsys: pytest.CaptureFixture, total: int) -> None:
        """Guards the division, and an updater with nothing to do prints no bar at all."""
        process_bar('Task', total, 5)

        assert capsys.readouterr().out == ''

    def test_progress_past_total_is_clamped(self, capsys: pytest.CaptureFixture) -> None:
        """The percentage stops at 100 while the [x/y] segment still shows the raw counts."""
        process_bar('Task', 10, 15)

        written = capsys.readouterr().out

        assert '100%' in written
        assert '[15/10]' in written
        assert _bar_of(written) == '#' * 50

    def test_negative_progress_is_clamped(self, capsys: pytest.CaptureFixture) -> None:
        """
        The lower bound used to be missing.

        Only the top was clamped, so a negative progress produced a negative block count and a bar
        65 chars wide reading '-30%'. The bar is 50 chars at every input now.
        """
        process_bar('Task', 10, -3)

        written = capsys.readouterr().out

        assert '0%' in written
        assert '-30%' not in written
        assert _bar_of(written) == '-' * 50


class TestParseImportBool:
    """parse_import_bool is the permissive boolean an upload's flag column is read with."""

    @pytest.mark.parametrize('value', [True, 1, 'true', 'True', 'TRUE', ' true ', 'yes', 'YES', '1'])
    def test_accepts_every_truthy_spelling(self, value: Any) -> None:
        """More permissive than str_to_bool on purpose - an upload is written by a person."""
        assert parse_import_bool(value) is True

    @pytest.mark.parametrize('value', [False, 0, 'false', 'False', 'FALSE', ' false ', 'no', 'NO', '0'])
    def test_accepts_every_falsy_spelling(self, value: Any) -> None:
        """Same set, negated."""
        assert parse_import_bool(value) is False

    @pytest.mark.parametrize('value', [None, '', '   ', 'maybe', 'y', 'n', 2, -1, 1.0, [], {}])
    def test_reports_an_unusable_value_as_none(self, value: Any) -> None:
        """
        Never raises.

        The import collects the unusable value as a per-entry message instead of failing the whole
        upload, which is the difference from str_to_bool.
        """
        assert parse_import_bool(value) is None

    def test_an_int_other_than_one_or_zero_is_not_a_boolean(self) -> None:
        """Only the two ints that spell a boolean are accepted; 2 is a number, not a flag."""
        assert parse_import_bool(2) is None

    def test_a_float_is_not_a_boolean(self) -> None:
        """1.0 is not a flag - only bool, int and str are inspected."""
        assert parse_import_bool(1.0) is None


class TestIsNonBlankString:
    """is_non_blank_string is the 'this name / label is usable' predicate of the type import."""

    @pytest.mark.parametrize('value', ['name', ' name ', 'a', '0', 'False'])
    def test_accepts_a_string_carrying_more_than_whitespace(self, value: str) -> None:
        """Content is content, whatever it spells."""
        assert is_non_blank_string(value) is True

    @pytest.mark.parametrize('value', ['', ' ', '\t', '\n', '  \t\n '])
    def test_rejects_a_blank_string(self, value: str) -> None:
        """'' and '   ' both mean the same thing - nothing to identify or display with."""
        assert is_non_blank_string(value) is False

    @pytest.mark.parametrize('value', [None, 0, 42, True, [], {}, ['name']])
    def test_rejects_a_non_string(self, value: Any) -> None:
        """A stray number is not a name either."""
        assert is_non_blank_string(value) is False


class TestDuplicateNames:
    """duplicate_names reports the colliding identifiers an import validator rejects."""

    def test_reports_nothing_when_every_value_is_unique(self) -> None:
        """The clean case an accepted upload takes."""
        assert duplicate_names(['a', 'b', 'c']) == []

    def test_reports_an_empty_iterable(self) -> None:
        """A type with no fields collides with nothing."""
        assert duplicate_names([]) == []

    def test_reports_each_duplicate_once(self) -> None:
        """
        A value repeated three times is still one collision.

        The validator names the offending identifier in its message, so listing it twice would
        report the same problem twice.
        """
        assert duplicate_names(['a', 'a', 'a']) == ['a']

    def test_reports_duplicates_in_first_seen_order(self) -> None:
        """The message reads in the order the fields appear in the upload."""
        assert duplicate_names(['b', 'a', 'a', 'b', 'c']) == ['a', 'b']

    def test_reports_every_distinct_duplicate(self) -> None:
        """Two colliding names are two entries."""
        assert sorted(duplicate_names(['x', 'y', 'x', 'y', 'z'])) == ['x', 'y']

    def test_accepts_any_hashable_value(self) -> None:
        """Typed as Iterable[Any] - the import passes strings, but nothing here is string-specific."""
        assert duplicate_names([1, 2, 1, None, None]) == [1, None]

    def test_consumes_a_generator(self) -> None:
        """Iterated once, so a generator is a valid argument."""
        assert duplicate_names(name for name in ['a', 'b', 'a']) == ['a']


class TestRandomHexColor:
    """random_hex_color fills in a CI-Explorer color for a type that brings none."""

    def test_produces_the_accepted_spelling(self) -> None:
        """The generator and is_hex_color have to agree, or a defaulted color fails validation."""
        for _ in range(50):
            assert is_hex_color(random_hex_color()) is True

    def test_is_always_seven_characters(self) -> None:
        """'#' plus six digits - a small value is zero-padded rather than shortened."""
        for _ in range(50):
            assert len(random_hex_color()) == 7

    def test_pads_a_small_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The zero-padding is what keeps '#000001' from collapsing to '#1'."""
        monkeypatch.setattr('cmdb.utils.helpers.random.randint', lambda _low, _high: 1)

        assert random_hex_color() == '#000001'

    def test_renders_the_upper_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0xFFFFFF is in range and renders as white."""
        monkeypatch.setattr('cmdb.utils.helpers.random.randint', lambda _low, _high: 0xFFFFFF)

        assert random_hex_color() == '#FFFFFF'
