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
Unit tests for cmdb.interface.rest_api.responses.helpers.api_projector.APIProjector

Pure data-in/data-out tests (no Flask app context, no database). Covers pass-through when no
projection is set, include/exclude projection, dotted-path descent into nested dicts and lists,
the memoization of `project`, and the regression cases for the bugs fixed alongside these tests:
uncaught errors on a missing dotted-path segment, mutation of the caller's document on an
exclude-only projection, and cache-defeat on a falsy (empty) projection result.
"""
import pytest

from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector

from cmdb.errors.api_projection import APIProjectionInclusionError
# -------------------------------------------------------------------------------------------------------------------- #

# Field-name constants (avoid repeated string literals across the tests)
PUBLIC_ID: str = 'public_id'
LABEL: str = 'label'
NAME: str = 'name'
SECRET: str = 'secret'
META: str = 'render_meta'
SECTIONS: str = 'sections'
ITEMS: str = 'items'
INCLUDE: int = 1
EXCLUDE: int = 0


def _sample_doc() -> dict:
    """Returns a fresh flat sample document (new object each call so mutation tests are isolated)."""
    return {PUBLIC_ID: 1, LABEL: 'Server', NAME: 'srv', SECRET: 'hidden'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              APIProjector.project                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestProjectPassThrough:
    """With no projection, `project` returns the input data untouched."""

    def test_returns_dict_unchanged_when_no_projection(self) -> None:
        """A None projection makes `project` return the exact same dict object."""
        doc = _sample_doc()

        assert APIProjector(doc).project is doc

    def test_returns_list_unchanged_when_no_projection(self) -> None:
        """A None projection makes `project` return the exact same list object."""
        docs = [_sample_doc(), _sample_doc()]

        assert APIProjector(docs).project is docs


class TestProjectIncludes:
    """Include projections (value 1) keep only the requested keys."""

    def test_include_keeps_only_listed_keys(self) -> None:
        """Only the included top-level keys survive; everything else is dropped."""
        result = APIProjector(_sample_doc(), APIProjection([PUBLIC_ID, LABEL])).project

        assert result == {PUBLIC_ID: 1, LABEL: 'Server'}

    def test_include_as_dict_projection(self) -> None:
        """A dict projection ({key: 1}) behaves the same as the list form."""
        projection = APIProjection({PUBLIC_ID: INCLUDE, NAME: INCLUDE})

        result = APIProjector(_sample_doc(), projection).project

        assert result == {PUBLIC_ID: 1, NAME: 'srv'}

    def test_missing_include_key_is_skipped(self) -> None:
        """An include key absent from the document is silently skipped, not an error."""
        result = APIProjector(_sample_doc(), APIProjection([PUBLIC_ID, 'does_not_exist'])).project

        assert result == {PUBLIC_ID: 1}

    def test_dotted_include_descends_into_nested_dict(self) -> None:
        """A dotted key keeps only the nested sub-key inside a nested dict."""
        doc = {META: {SECTIONS: [1, 2], 'other': 'x'}, PUBLIC_ID: 1}

        result = APIProjector(doc, APIProjection([f'{META}.{SECTIONS}'])).project

        assert result == {META: {SECTIONS: [1, 2]}}

    def test_dotted_include_descends_into_nested_list(self) -> None:
        """A dotted key is applied to every element of a nested list."""
        doc = {ITEMS: [{NAME: 'a', SECRET: 'x'}, {NAME: 'b', SECRET: 'y'}]}

        result = APIProjector(doc, APIProjection([f'{ITEMS}.{NAME}'])).project

        assert result == {ITEMS: [{NAME: 'a'}, {NAME: 'b'}]}


class TestProjectExcludes:
    """Exclude projections (value 0) drop the listed top-level keys."""

    def test_exclude_removes_listed_key(self) -> None:
        """An exclude-only projection removes the listed key and keeps the rest."""
        result = APIProjector(_sample_doc(), APIProjection({SECRET: EXCLUDE})).project

        assert SECRET not in result
        assert result[PUBLIC_ID] == 1

    def test_exclude_does_not_mutate_input_document(self) -> None:
        """Regression: exclude-only projection must not delete keys from the caller's document."""
        doc = _sample_doc()
        original = dict(doc)

        APIProjector(doc, APIProjection({SECRET: EXCLUDE})).project

        assert doc == original

    def test_missing_exclude_key_is_ignored(self) -> None:
        """Excluding a key the document does not have is a no-op, not an error."""
        result = APIProjector(_sample_doc(), APIProjection({'absent': EXCLUDE})).project

        assert result == _sample_doc()


