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
