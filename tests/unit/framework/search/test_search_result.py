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
Unit tests for SearchResult and its field-matching helpers

The matcher is pure: it walks the `fields` list of a rendered result, tests every value against the
compiled search patterns, and reports the matching field entries. Everything here works on plain
dicts and a minimal result stub - no Mongo, no Flask, no manager.
"""
import re
from typing import Any

import pytest

from cmdb.framework.search.search_constants import (
    SEARCH_REGEX_RE_FLAGS,
    SearchResultKey,
    SearchResultMapKey,
)
from cmdb.framework.search.search_result import (
    MAX_REFERENCE_DEPTH,
    SearchResult,
    append_unique,
    collect_matching_fields,
    compile_search_pattern,
    compile_search_patterns,
    field_value_matches,
    get_reference_expansion,
)
from cmdb.framework.search.search_result_map import SearchResultMap
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

# The walk helpers are documented to return a list, never None: asserting `== []` rather than
# falsiness is what pins that half of the contract, so the implicit-booleaness hint does not apply
# pylint: disable=use-implicit-booleaness-not-comparison

TOTAL_RESULTS: int = 42
LIMIT: int = 10
SKIP: int = 20

MATCHING_VALUE: str = 'hello'
OTHER_VALUE: str = 'world'
UNMATCHED_PATTERN: str = 'no-such-value-xyz'
INVALID_PATTERN: str = '[unclosed'


def make_field(name: str, value: Any, field_type: str = FieldType.TEXT, **extra: Any) -> dict[str, Any]:
    """Builds a rendered field entry, optionally carrying a reference expansion."""
    return {'name': name, 'label': name.title(), 'type': field_type, 'value': value, **extra}


def make_reference_field(name: str, value: Any, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a rendered `ref` field carrying the referenced object's summary fields."""
    return make_field(name, value, FieldType.REFERENCE, reference={'summaries': summaries})


