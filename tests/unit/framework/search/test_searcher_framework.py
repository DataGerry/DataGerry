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
Unit tests for cmdb.framework.search.searcher_framework.SearcherFramework

Pure tests: no Mongo, no Flask. The ObjectsManager is a mock returning the single document a
``$facet`` emits, and the renderer is patched, so what is exercised is the searcher's own behaviour -
the pipeline it hands to the database, how it reads the facet's three branches, and what it puts into
the SearchResult. The query itself is pinned against a real MongoDB by the functional search-route
suite.

Four things are worth the tests above the rest:

  - the search patterns are read BEFORE the facet is appended, so a future stage carrying a `$regex`
    of its own cannot end up highlighted as if the user had searched for it
  - a failure while reading them costs the highlighting and nothing else: the page is still answered
  - the facet document is read defensively (`next(iter(...), {})`), because the alternative - the
    `[0]` this file used to do - is an IndexError inside a route
  - `?resolve=` reaches the renderer. It was accepted by the route, passed in as `**kwargs` and
    dropped on the floor, so reference resolution could not be switched on at all
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.search.search_constants import SearchFacetKey, SearchGroupKey
from cmdb.framework.search.searcher_framework import SearcherFramework
from cmdb.manager import ObjectsManager
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.framework.search.searcher_framework'

PAGE_SIZE: int = 2
OFFSET: int = 4
TOTAL: int = 7
OBJECT_ID: int = 555
TYPE_ID: int = 47


def _document(public_id: int = OBJECT_ID) -> dict[str, Any]:
    """A matched CmdbObject document as an aggregation returns it."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': 'text-1', 'value': 'host'}],
    }


def _group() -> dict[str, Any]:
    """One per-type group entry as the group branch projects it."""
    return {
        SearchGroupKey.SEARCH_TEXT.value: 'Server',
        SearchGroupKey.SEARCH_FORM.value: 'type',
        SearchGroupKey.SEARCH_LABEL.value: 'Server',
        SearchGroupKey.SETTINGS.value: {SearchGroupKey.TYPES.value: [TYPE_ID]},
        SearchGroupKey.TOTAL.value: TOTAL,
    }


def _facet_document(
        documents: list[dict[str, Any]] | None = None,
        total: int | None = TOTAL,
        groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The single document a `$facet` emits, with all three branches."""
    metadata: list[dict[str, Any]] = [] if total is None else [{SearchGroupKey.TOTAL.value: total}]

    return {
        SearchFacetKey.METADATA.value: metadata,
        SearchFacetKey.DATA.value: documents if documents is not None else [_document()],
        SearchFacetKey.GROUP.value: groups if groups is not None else [_group()],
    }


def _searcher(facet_document: dict[str, Any] | None = None) -> tuple[SearcherFramework, MagicMock]:
    """A searcher whose ObjectsManager answers with the given facet document."""
    objects_manager = MagicMock(spec=ObjectsManager)
    objects_manager.aggregate_objects.return_value = iter(
        [facet_document if facet_document is not None else _facet_document()]
    )

    return SearcherFramework(objects_manager), objects_manager


