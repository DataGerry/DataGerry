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
Unit tests for cmdb.framework.object_field_value_rules

Pure tests (no database). Covers the length cap per field kind, the field's pattern read the way the
object form reads it (anchored, not wrapped), which values the rules judge at all, where in an object
the values are read from, that a value the stored object already holds is not judged again, and the time
limit: a backtracking pattern answers TIMED_OUT within its per-match limit, one write shares one budget, and a
timed-out value is refused with its own message
"""
import logging
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.object_field_value_constants import (
    FieldDefaultError,
    FieldValueError,
    MDS_SECTION_SUFFIX,
    PATTERN_MATCH_TIMEOUT_SECONDS,
    PATTERN_WRITE_BUDGET_SECONDS,
    PatternVerdict,
)
from cmdb.framework.object_field_value_rules import (
    FieldValueRule,
    PatternBudget,
    anchor_field_regex,
    build_field_value_rules,
    collect_object_value_errors,
    collect_stored_values,
    compile_field_regex,
    find_default_errors,
    find_default_value_errors,
    find_value_errors,
    has_no_value,
    iter_object_values,
    match_field_pattern,
    value_as_pattern_text,
)
from cmdb.models.type_model import FieldType, TEXT_VALUE_MAX_LENGTH, TEXTAREA_VALUE_MAX_LENGTH
# -------------------------------------------------------------------------------------------------------------------- #

TEXT_FIELD: str = 'a-text'
NOTES_FIELD: str = 'a-notes'
CODE_FIELD: str = 'a-code'          # text field with a pattern
NUMBER_FIELD: str = 'a-number'      # number field with a pattern, no cap
FLAG_FIELD: str = 'a-flag'          # checkbox: neither a cap nor a pattern
MDS_SECTION: str = 'rows'

CODE_REGEX: str = '[A-Z]{3}'
NUMBER_REGEX: str = r'\d{2}'
UNCOMPILABLE_REGEX: str = '\\u{1F600}'   # a JavaScript code-point escape the regex engine does not read
JS_NAMED_GROUP_REGEX: str = '(?<code>[A-Z]{2})'   # JavaScript's named group: `re` refused it, `regex` reads it


def _type_fields() -> list[dict[str, Any]]:
    """A type's fields: one of each rule shape."""
    return [
        {'type': FieldType.TEXT.value, 'name': TEXT_FIELD},
        {'type': FieldType.TEXTAREA.value, 'name': NOTES_FIELD},
        {'type': FieldType.TEXT.value, 'name': CODE_FIELD, 'regex': CODE_REGEX},
        {'type': FieldType.NUMBER.value, 'name': NUMBER_FIELD, 'regex': NUMBER_REGEX},
        {'type': FieldType.CHECKBOX.value, 'name': FLAG_FIELD},
    ]