def make_ref_section_field(name: str, value: Any, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a rendered `ref-section-field` carrying the pulled-in section fields."""
    return make_field(name, value, FieldType.REF_SECTION, references={'fields': fields})


class ResultStub:
    """Minimal stand-in for a RenderResult: the matcher only reads `fields`, to_json only serializes."""

    def __init__(self, fields: list[dict[str, Any]]) -> None:
        self.fields = fields

    def to_json(self) -> dict[str, Any]:
        """Mirrors RenderResult.to_json so SearchResultMap can serialize the stub."""
        return {'fields': self.fields}


def patterns_for(*raw_patterns: str) -> list[re.Pattern]:
    """Compiles the given raw patterns the way SearchResult does."""
    return compile_search_patterns(list(raw_patterns))


# -------------------------------------------------------------------------------------------------------------------- #
#                                             compile_search_pattern                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCompileSearchPattern:
    """A raw `$regex` value becomes a compiled pattern, or an escaped literal when it cannot compile."""

    def test_compiles_a_valid_regex(self) -> None:
        """A well-formed pattern compiles into a usable regex."""
        pattern = compile_search_pattern('he.lo')

        assert pattern.search('hello') is not None

    def test_is_case_insensitive_multiline_and_dotall(self) -> None:
        """The 'ims' flags are applied, so casing and newlines do not defeat a match."""
        pattern = compile_search_pattern('he.lo')

        assert pattern.search('HE\nLO') is not None

    def test_invalid_regex_falls_back_to_a_literal_match(self) -> None:
        """A malformed pattern matches its own text literally instead of matching nothing."""
        pattern = compile_search_pattern(INVALID_PATTERN)

        assert pattern.search(f'value {INVALID_PATTERN} here') is not None

    def test_invalid_regex_does_not_match_unrelated_text(self) -> None:
        """The literal fallback stays a real matcher rather than matching everything."""
        pattern = compile_search_pattern(INVALID_PATTERN)

        assert pattern.search('completely unrelated') is None

    def test_non_string_pattern_falls_back_to_a_literal_match(self) -> None:
        """A non-str `$regex` value is stringified and matched literally rather than raising."""
        pattern = compile_search_pattern(42)

        assert pattern.search('answer is 42') is not None

    def test_literal_fallback_uses_the_same_flags(self) -> None:
        """The fallback carries the flags a successful compile would have applied."""
        pattern = compile_search_pattern(INVALID_PATTERN)

        assert pattern.flags & SEARCH_REGEX_RE_FLAGS == SEARCH_REGEX_RE_FLAGS


class TestCompileSearchPatterns:
    """The list form compiles every pattern once, up front."""

    def test_compiles_each_pattern(self) -> None:
        """Every raw pattern yields one compiled pattern."""
        assert len(compile_search_patterns(['a', 'b', 'c'])) == 3

    @pytest.mark.parametrize('raw_patterns', [None, []])
    def test_empty_input_yields_no_patterns(self, raw_patterns) -> None:
        """No patterns in means no patterns out, for both None and the empty list."""
        assert compile_search_patterns(raw_patterns) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              field_value_matches                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFieldValueMatches:
    """A field matches when any pattern hits its stringified value."""

    def test_matches_on_value(self) -> None:
        """A pattern contained in the value matches."""
        assert field_value_matches(make_field('a', MATCHING_VALUE), patterns_for('hell')) is True

    def test_does_not_match_other_values(self) -> None:
        """A pattern absent from the value does not match."""
        assert field_value_matches(make_field('a', MATCHING_VALUE), patterns_for(UNMATCHED_PATTERN)) is False

    def test_matches_case_insensitively(self) -> None:
        """Casing is irrelevant."""
        assert field_value_matches(make_field('a', 'HeLLo'), patterns_for(MATCHING_VALUE)) is True

    def test_stringifies_non_string_values(self) -> None:
        """A numeric value is searchable because the value is stringified first."""
        assert field_value_matches(make_field('n', 42, FieldType.NUMBER), patterns_for('42')) is True

    def test_any_pattern_is_enough(self) -> None:
        """Only one of several patterns needs to hit."""
        patterns = patterns_for(UNMATCHED_PATTERN, 'hell')

        assert field_value_matches(make_field('a', MATCHING_VALUE), patterns) is True

    def test_no_patterns_never_matches(self) -> None:
        """With nothing to match against, nothing matches."""
        assert field_value_matches(make_field('a', MATCHING_VALUE), []) is False

    def test_field_without_a_value_key_never_matches(self) -> None:
        """A field carrying no value holds no text to search, so it cannot match."""
        assert field_value_matches({'name': 'a', 'type': FieldType.TEXT}, patterns_for('none')) is False

    def test_explicit_none_value_never_matches(self) -> None:
        """An empty field is not searchable as the literal text 'None'."""
        assert field_value_matches(make_field('a', None), patterns_for('none')) is False

    def test_empty_field_does_not_match_an_empty_pattern(self) -> None:
        """Not even a pattern that matches anything makes an unset value searchable."""
        assert field_value_matches(make_field('a', None), patterns_for('')) is False

    @pytest.mark.parametrize(
        'value, search_text',
        [(0, '0'), (False, 'false'), ('', ''), (0.0, '0.0')],
        ids=['zero', 'false', 'empty-string', 'zero-float'],
    )
    def test_falsy_but_present_values_are_still_searchable(self, value, search_text) -> None:
        """Only None counts as absent - a falsy value is matched on its own text."""
        assert field_value_matches(make_field('a', value), patterns_for(search_text)) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_reference_expansion                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetReferenceExpansion:
    """Only reference-like fields expand, and only when the renderer resolved them."""

    def test_plain_field_has_no_expansion(self) -> None:
        """A text field never expands."""
        assert get_reference_expansion(make_field('a', MATCHING_VALUE)) == []

    def test_reference_field_yields_its_summaries(self) -> None:
        """A `ref` field expands into the referenced object's summary fields."""
        summary = make_field('s', OTHER_VALUE)

        assert get_reference_expansion(make_reference_field('r', 1, [summary])) == [summary]

    def test_ref_section_field_yields_its_pulled_fields(self) -> None:
        """A `ref-section-field` expands into the pulled-in section fields."""
        pulled = make_field('p', OTHER_VALUE)

        assert get_reference_expansion(make_ref_section_field('rs', 1, [pulled])) == [pulled]

    def test_unresolved_reference_yields_nothing(self) -> None:
        """A `ref` field the renderer could not resolve carries no expansion key at all."""
        assert get_reference_expansion(make_field('r', 1, FieldType.REFERENCE)) == []

    def test_null_expansion_yields_nothing(self) -> None:
        """An expansion explicitly set to None is treated as absent, not subscripted."""
        assert get_reference_expansion(make_field('r', 1, FieldType.REFERENCE, reference=None)) == []

    def test_non_dict_expansion_yields_nothing(self) -> None:
        """A malformed expansion of the wrong type is ignored rather than raising."""
        assert get_reference_expansion(make_field('r', 1, FieldType.REFERENCE, reference=['bad'])) == []

    def test_non_list_nested_fields_yield_nothing(self) -> None:
        """A malformed summaries entry of the wrong type is ignored rather than raising."""
        field = make_field('r', 1, FieldType.REFERENCE, reference={'summaries': 'bad'})

        assert get_reference_expansion(field) == []

    def test_field_without_a_type_yields_nothing(self) -> None:
        """A field entry missing its type key is treated as a plain field."""
        assert get_reference_expansion({'name': 'a', 'value': MATCHING_VALUE}) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 append_unique                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAppendUnique:
    """Matches are recorded at most once, compared by equality."""

    def test_appends_a_new_entry(self) -> None:
        """An unseen field is appended."""
        matched: list[dict[str, Any]] = []
        append_unique(matched, make_field('a', MATCHING_VALUE))

        assert len(matched) == 1

    def test_skips_an_equal_entry(self) -> None:
        """A field equal to one already recorded is not appended again."""
        matched = [make_field('a', MATCHING_VALUE)]
        append_unique(matched, make_field('a', MATCHING_VALUE))

        assert len(matched) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_matching_fields                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectMatchingFields:
    """The walk over a field list, including reference expansions."""

    def test_returns_the_matching_field(self) -> None:
        """A matching field is reported."""
        matching = make_field('a', MATCHING_VALUE)
        fields = [matching, make_field('b', OTHER_VALUE)]

        assert collect_matching_fields(fields, patterns_for(MATCHING_VALUE)) == [matching]

    def test_returns_nothing_when_no_field_matches(self) -> None:
        """A search term absent from every field yields no matches."""
        fields = [make_field('a', MATCHING_VALUE)]

        assert collect_matching_fields(fields, patterns_for(UNMATCHED_PATTERN)) == []

    def test_reports_matches_in_field_order(self) -> None:
        """Several patterns matching different fields report in field order, not pattern order."""
        first = make_field('a', MATCHING_VALUE)
        second = make_field('b', OTHER_VALUE)

        matched = collect_matching_fields([first, second], patterns_for(OTHER_VALUE, MATCHING_VALUE))

        assert matched == [first, second]

    def test_deduplicates_a_field_hit_by_several_patterns(self) -> None:
        """A field matched by two patterns is reported once."""
        matching = make_field('a', MATCHING_VALUE)

        assert collect_matching_fields([matching], patterns_for('hel', 'llo')) == [matching]

    def test_skips_non_dict_entries(self) -> None:
        """A malformed entry in the field list is skipped rather than raising."""
        matching = make_field('a', MATCHING_VALUE)

        assert collect_matching_fields(['not-a-field', matching], patterns_for(MATCHING_VALUE)) == [matching]

    def test_empty_field_list_yields_nothing(self) -> None:
        """Nothing to walk means nothing to report."""
        assert collect_matching_fields([], patterns_for(MATCHING_VALUE)) == []


class TestCollectMatchingFieldsReferences:
    """A match inside a reference expansion is attributed to the field carrying the expansion."""

    def test_nested_match_reports_the_parent_field(self) -> None:
        """A hit in a referenced object's summary reports the `ref` field, not the nested field."""
        parent = make_reference_field('r', 1, [make_field('s', MATCHING_VALUE)])

        assert collect_matching_fields([parent], patterns_for(MATCHING_VALUE)) == [parent]

    def test_ref_section_nested_match_reports_the_parent_field(self) -> None:
        """A hit in a pulled-in section field reports the `ref-section-field`."""
        parent = make_ref_section_field('rs', 1, [make_field('p', MATCHING_VALUE)])

        assert collect_matching_fields([parent], patterns_for(MATCHING_VALUE)) == [parent]

    def test_parent_matching_itself_and_nested_is_reported_once(self) -> None:
        """When both the reference value and a nested value match, the parent appears once."""
        parent = make_reference_field('r', MATCHING_VALUE, [make_field('s', MATCHING_VALUE)])

        assert collect_matching_fields([parent], patterns_for(MATCHING_VALUE)) == [parent]

    def test_several_nested_matches_report_the_parent_once(self) -> None:
        """Two matching summary fields under one reference collapse to a single parent entry."""
        summaries = [make_field('s1', MATCHING_VALUE), make_field('s2', MATCHING_VALUE)]
        parent = make_reference_field('r', 1, summaries)

        assert collect_matching_fields([parent], patterns_for(MATCHING_VALUE)) == [parent]

    def test_attribution_is_to_the_immediate_parent_only(self) -> None:
        """Two levels down, the hit is reported as the intermediate reference, not the outermost."""
        inner = make_reference_field('r2', 2, [make_field('leaf', MATCHING_VALUE)])
        outer = make_reference_field('r1', 1, [inner])

        assert collect_matching_fields([outer], patterns_for(MATCHING_VALUE)) == [inner]

    def test_unresolved_reference_still_matches_on_its_own_value(self) -> None:
        """A `ref` field with no expansion is still matched on its own value."""
        unresolved = make_field('r', MATCHING_VALUE, FieldType.REFERENCE)

        assert collect_matching_fields([unresolved], patterns_for(MATCHING_VALUE)) == [unresolved]

    def test_stops_at_the_maximum_reference_depth(self) -> None:
        """A cyclic expansion is bounded rather than recursing until a RecursionError."""
        cyclic = make_reference_field('r', 1, [])
        cyclic['reference']['summaries'].append(cyclic)

        assert collect_matching_fields([cyclic], patterns_for(UNMATCHED_PATTERN)) == []

    def test_depth_bound_is_respected_when_called_at_depth(self) -> None:
        """Entering already past the bound returns immediately."""
        fields = [make_field('a', MATCHING_VALUE)]
        matched = collect_matching_fields(fields, patterns_for(MATCHING_VALUE), depth=MAX_REFERENCE_DEPTH + 1)

        assert matched == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                          SearchResult.match_result                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMatchResult:
    """The per-result entry point, which answers None rather than an empty list."""

    def test_returns_none_without_patterns(self) -> None:
        """No patterns means no match list at all."""
        assert SearchResult.match_result(ResultStub([make_field('a', MATCHING_VALUE)]), []) is None

    def test_does_not_touch_the_result_without_patterns(self) -> None:
        """The guard runs before `fields` is read, so a result without fields is fine."""
        assert SearchResult.match_result(object(), []) is None

    def test_returns_none_when_nothing_matched(self) -> None:
        """An empty match list is normalised to None for the frontend's fallback."""
        result = ResultStub([make_field('a', MATCHING_VALUE)])

        assert SearchResult.match_result(result, patterns_for(UNMATCHED_PATTERN)) is None

    def test_returns_the_matches(self) -> None:
        """A hit is returned as a list of full field entries."""
        matching = make_field('a', MATCHING_VALUE)

        assert SearchResult.match_result(ResultStub([matching]), patterns_for(MATCHING_VALUE)) == [matching]


class TestFindMatchFields:
    """The raw-pattern entry point compiles for a single result."""

    def test_returns_none_without_patterns(self) -> None:
        """No regex list means no matches."""
        assert SearchResult.find_match_fields(ResultStub([make_field('a', MATCHING_VALUE)])) is None

    def test_returns_the_matches(self) -> None:
        """A raw pattern is compiled and applied."""
        matching = make_field('a', MATCHING_VALUE)
        result = ResultStub([matching])

        assert SearchResult.find_match_fields(result, [MATCHING_VALUE]) == [matching]

    def test_invalid_regex_matches_literally(self) -> None:
        """A malformed pattern finds the field containing that literal text."""
        matching = make_field('a', f'prefix {INVALID_PATTERN} suffix')
        result = ResultStub([matching])

        assert SearchResult.find_match_fields(result, [INVALID_PATTERN]) == [matching]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SearchResult                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def build_search_result(results: list[ResultStub], matches_regex: list[str] | None = None) -> SearchResult:
    """Builds a SearchResult over the given stubs with the standard pagination values."""
    return SearchResult(
        results=results,
        total_results=TOTAL_RESULTS,
        groups=[],
        alive=True,
        limit=LIMIT,
        skip=SKIP,
        matches_regex=matches_regex,
    )


class TestSearchResult:
    """The container wraps each result in a SearchResultMap and serializes the page."""

    def test_wraps_every_result(self) -> None:
        """Each incoming result becomes one SearchResultMap."""
        page = build_search_result([ResultStub([]), ResultStub([])])

        assert all(isinstance(entry, SearchResultMap) for entry in page.results)

    def test_len_is_the_page_size(self) -> None:
        """`len` counts this page, not the database total."""
        page = build_search_result([ResultStub([]), ResultStub([])])

        assert len(page) == 2

    def test_matches_are_none_without_a_regex_list(self) -> None:
        """Without search patterns every entry reports no matches."""
        page = build_search_result([ResultStub([make_field('a', MATCHING_VALUE)])])

        assert page.results[0].matches is None

    def test_matches_are_filled_from_the_regex_list(self) -> None:
        """With a pattern, the matching field is reported on the entry."""
        matching = make_field('a', MATCHING_VALUE)
        page = build_search_result([ResultStub([matching])], [MATCHING_VALUE])

        assert page.results[0].matches == [matching]

    def test_patterns_are_compiled_once_for_the_whole_page(self, monkeypatch) -> None:
        """The compile happens per page, not per result - three results still compile one pattern."""
        calls: list[Any] = []
        original = compile_search_pattern

        def _counting(raw_pattern):
            calls.append(raw_pattern)
            return original(raw_pattern)

        monkeypatch.setattr('cmdb.framework.search.search_result.compile_search_pattern', _counting)
        build_search_result([ResultStub([]) for _ in range(3)], [MATCHING_VALUE])

        assert calls == [MATCHING_VALUE]

    def test_to_json_carries_the_pagination_metadata(self) -> None:
        """The serialized page reports its limit, skip and database total."""
        body = build_search_result([ResultStub([])]).to_json()

        assert (
            body[SearchResultKey.LIMIT.value],
            body[SearchResultKey.SKIP.value],
            body[SearchResultKey.TOTAL_RESULTS.value],
        ) == (LIMIT, SKIP, TOTAL_RESULTS)

    def test_to_json_number_of_results_is_the_page_size(self) -> None:
        """`number_of_results` is this page's length, distinct from `total_results`."""
        body = build_search_result([ResultStub([]), ResultStub([])]).to_json()

        assert body[SearchResultKey.NUMBER_OF_RESULTS.value] == 2

    def test_to_json_exposes_exactly_the_documented_keys(self) -> None:
        """The response shape is a frontend contract, so the key set is pinned."""
        body = build_search_result([]).to_json()

        assert set(body) == {key.value for key in SearchResultKey}

    def test_to_json_results_are_search_result_maps(self) -> None:
        """`results` holds the map objects; the JSON hook converts them on the way out."""
        body = build_search_result([ResultStub([])]).to_json()

        assert isinstance(body[SearchResultKey.RESULTS.value][0], SearchResultMap)

    def test_alive_and_groups_are_kept(self) -> None:
        """Both are passed through untouched for the caller."""
        page = build_search_result([])

        assert (page.alive, page.groups) == (True, [])


class TestSearchResultMapSerialization:
    """The map serializes its result through `to_json`, not through the live `__dict__`."""

    def test_to_json_shape(self) -> None:
        """Both documented keys are present."""
        entry = SearchResultMap(result=ResultStub([]), matches=None)

        assert set(entry.to_json()) == {key.value for key in SearchResultMapKey}

    def test_to_json_delegates_to_the_result(self) -> None:
        """The wrapped result is serialized by its own `to_json`."""
        result = ResultStub([make_field('a', MATCHING_VALUE)])
        entry = SearchResultMap(result=result, matches=None)

        assert entry.to_json()[SearchResultMapKey.RESULT.value] == result.to_json()

    def test_to_json_carries_the_matches(self) -> None:
        """The matched fields are passed through unchanged."""
        matches = [make_field('a', MATCHING_VALUE)]
        entry = SearchResultMap(result=ResultStub([]), matches=matches)

        assert entry.to_json()[SearchResultMapKey.MATCHES.value] == matches

    def test_matches_default_to_none(self) -> None:
        """An entry built without matches reports None, which is the frontend's fallback signal."""
        assert SearchResultMap(result=ResultStub([])).matches is None