@pytest.fixture(name='render_list')
def fixture_render_list():
    """Patches RenderList, whose rendering is exercised by its own suite."""
    with patch(f'{MODULE_PATH}.RenderList') as render_list:
        render_list.return_value.render_result_list.return_value = ['rendered']
        yield render_list


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the pipeline                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestThePipeline:
    """What the searcher hands to the database: the caller's criteria plus the search facet."""

    def test_the_criteria_are_kept_and_the_facet_appended(self, render_list) -> None:
        """The caller's stages come first - they carry the ACL the routes built"""
        del render_list
        criteria: list[dict[str, Any]] = [{'$match': {'type_id': TYPE_ID}}]
        searcher, objects_manager = _searcher()

        searcher.aggregate(criteria, limit=PAGE_SIZE)

        pipeline = objects_manager.aggregate_objects.call_args.kwargs['pipeline']
        assert pipeline[0] == criteria[0]
        assert list(pipeline[-1]) == ['$facet']

    def test_the_page_is_taken_from_the_requested_limit_and_skip(self, render_list) -> None:
        """Paging is expressed inside the facet's data branch"""
        del render_list
        searcher, objects_manager = _searcher()

        searcher.aggregate([], limit=PAGE_SIZE, skip=OFFSET)

        facet = objects_manager.aggregate_objects.call_args.kwargs['pipeline'][-1]['$facet']
        assert facet[SearchFacetKey.DATA.value] == [{'$skip': OFFSET}, {'$limit': PAGE_SIZE}]

    def test_an_unlimited_search_sends_no_limit_stage(self, render_list) -> None:
        """0 means every match; MongoDB refuses a `$limit: 0`"""
        del render_list
        searcher, objects_manager = _searcher()

        searcher.aggregate([], limit=0)

        facet = objects_manager.aggregate_objects.call_args.kwargs['pipeline'][-1]['$facet']
        assert facet[SearchFacetKey.DATA.value] == []

    def test_the_patterns_are_read_before_the_facet_is_appended(self, render_list) -> None:
        """
        Otherwise the facet's own stages would be scanned for `$regex` too

        Nothing in the facet carries one today, which is exactly why an accidental change here would
        go unnoticed until a user saw a highlight they never searched for.
        """
        del render_list
        seen: list[int] = []
        searcher, _ = _searcher()

        with patch(f'{MODULE_PATH}.SearchPipelineBuilder') as builder_class:
            builder = builder_class.return_value
            builder.pipeline = []
            builder.get_regex_pipes_values.side_effect = lambda: seen.append(len(builder.pipeline)) or []
            builder.add_pipe.side_effect = lambda stage: builder.pipeline.append(stage)

            searcher.aggregate([{'$match': {}}], limit=PAGE_SIZE)

        assert seen == [0]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              reading the facet result                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadingTheFacetResult:
    """The three branches, and what an unexpected result document does NOT do."""

    def test_the_total_comes_from_the_metadata_branch(self, render_list) -> None:
        """The count of the whole matched set, not of the page"""
        del render_list
        searcher, _ = _searcher()

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert result.total_results == TOTAL

    def test_an_empty_metadata_branch_is_a_total_of_zero(self, render_list) -> None:
        """`$count` emits NO document when nothing matched"""
        del render_list
        searcher, _ = _searcher(_facet_document(documents=[], total=None, groups=[]))

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert result.total_results == 0

    def test_the_groups_are_passed_through_unchanged(self, render_list) -> None:
        """They are a frontend contract; the searcher does not reshape them"""
        del render_list
        searcher, _ = _searcher()

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert result.groups == [_group()]

    def test_an_empty_page_renders_nothing(self, render_list) -> None:
        """A search that matched nothing answers an empty page without invoking the renderer"""
        searcher, _ = _searcher(_facet_document(documents=[], total=0, groups=[]))

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert (len(result), result.total_results, result.groups) == (0, 0, [])
        render_list.assert_not_called()

    def test_a_result_document_without_the_branches_is_survived(self, render_list) -> None:
        """
        `$facet` always emits exactly one document carrying all three keys

        This is the guard for the day that stops being true: reading it defensively answers an empty
        page, where the `[0]` and `['data']` this file used to do raised inside a route.
        """
        del render_list
        searcher, _ = _searcher({})

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert (len(result), result.total_results, result.groups) == (0, 0, [])

    def test_an_empty_aggregation_result_is_survived(self, render_list) -> None:
        """Same guard, one level up: no document at all instead of one"""
        del render_list
        objects_manager = MagicMock(spec=ObjectsManager)
        objects_manager.aggregate_objects.return_value = iter([])

        result = SearcherFramework(objects_manager).aggregate([], limit=PAGE_SIZE)

        assert result.total_results == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the rendering                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheRendering:
    """Only the page is rendered, for the requesting user, with the requested resolve mode."""

    def test_the_page_documents_are_rendered_for_the_request_user(self, render_list) -> None:
        """The ACL rode in with the pipeline; the user is needed for the rendering"""
        request_user = MagicMock(spec=CmdbUser)
        searcher, _ = _searcher()

        searcher.aggregate([], request_user=request_user, limit=PAGE_SIZE)

        objects, user, resolve = render_list.call_args.args
        assert [obj.get_public_id() for obj in objects] == [OBJECT_ID]
        assert (user, resolve) == (request_user, False)

    def test_resolve_reaches_the_renderer(self, render_list) -> None:
        """
        The route's ``?resolve=true``

        It used to arrive as an ignored `**kwargs` entry, so reference resolution was unreachable.
        """
        searcher, _ = _searcher()

        searcher.aggregate([], limit=PAGE_SIZE, resolve=True)

        assert render_list.call_args.args[2] is True

    def test_the_rendered_page_is_what_the_result_carries(self, render_list) -> None:
        """One SearchResultMap per rendered hit"""
        del render_list
        searcher, _ = _searcher()

        result = searcher.aggregate([], limit=PAGE_SIZE)

        assert len(result) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the highlighting patterns                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheSearchPatterns:
    """The patterns the hits are highlighted against, and what a failure to read them costs."""

    def test_the_patterns_are_taken_from_the_pipeline(self, render_list) -> None:
        """A text search's `$regex` values are what a hit's matched fields are found with"""
        del render_list
        searcher, _ = _searcher()
        criteria: list[dict[str, Any]] = [
            {'$match': {'fields.value': {'$regex': 'host', '$options': 'ims'}}},
        ]

        with patch(f'{MODULE_PATH}.SearchResult') as search_result:
            searcher.aggregate(criteria, limit=PAGE_SIZE)

        assert search_result.__getitem__.return_value.call_args.kwargs['matches_regex'] == ['host']

    def test_a_failure_to_read_them_still_answers_the_page(self, render_list) -> None:
        """
        Highlighting is a nicety; the results are the answer

        The builder swallows its own errors, so this arm is only reachable by a broken builder - which
        is precisely why it is worth pinning rather than deleting.
        """
        del render_list
        searcher, _ = _searcher()

        with patch(f'{MODULE_PATH}.SearchPipelineBuilder') as builder_class:
            builder = builder_class.return_value
            builder.pipeline = []
            builder.get_regex_pipes_values.side_effect = RuntimeError('boom')

            result = searcher.aggregate([], limit=PAGE_SIZE)

        assert result.total_results == TOTAL


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the metadata                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheResultMetadata:
    """limit / skip / alive, as the SearchResult carries them."""

    def test_the_paging_is_reported_back(self, render_list) -> None:
        """The frontend pages with what it sent"""
        del render_list
        searcher, _ = _searcher()

        result = searcher.aggregate([], limit=PAGE_SIZE, skip=OFFSET)

        assert (result.limit, result.skip) == (PAGE_SIZE, OFFSET)

    def test_alive_reports_whether_more_matches_follow(self, render_list) -> None:
        """
        Computed from the paging, not from the cursor

        `alive` used to be read off the CommandCursor AFTER it had been drained, so it was always
        False - a value that is computed has to be true even while nothing serializes it.
        """
        del render_list
        searcher, _ = _searcher()

        assert searcher.aggregate([], limit=PAGE_SIZE, skip=0).alive is True

    def test_the_last_page_is_not_alive(self, render_list) -> None:
        """Skip plus this page's size covers every match"""
        del render_list
        searcher, _ = _searcher(_facet_document(documents=[_document()], total=1))

        assert searcher.aggregate([], limit=PAGE_SIZE, skip=0).alive is False