def _object(fields: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A CmdbObject document with the given top-level values and MDS rows (each a {name: value} dict)."""
    document: dict[str, Any] = {
        'fields': [{'name': name, 'value': value} for name, value in (fields or {}).items()],
    }

    if rows is not None:
        document['multi_data_sections'] = [{
            'section_id': MDS_SECTION,
            'values': [
                {'multi_data_id': index, 'data': [{'name': name, 'value': value} for name, value in row.items()]}
                for index, row in enumerate(rows)
            ],
        }]

    return document


def _errors(document: dict[str, Any], previous: dict[str, Any] | None = None) -> list[str]:
    """The errors the rules of _type_fields() report for a document."""
    return collect_object_value_errors(document, build_field_value_rules(_type_fields()), previous)


class TestTheAnchors:
    """A pattern is anchored the way Angular's Validators.pattern anchors a string pattern."""

    @pytest.mark.parametrize('regex, expected', [
        ('abc', '^abc$'),
        ('^abc', '^abc$'),
        ('abc$', '^abc$'),
        ('^abc$', '^abc$'),
        ('a|b', '^a|b$'),
    ], ids=['bare', 'start-given', 'end-given', 'both-given', 'alternation-not-wrapped'])
    def test_anchors_are_added_only_where_missing(self, regex: str, expected: str) -> None:
        """Nothing else is added - an alternation stays unwrapped, exactly like the form"""
        assert anchor_field_regex(regex) == expected

    def test_an_unwrapped_alternation_behaves_like_the_form(self) -> None:
        """'^a|b$' matches anything starting with a or ending with b - the form's own reading"""
        rule = FieldValueRule(pattern=compile_field_regex(CODE_FIELD, 'a|b'), regex='a|b')

        assert find_value_errors(CODE_FIELD, 'axxx', rule) == []
        assert find_value_errors(CODE_FIELD, 'xxxb', rule) == []
        assert find_value_errors(CODE_FIELD, 'xax', rule) != []


class TestCompileFieldRegex:
    """What a declared regex compiles to."""

    @pytest.mark.parametrize('regex', [None, '', 42, ['x']], ids=['none', 'empty', 'number', 'list'])
    def test_no_usable_regex_is_no_pattern(self, regex: Any) -> None:
        """Only a non-empty string declares a pattern"""
        assert compile_field_regex(CODE_FIELD, regex) is None

    def test_a_javascript_named_group_compiles_and_is_enforced(self) -> None:
        """`re` could not read `(?<name>...)` and skipped the field; the regex engine reads it as the browser does"""
        rule = FieldValueRule(pattern=compile_field_regex(CODE_FIELD, JS_NAMED_GROUP_REGEX), regex=JS_NAMED_GROUP_REGEX)

        assert rule.pattern is not None
        assert not find_value_errors(CODE_FIELD, 'DE', rule)
        assert find_value_errors(CODE_FIELD, 'de', rule)

    def test_an_uncompilable_regex_is_skipped_with_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Failing every write of the type over it would be worse than not checking it"""
        with caplog.at_level(logging.WARNING):
            assert compile_field_regex(CODE_FIELD, UNCOMPILABLE_REGEX) is None

        assert CODE_FIELD in caplog.text


class TestBuildFieldValueRules:
    """Which fields get a rule."""

    def test_the_caps_follow_the_field_kind(self) -> None:
        """Text and textarea are capped; a number, a checkbox are not"""
        rules = build_field_value_rules(_type_fields())

        assert rules[TEXT_FIELD].max_length == TEXT_VALUE_MAX_LENGTH
        assert rules[NOTES_FIELD].max_length == TEXTAREA_VALUE_MAX_LENGTH
        assert rules[NUMBER_FIELD].max_length is None

    def test_a_field_with_neither_rule_is_left_out(self) -> None:
        """A checkbox without a pattern has nothing to judge"""
        assert FLAG_FIELD not in build_field_value_rules(_type_fields())

    def test_the_declared_regex_is_kept_for_the_message(self) -> None:
        """The message quotes the regex as the type builder shows it, not the anchored form"""
        assert build_field_value_rules(_type_fields())[CODE_FIELD].regex == CODE_REGEX

    def test_an_uncompilable_regex_leaves_the_cap(self) -> None:
        """The field keeps its kind's cap, and no regex is quoted for a pattern that is not applied"""
        rules = build_field_value_rules([{'type': 'text', 'name': CODE_FIELD, 'regex': UNCOMPILABLE_REGEX}])

        assert rules[CODE_FIELD] == FieldValueRule(max_length=TEXT_VALUE_MAX_LENGTH)

    @pytest.mark.parametrize('type_fields', [None, []], ids=['none', 'empty'])
    def test_no_fields_no_rules(self, type_fields: Any) -> None:
        """A type without fields has nothing to enforce"""
        assert build_field_value_rules(type_fields) == {}


class TestValueAsPatternText:
    """How a value is spelled for the pattern test."""

    @pytest.mark.parametrize('value, expected', [
        ('abc', 'abc'), (12, '12'), (5.0, '5'), (2.5, '2.5'),
    ], ids=['string', 'int', 'whole-float-as-javascript', 'fraction'])
    def test_strings_and_numbers_are_tested(self, value: Any, expected: str) -> None:
        """A number reads the way JavaScript's String() prints it"""
        assert value_as_pattern_text(value) == expected

    @pytest.mark.parametrize('value', [True, False, ['x'], {'$date': 1}], ids=['true', 'false', 'list', 'date'])
    def test_other_shapes_are_not_tested(self, value: Any) -> None:
        """A boolean is not the number it subclasses; lists and dates are no text"""
        assert value_as_pattern_text(value) is None


class TestHasNoValue:
    """What the rules leave to the required-field rule."""

    @pytest.mark.parametrize('value', [None, '', []], ids=['none', 'empty-string', 'empty-list'])
    def test_nothing_is_judged(self, value: Any) -> None:
        """No value breaks no cap and no pattern"""
        assert has_no_value(value)

    @pytest.mark.parametrize('value', [0, False, ' '], ids=['zero', 'false', 'blank'])
    def test_falsy_values_are_values(self, value: Any) -> None:
        """0, False and a blank are values like any other"""
        assert not has_no_value(value)


class TestFindValueErrors:
    """One value against one rule."""

    def test_the_cap_itself_is_allowed(self) -> None:
        """At most, not fewer than"""
        rule = FieldValueRule(max_length=TEXT_VALUE_MAX_LENGTH)

        assert find_value_errors(TEXT_FIELD, 'x' * TEXT_VALUE_MAX_LENGTH, rule) == []

    def test_one_character_over_the_cap_is_refused(self) -> None:
        """The message names the field, the length and the cap"""
        rule = FieldValueRule(max_length=TEXT_VALUE_MAX_LENGTH)

        assert find_value_errors(TEXT_FIELD, 'x' * (TEXT_VALUE_MAX_LENGTH + 1), rule) == [
            FieldValueError.TOO_LONG.format(
                field=TEXT_FIELD, length=TEXT_VALUE_MAX_LENGTH + 1, max_length=TEXT_VALUE_MAX_LENGTH,
            ),
        ]

    def test_a_mismatch_names_the_declared_regex(self) -> None:
        """The regex the user wrote, not the anchored one"""
        rule = build_field_value_rules(_type_fields())[CODE_FIELD]

        assert find_value_errors(CODE_FIELD, 'abc', rule) == [
            FieldValueError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=CODE_REGEX),
        ]

    def test_a_match_passes(self) -> None:
        """The anchored pattern must cover the whole value"""
        rule = build_field_value_rules(_type_fields())[CODE_FIELD]

        assert find_value_errors(CODE_FIELD, 'ABC', rule) == []
        assert find_value_errors(CODE_FIELD, 'ABCD', rule) != []

    def test_both_rules_are_reported_together(self) -> None:
        """A value too long and not matching gets both messages"""
        rule = build_field_value_rules(_type_fields())[CODE_FIELD]

        assert len(find_value_errors(CODE_FIELD, 'x' * (TEXT_VALUE_MAX_LENGTH + 1), rule)) == 2

    def test_a_number_is_pattern_checked(self) -> None:
        """A number field's pattern is tested on the number's text"""
        rule = build_field_value_rules(_type_fields())[NUMBER_FIELD]

        assert find_value_errors(NUMBER_FIELD, 42, rule) == []
        assert find_value_errors(NUMBER_FIELD, 7, rule) != []

    @pytest.mark.parametrize('value', [None, '', []], ids=['none', 'empty-string', 'empty-list'])
    def test_no_value_passes_every_rule(self, value: Any) -> None:
        """Even a pattern the empty string does not match"""
        assert find_value_errors(CODE_FIELD, value, build_field_value_rules(_type_fields())[CODE_FIELD]) == []