class TestProjectListInput:
    """A list of documents is projected element-by-element, preserving list shape."""

    def test_projects_every_element(self) -> None:
        """Each document in the list is projected independently."""
        docs = [{PUBLIC_ID: 1, SECRET: 'a'}, {PUBLIC_ID: 2, SECRET: 'b'}]

        result = APIProjector(docs, APIProjection([PUBLIC_ID])).project

        assert result == [{PUBLIC_ID: 1}, {PUBLIC_ID: 2}]

    def test_non_dict_element_raises_type_error(self) -> None:
        """A non-dict payload cannot be projected and raises TypeError."""
        with pytest.raises(TypeError):
            _ = APIProjector('not-a-dict', APIProjection([PUBLIC_ID])).project


class TestProjectCaching:
    """`project` computes once and returns the cached result on subsequent access."""

    def test_result_is_cached(self) -> None:
        """Two reads of `project` return the identical (cached) object."""
        projector = APIProjector(_sample_doc(), APIProjection([PUBLIC_ID]))

        first = projector.project
        second = projector.project

        assert first is second

    def test_empty_result_is_cached(self) -> None:
        """Regression: a falsy (empty) projected result is still cached, not recomputed."""
        # Excluding the only key yields {} — a falsy value that must not defeat memoization.
        projector = APIProjector({PUBLIC_ID: 1}, APIProjection({PUBLIC_ID: EXCLUDE}))

        first = projector.project
        second = projector.project

        assert first == {}
        assert first is second


# -------------------------------------------------------------------------------------------------------------------- #
#                                         APIProjector.element_includes                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestElementIncludes:
    """The static dotted-path extractor and its error handling."""

    def test_plain_key_present(self) -> None:
        """A present plain key returns the single matching pair."""
        assert APIProjector.element_includes(PUBLIC_ID, {PUBLIC_ID: 1, LABEL: 'x'}) == {PUBLIC_ID: 1}

    def test_plain_key_missing_raises(self) -> None:
        """A missing plain key raises APIProjectionInclusionError."""
        with pytest.raises(APIProjectionInclusionError):
            APIProjector.element_includes('missing', {PUBLIC_ID: 1})

    def test_dotted_nested_dict(self) -> None:
        """A dotted key extracts only the nested sub-key."""
        assert APIProjector.element_includes('a.b', {'a': {'b': 2, 'c': 3}}) == {'a': {'b': 2}}

    def test_dotted_nested_list(self) -> None:
        """A dotted key over a list applies to every element."""
        assert APIProjector.element_includes('a.b', {'a': [{'b': 1}, {'b': 2}]}) == {'a': [{'b': 1}, {'b': 2}]}

    def test_missing_intermediate_segment_raises(self) -> None:
        """Regression: a missing intermediate segment raises the wrapped error, not a raw KeyError."""
        with pytest.raises(APIProjectionInclusionError):
            APIProjector.element_includes('a.b', {'x': 1})

    def test_scalar_intermediate_segment_raises(self) -> None:
        """Regression: a non-subscriptable intermediate segment raises the wrapped error, not TypeError."""
        with pytest.raises(APIProjectionInclusionError):
            APIProjector.element_includes('a.b', {'a': 'scalar'})


class TestProjectMissingDottedSegmentSkipped:
    """End-to-end: a broken dotted include is skipped instead of raising out of `project`."""

    def test_missing_intermediate_include_is_skipped(self) -> None:
        """Regression: a dotted include with a missing intermediate key drops that include only."""
        doc = {PUBLIC_ID: 1}

        result = APIProjector(doc, APIProjection([PUBLIC_ID, f'{META}.{SECTIONS}'])).project

        assert result == {PUBLIC_ID: 1}


# -------------------------------------------------------------------------------------------------------------------- #
#                                         a key that holds a dot (T324 B1)                                             #
# -------------------------------------------------------------------------------------------------------------------- #
DOTTED_NAME: str = 'ip.address'
DOTTED_VALUE: str = '10.0.0.1'
NESTED_VALUE: str = 'nested'
FIELDS: str = 'fields'