class TestIterObjectValues:
    """Where the values of an object are read from."""

    def test_the_top_level_list_and_every_row(self) -> None:
        """Both places, each value with its place"""
        document = _object({TEXT_FIELD: 'a'}, rows=[{TEXT_FIELD: 'b'}, {TEXT_FIELD: 'c'}])

        assert iter_object_values(document) == [
            (None, TEXT_FIELD, 'a'), (MDS_SECTION, TEXT_FIELD, 'b'), (MDS_SECTION, TEXT_FIELD, 'c'),
        ]

    @pytest.mark.parametrize('document', [
        None, {}, {'fields': None}, {'fields': ['x']},
        {'multi_data_sections': ['x']}, {'multi_data_sections': [{'values': ['x']}]},
    ], ids=['none', 'empty', 'null-fields', 'non-dict-entry', 'non-dict-section', 'non-dict-row'])
    def test_malformed_shapes_are_skipped(self, document: Any) -> None:
        """Their shape is the object schema's to refuse; the rules only judge values"""
        assert iter_object_values(document) == []

    def test_stored_values_are_grouped_by_place_and_field(self) -> None:
        """Every row's value is kept"""
        stored = collect_stored_values(_object({TEXT_FIELD: 'a'}, rows=[{TEXT_FIELD: 'b'}, {TEXT_FIELD: 'c'}]))

        assert stored == {(None, TEXT_FIELD): ['a'], (MDS_SECTION, TEXT_FIELD): ['b', 'c']}


class TestCollectObjectValueErrors:
    """A whole candidate object."""

    def test_a_valid_object_passes(self) -> None:
        """Every rule met"""
        assert _errors(_object({TEXT_FIELD: 'a', NOTES_FIELD: 'n', CODE_FIELD: 'ABC', NUMBER_FIELD: 10})) == []

    def test_the_textarea_cap_is_the_larger_one(self) -> None:
        """A note longer than a text cap is fine; one past the textarea cap is not"""
        assert _errors(_object({NOTES_FIELD: 'x' * (TEXT_VALUE_MAX_LENGTH + 1)})) == []
        assert _errors(_object({NOTES_FIELD: 'x' * (TEXTAREA_VALUE_MAX_LENGTH + 1)})) != []

    def test_an_mds_row_value_is_judged_and_names_the_section(self) -> None:
        """The message says which section's rows hold it"""
        errors = _errors(_object(rows=[{CODE_FIELD: 'abc'}]))

        assert errors == [
            FieldValueError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=CODE_REGEX)
            + MDS_SECTION_SUFFIX.format(section_id=MDS_SECTION),
        ]

    def test_a_message_repeated_by_several_rows_is_reported_once(self) -> None:
        """Ten bad rows of the same field are one problem to fix"""
        assert len(_errors(_object(rows=[{CODE_FIELD: 'abc'}, {CODE_FIELD: 'abc'}]))) == 1

    def test_a_field_the_type_does_not_declare_is_not_judged(self) -> None:
        """Whether it may be there at all is the object write's other check"""
        assert _errors(_object({'undeclared': 'x' * (TEXTAREA_VALUE_MAX_LENGTH + 1)})) == []

    def test_no_rules_nothing_to_judge(self) -> None:
        """A type without capped or patterned fields"""
        assert collect_object_value_errors(_object({TEXT_FIELD: 'x' * 1000}), {}) == []