class TestADottedNameIsOneKey:
    """A field name may hold a dot: the longest existing prefix wins, and a key held as it is wins outright"""

    def test_a_dotted_field_name_is_selected(self) -> None:
        """fields.ip.address reaches the field named ip.address - it used to descend into ip -> address"""
        doc = {FIELDS: {DOTTED_NAME: DOTTED_VALUE, NAME: 'srv'}}

        assert APIProjector(doc, APIProjection([f'{FIELDS}.{DOTTED_NAME}'])).project == {
            FIELDS: {DOTTED_NAME: DOTTED_VALUE},
        }

    def test_the_named_key_wins_over_the_nested_path(self) -> None:
        """Both spellings present: the key the document holds as it is is the one meant"""
        doc = {FIELDS: {DOTTED_NAME: DOTTED_VALUE, 'ip': {'address': NESTED_VALUE}}}

        assert APIProjector.element_includes(f'{FIELDS}.{DOTTED_NAME}', doc) == {FIELDS: {DOTTED_NAME: DOTTED_VALUE}}

    def test_a_top_level_dotted_key_is_selected_as_it_is(self) -> None:
        """A key held as it is is matched before any split"""
        assert APIProjector.element_includes(DOTTED_NAME, {DOTTED_NAME: 1}) == {DOTTED_NAME: 1}

    def test_the_nested_path_still_works_without_a_named_key(self) -> None:
        """No document key holds the dot: the path is read segment by segment as before"""
        assert APIProjector.element_includes('a.b.c', {'a': {'b': {'c': 1, 'd': 2}}}) == {'a': {'b': {'c': 1}}}

    @pytest.mark.parametrize('key, element, expected', [
        ('a.b.c', {'a': {}}, ('a', 'b.c')),
        ('a.b.c', {'a.b': {}, 'a': {}}, ('a.b', 'c')),
        ('a.b', {'x': 1}, None),
        ('plain', {'plain': 1}, None),
    ], ids=['shortest', 'longest-wins', 'no-prefix', 'no-dot'])
    def test_split_key_finds_the_longest_existing_prefix(
            self, key: str, element: dict, expected: tuple[str, str] | None) -> None:
        """The split never uses the whole key - the exact match is the caller's first check"""
        assert APIProjector.split_key(key, element) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                      includes under one parent combine (T324 B2)                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIncludesUnderOneParent:
    """Several includes under the same key used to replace each other - the last one won"""

    def test_two_sub_keys_both_survive(self) -> None:
        """render_meta.icon + render_meta.sections answer both"""
        doc = {META: {'icon': 'x', SECTIONS: [1], 'summary': {}}}

        assert APIProjector(doc, APIProjection([f'{META}.icon', f'{META}.{SECTIONS}'])).project == {
            META: {'icon': 'x', SECTIONS: [1]},
        }

    def test_the_object_selectors_projection_keeps_object_id(self) -> None:
        """The frontend object selector asks object_information.object_id AND .public_id - object_id must survive"""
        doc = {'object_information': {'object_id': 7, 'public_id': 7, 'author_name': 'a'}, 'summary_line': 's'}
        projection = APIProjection({
            'object_information.object_id': INCLUDE, 'object_information.public_id': INCLUDE, 'summary_line': INCLUDE,
        })

        assert APIProjector(doc, projection).project == {
            'object_information': {'object_id': 7, 'public_id': 7}, 'summary_line': 's',
        }

    def test_list_entries_combine_by_position(self) -> None:
        """Two includes into the same list merge entry by entry"""
        doc = {ITEMS: [{'a': 1, 'b': 2, 'c': 3}, {'a': 4, 'b': 5, 'c': 6}]}

        assert APIProjector(doc, APIProjection([f'{ITEMS}.a', f'{ITEMS}.b'])).project == {
            ITEMS: [{'a': 1, 'b': 2}, {'a': 4, 'b': 5}],
        }

    def test_merging_does_not_touch_the_source(self) -> None:
        """The merge copies the dicts it combines"""
        doc = {META: {'icon': 'x', SECTIONS: [1]}}

        APIProjector(doc, APIProjection([META, f'{META}.icon'])).project  # pylint: disable=expression-not-assigned

        assert doc == {META: {'icon': 'x', SECTIONS: [1]}}

    def test_merge_included_sets_a_non_dict_value(self) -> None:
        """A scalar under the key is replaced, not merged"""
        target = {'a': 1}
        APIProjector.merge_included(target, {'a': {'b': 2}})

        assert target == {'a': {'b': 2}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       a list is projected per entry (T324 B3)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAListIsProjectedPerEntry:
    """One entry lacking the key used to drop the include for every entry"""

    def test_entries_that_have_the_key_keep_it(self) -> None:
        """The entry without it stays as an empty dict, so positions are kept"""
        doc = {ITEMS: [{'a': 1, 'b': 2}, {'b': 3}]}

        assert APIProjector(doc, APIProjection([f'{ITEMS}.a'])).project == {ITEMS: [{'a': 1}, {}]}

    def test_a_list_in_which_no_entry_has_the_key_drops_the_include(self) -> None:
        """Nothing to select: the include is skipped like a missing key"""
        doc = {PUBLIC_ID: 1, ITEMS: [{'b': 1}, 'scalar']}

        assert APIProjector(doc, APIProjection([PUBLIC_ID, f'{ITEMS}.a'])).project == {PUBLIC_ID: 1}

    def test_an_empty_list_stays_an_empty_list(self) -> None:
        """No entry to fail - the key is answered with its empty list"""
        assert APIProjector.element_includes(f'{ITEMS}.a', {ITEMS: []}) == {ITEMS: []}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            dotted excludes (T324 B4)                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDottedExcludes:
    """A dotted exclude used to be ignored silently - only top-level keys were popped"""

    def test_a_nested_key_is_removed(self) -> None:
        """render_meta.icon: 0 removes the icon and keeps the rest of render_meta"""
        doc = {PUBLIC_ID: 1, META: {'icon': 'x', SECTIONS: [1]}}

        assert APIProjector(doc, APIProjection({f'{META}.icon': EXCLUDE})).project == {
            PUBLIC_ID: 1, META: {SECTIONS: [1]},
        }

    def test_the_callers_document_is_not_mutated(self) -> None:
        """Only the containers on the path are copied"""
        doc = {META: {'icon': 'x', SECTIONS: [1]}}

        APIProjector(doc, APIProjection({f'{META}.icon': EXCLUDE})).project  # pylint: disable=expression-not-assigned

        assert doc == {META: {'icon': 'x', SECTIONS: [1]}}

    def test_a_key_is_removed_from_every_list_entry(self) -> None:
        """Into a list, like an include"""
        doc = {ITEMS: [{'a': 1, 'b': 2}, {'b': 3}, 'scalar']}

        assert APIProjector(doc, APIProjection({f'{ITEMS}.b': EXCLUDE})).project == {
            ITEMS: [{'a': 1}, {}, 'scalar'],
        }

    def test_a_dotted_field_name_is_excluded_as_one_key(self) -> None:
        """The same longest-prefix rule as an include"""
        doc = {FIELDS: {DOTTED_NAME: DOTTED_VALUE, NAME: 'srv'}}

        assert APIProjector(doc, APIProjection({f'{FIELDS}.{DOTTED_NAME}': EXCLUDE})).project == {
            FIELDS: {NAME: 'srv'},
        }

    def test_an_exclude_that_reaches_nothing_removes_nothing(self) -> None:
        """A missing path is ignored, as a missing top-level key always was"""
        doc = {PUBLIC_ID: 1, META: 'scalar'}

        assert APIProjector(doc, APIProjection({'nope.x': EXCLUDE, f'{META}.icon': EXCLUDE})).project == doc

    def test_an_exclude_narrows_an_include_on_the_same_parent(self) -> None:
        """Includes first, then excludes: the whole of render_meta but its icon"""
        doc = {PUBLIC_ID: 1, META: {'icon': 'x', SECTIONS: [1]}}

        assert APIProjector(doc, APIProjection({META: INCLUDE, f'{META}.icon': EXCLUDE})).project == {
            META: {SECTIONS: [1]},
        }

    def test_a_deep_exclude_does_not_mutate_a_nested_source_document(self) -> None:
        """Below the top level the dicts on the path are the caller's own - each is copied, never changed"""
        doc = {'a': {'b': {'c': 1, 'd': 2}, 'e': 3}}

        result = APIProjector(doc, APIProjection({'a.b.c': EXCLUDE})).project

        assert result == {'a': {'b': {'d': 2}, 'e': 3}}
        assert doc == {'a': {'b': {'c': 1, 'd': 2}, 'e': 3}}