class TestTheStoredValueIsNotJudged:
    """An update answers for what it changes."""

    def test_an_unchanged_oversized_value_passes(self) -> None:
        """Stored before the cap existed: the object can still be edited elsewhere"""
        long_value: str = 'x' * (TEXT_VALUE_MAX_LENGTH + 1)
        previous = _object({TEXT_FIELD: long_value})

        assert _errors(_object({TEXT_FIELD: long_value, CODE_FIELD: 'ABC'}), previous) == []

    def test_a_changed_value_is_judged(self) -> None:
        """Changing it means it must meet the rule"""
        previous = _object({TEXT_FIELD: 'x' * (TEXT_VALUE_MAX_LENGTH + 1)})

        assert _errors(_object({TEXT_FIELD: 'y' * (TEXT_VALUE_MAX_LENGTH + 1)}), previous) != []

    def test_a_value_moved_to_another_field_is_judged(self) -> None:
        """Unchanged means the same field in the same place"""
        previous = _object({TEXT_FIELD: 'abc'})

        assert _errors(_object({CODE_FIELD: 'abc'}), previous) != []

    def test_a_row_value_counts_as_stored_in_any_row_of_its_section(self) -> None:
        """Rows can be reordered or added; a value some row already held is not new"""
        previous = _object(rows=[{CODE_FIELD: 'abc'}])

        assert _errors(_object(rows=[{CODE_FIELD: 'ABC'}, {CODE_FIELD: 'abc'}]), previous) == []

    def test_a_top_level_value_does_not_excuse_a_row(self) -> None:
        """The flat list and the rows are different places"""
        previous = _object({CODE_FIELD: 'abc'})

        assert _errors(_object(rows=[{CODE_FIELD: 'abc'}]), previous) != []


class TestFindDefaultValueErrors:
    """A field's declared default, judged by the field's own rules."""

    def test_a_default_over_the_cap_is_named(self) -> None:
        """Worded about the default, not about a value"""
        default: str = 'x' * (TEXT_VALUE_MAX_LENGTH + 1)

        assert find_default_value_errors([{'type': 'text', 'name': TEXT_FIELD, 'value': default}]) == {
            TEXT_FIELD: [FieldDefaultError.TOO_LONG.format(
                field=TEXT_FIELD, length=len(default), max_length=TEXT_VALUE_MAX_LENGTH,
            )],
        }

    def test_a_default_breaking_its_own_regex_is_named(self) -> None:
        """The declared regex is quoted"""
        errors = find_default_value_errors([{'type': 'text', 'name': CODE_FIELD, 'regex': CODE_REGEX, 'value': 'abc'}])

        assert errors == {CODE_FIELD: [FieldDefaultError.PATTERN_MISMATCH.format(field=CODE_FIELD, regex=CODE_REGEX)]}

    @pytest.mark.parametrize('field', [
        {'type': 'text', 'name': CODE_FIELD, 'regex': CODE_REGEX, 'value': 'ABC'},
        {'type': 'text', 'name': CODE_FIELD, 'regex': CODE_REGEX},
        {'type': 'text', 'name': CODE_FIELD, 'regex': UNCOMPILABLE_REGEX, 'value': 'anything'},
        {'type': 'checkbox', 'name': FLAG_FIELD, 'value': True},
    ], ids=['matching', 'no-default', 'uncompilable-regex-skipped', 'no-rule'])
    def test_a_passing_or_unjudged_default_is_not_named(self, field: dict[str, Any]) -> None:
        """The same skips the object write makes"""
        assert find_default_value_errors([field]) == {}

    def test_both_rules_are_reported_for_one_default(self) -> None:
        """Over the cap and not matching"""
        rule = build_field_value_rules(_type_fields())[CODE_FIELD]

        assert len(find_default_errors(CODE_FIELD, 'x' * (TEXT_VALUE_MAX_LENGTH + 1), rule)) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the time limit                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
BACKTRACKING_REGEX: str = '(a|aa)+b'          # Fibonacci backtracking - hours on 60 characters without a limit
BACKTRACKING_VALUE: str = 'a' * 60
BACKTRACKING_FIELDS: int = 25                 # enough patterned fields to add per-match timeouts past the budget
WALL_CLOCK_MARGIN_SECONDS: float = 0.5


class _FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now: float = 100.0

    def __call__(self) -> float:
        return self.now


def _backtracking_rule() -> FieldValueRule:
    """The rule of a text field declaring the backtracking pattern."""
    return build_field_value_rules([{'type': 'text', 'name': CODE_FIELD, 'regex': BACKTRACKING_REGEX}])[CODE_FIELD]


class TestPatternBudget:
    """The time all the pattern checks of one write may spend."""

    def test_the_next_timeout_is_the_per_match_limit_while_time_is_left(self) -> None:
        """Plenty left: each match gets PATTERN_MATCH_TIMEOUT_SECONDS"""
        budget = PatternBudget(seconds=PATTERN_WRITE_BUDGET_SECONDS, clock=_FakeClock())

        assert budget.next_timeout() == PATTERN_MATCH_TIMEOUT_SECONDS
        assert not budget.exhausted

    def test_the_next_timeout_shrinks_to_what_is_left(self) -> None:
        """Near the end of the budget a match gets only the rest"""
        clock = _FakeClock()
        budget = PatternBudget(seconds=PATTERN_WRITE_BUDGET_SECONDS, clock=clock)
        clock.now += PATTERN_WRITE_BUDGET_SECONDS - PATTERN_MATCH_TIMEOUT_SECONDS / 4

        assert budget.next_timeout() == pytest.approx(PATTERN_MATCH_TIMEOUT_SECONDS / 4)

    def test_a_spent_budget_answers_none_and_is_exhausted(self) -> None:
        """Nothing left: no timeout to run with, and the budget says so from then on"""
        clock = _FakeClock()
        budget = PatternBudget(seconds=PATTERN_WRITE_BUDGET_SECONDS, clock=clock)
        clock.now += PATTERN_WRITE_BUDGET_SECONDS

        assert budget.next_timeout() is None
        assert budget.exhausted

    def test_an_exhausted_budget_stays_exhausted(self) -> None:
        """A timed-out match exhausts the budget even with time on the clock"""
        budget = PatternBudget(clock=_FakeClock())
        budget.exhausted = True

        assert budget.next_timeout() is None


class TestMatchFieldPattern:
    """The one place a field pattern runs."""

    def test_match_and_mismatch(self) -> None:
        """An ordinary pattern decides"""
        rule = FieldValueRule(pattern=compile_field_regex(CODE_FIELD, CODE_REGEX), regex=CODE_REGEX)

        assert match_field_pattern(rule, 'ABC', PatternBudget(), CODE_FIELD) == PatternVerdict.MATCH
        assert match_field_pattern(rule, 'abc', PatternBudget(), CODE_FIELD) == PatternVerdict.MISMATCH

    def test_a_backtracking_pattern_times_out_within_its_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        """The defect: unlimited, this match runs for hours; now it answers TIMED_OUT in about the per-match limit"""
        budget = PatternBudget()

        with caplog.at_level(logging.WARNING):
            started: float = time.monotonic()
            verdict = match_field_pattern(_backtracking_rule(), BACKTRACKING_VALUE, budget, CODE_FIELD)
            elapsed: float = time.monotonic() - started

        assert verdict == PatternVerdict.TIMED_OUT
        assert elapsed < PATTERN_MATCH_TIMEOUT_SECONDS + WALL_CLOCK_MARGIN_SECONDS
        assert budget.exhausted
        assert BACKTRACKING_REGEX in caplog.text and CODE_FIELD in caplog.text

    def test_an_exhausted_budget_runs_nothing(self) -> None:
        """Once spent, the pattern is not even called"""
        pattern = MagicMock(name='pattern')
        budget = PatternBudget()
        budget.exhausted = True

        verdict = match_field_pattern(FieldValueRule(pattern=pattern, regex='x'), 'x', budget, CODE_FIELD)

        assert verdict == PatternVerdict.TIMED_OUT
        pattern.search.assert_not_called()

    def test_the_match_runs_with_the_budgets_timeout(self) -> None:
        """The engine is handed the timeout - the limit is not a wish"""
        pattern = MagicMock(name='pattern')
        pattern.search.return_value = object()

        match_field_pattern(FieldValueRule(pattern=pattern, regex='x'), 'x', PatternBudget(), CODE_FIELD)

        assert pattern.search.call_args.kwargs['timeout'] == PATTERN_MATCH_TIMEOUT_SECONDS


class TestTheTimedOutAnswer:
    """A timed-out value is refused with its own message - not called a mismatch, not let through."""

    def test_a_value_gets_the_timeout_message(self) -> None:
        """The value message set"""
        assert find_value_errors(CODE_FIELD, BACKTRACKING_VALUE, _backtracking_rule()) == [
            FieldValueError.PATTERN_TIMEOUT.format(field=CODE_FIELD, regex=BACKTRACKING_REGEX),
        ]

    def test_a_default_gets_the_default_wording(self) -> None:
        """The default message set"""
        assert find_default_errors(CODE_FIELD, BACKTRACKING_VALUE, _backtracking_rule()) == [
            FieldDefaultError.PATTERN_TIMEOUT.format(field=CODE_FIELD, regex=BACKTRACKING_REGEX),
        ]

    def test_a_matching_value_of_the_same_pattern_passes(self) -> None:
        """Only the pathological input runs out of time; a short value decides normally"""
        assert not find_value_errors(CODE_FIELD, 'aab', _backtracking_rule())

    def test_the_length_cap_is_still_reported_beside_it(self) -> None:
        """The cap is judged first and independently"""
        errors = find_value_errors(CODE_FIELD, 'a' * (TEXT_VALUE_MAX_LENGTH + 1), _backtracking_rule())

        assert errors[0].startswith(FieldValueError.TOO_LONG.format(
            field=CODE_FIELD, length=TEXT_VALUE_MAX_LENGTH + 1, max_length=TEXT_VALUE_MAX_LENGTH,
        )[:20])
        assert errors[1] == FieldValueError.PATTERN_TIMEOUT.format(field=CODE_FIELD, regex=BACKTRACKING_REGEX)


class TestOneBudgetPerWrite:
    """Many patterned fields cannot add their timeouts up."""

    @staticmethod
    def _many_backtracking_fields() -> tuple[dict[str, Any], dict[str, FieldValueRule]]:
        names: list[str] = [f'field-{index}' for index in range(BACKTRACKING_FIELDS)]
        rules = build_field_value_rules([
            {'type': 'text', 'name': name, 'regex': BACKTRACKING_REGEX} for name in names
        ])

        return _object({name: BACKTRACKING_VALUE for name in names}), rules

    def test_an_object_write_stops_at_the_first_time_out(self) -> None:
        """25 x 0.1 s would be 2.5 s; one write spends about one per-match timeout, then runs nothing"""
        document, rules = self._many_backtracking_fields()

        started: float = time.monotonic()
        errors = collect_object_value_errors(document, rules)
        elapsed: float = time.monotonic() - started

        assert elapsed < PATTERN_MATCH_TIMEOUT_SECONDS + WALL_CLOCK_MARGIN_SECONDS
        assert len(errors) == BACKTRACKING_FIELDS
        assert all('in time' in message for message in errors)

    def test_the_defaults_of_one_type_share_a_budget(self) -> None:
        """The same bound on the type write's default check"""
        names: list[str] = [f'field-{index}' for index in range(BACKTRACKING_FIELDS)]
        fields = [{'type': 'text', 'name': name, 'regex': BACKTRACKING_REGEX, 'value': BACKTRACKING_VALUE}
                  for name in names]

        started: float = time.monotonic()
        errors = find_default_value_errors(fields)
        elapsed: float = time.monotonic() - started

        assert elapsed < PATTERN_MATCH_TIMEOUT_SECONDS + WALL_CLOCK_MARGIN_SECONDS
        assert set(errors) == set(names)

    def test_each_write_starts_its_own_budget(self) -> None:
        """A timed-out write does not spend the next one's budget"""
        collect_object_value_errors(_object({CODE_FIELD: BACKTRACKING_VALUE}),
                                    {CODE_FIELD: _backtracking_rule()})
        rule = FieldValueRule(pattern=compile_field_regex(CODE_FIELD, CODE_REGEX), regex=CODE_REGEX)

        assert not collect_object_value_errors(_object({CODE_FIELD: 'ABC'}), {CODE_FIELD: rule})
