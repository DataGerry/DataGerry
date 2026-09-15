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
This module contains the implementation of the SearcherFramework

The object search runs as ONE aggregation: the criteria the caller built are followed by a ``$facet``
(see `search_facet`) whose three branches answer the total, the requested page and the per-type
tallies of the same matched set. This class runs it, renders the page and wraps everything in a
`SearchResult`, which additionally reports per hit which of its fields matched the search patterns.

Three things are worth knowing before changing anything here:

* **The access control arrives inside the incoming pipeline.** `SearchPipelineBuilder.build(...)` is
  called with the request user and `AccessControlPermission.READ` by the routes, so the criteria are
  already ACL-filtered when they reach this class - which is why it takes no user for the query and
  passes one only to the renderer.
* **`groups` is a frontend contract.** Each entry is a ready-made TYPE search parameter that the
  Angular result bar re-submits; its keys are `SearchGroupKey`.
* **A page of 0 means every match.** The paging semantics live in `search_facet.build_page_stages`,
  the one place that also knows MongoDB refuses a `$limit: 0`.

`SearchPipelineBuilder` is imported from the manager layer on purpose: the framework layer sits above
the managers (see CLAUDE.md), so this is a downward dependency
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.query_builder.search_pipeline_builder import SearchPipelineBuilder
from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject

from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.search.search_constants import SearchFacetKey, SearchGroupKey
from cmdb.framework.search.search_facet import build_search_facet
from cmdb.framework.search.search_result import SearchResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               SearcherFramework - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class SearcherFramework:
    """
    Framework searcher implementation for object search
    """

    # Page size used when a request names none. Read by the search route, which passes it on as the
    # default of its ?limit= parameter
    DEFAULT_LIMIT: int = 10

    # The "no search term" sentinel of the quick-count route's ?searchValue=: an empty pattern
    # matches every object, which is what an untyped quick search means
    DEFAULT_REGEX: str = ''


    def __init__(self, objects_manager: ObjectsManager) -> None:
        """
        Initialises the SearcherFramework

        Args:
            objects_manager (ObjectsManager): db interface for CmdbObjects, which runs the aggregation
        """
        self.objects_manager: ObjectsManager = objects_manager


    def aggregate(
        self,
        pipeline: list[dict[str, Any]],
        request_user: CmdbUser | None = None,
        limit: int = DEFAULT_LIMIT,
        skip: int = 0,
        resolve: bool = False,
    ) -> SearchResult[RenderResult]:
        """
        Runs a search pipeline and answers with one rendered page plus the search's metadata

        The caller's criteria are extended by the search ``$facet``, so the total, the page and the
        per-type groups come out of a single aggregation. Only the page is rendered. The criteria are
        expected to carry their own access-control stages (the routes build them with the request
        user), so `request_user` is passed to the renderer rather than to the query

        Args:
            pipeline (list[dict[str, Any]]): The search criteria as aggregation stages
            request_user (CmdbUser | None): User the results are rendered for. Defaults to None
            limit (int): Page size; 0 or less means every match. Defaults to DEFAULT_LIMIT
            skip (int): Number of matches to skip; a negative value is treated as 0. Defaults to 0
            resolve (bool): Resolves referenced CmdbObjects while rendering (the route's ``?resolve=``).
                            Defaults to False

        Raises:
            ObjectsManagerIterationError: When the aggregation itself fails

        Returns:
            SearchResult[RenderResult]: The rendered page, the total, the per-type groups and, per
                                        hit, the fields that matched the search patterns
        """
        search_pipeline_builder = SearchPipelineBuilder(pipeline)

        # Read before the facet is appended: these are the patterns the CALLER searched for, and the
        # facet stage carries none of its own
        matches_regex: list[str] = self._collect_search_patterns(search_pipeline_builder)

        search_pipeline_builder.add_pipe(build_search_facet(skip, limit))

        raw_result = self.objects_manager.aggregate_objects(pipeline=search_pipeline_builder.pipeline)

        # $facet always emits exactly one document carrying all three branches; reading it defensively
        # keeps a changed facet from turning into an IndexError inside a route
        facet_result: dict[str, Any] = next(iter(raw_result), {})

        matched_documents: list[dict[str, Any]] = facet_result.get(SearchFacetKey.DATA.value, [])
        groups: list[dict[str, Any]] = facet_result.get(SearchFacetKey.GROUP.value, [])
        total_results: int = self._read_total(facet_result)

        rendered_results: list[RenderResult] = self._render_page(matched_documents, request_user, resolve)

        return SearchResult[RenderResult](
            results=rendered_results,
            total_results=total_results,
            groups=groups,
            # Not serialized by SearchResult.to_json, so nothing reads it today - but a value that is
            # computed has to be true: the cursor is already drained here, and its own 'alive' would
            # therefore always be False
            alive=skip + len(rendered_results) < total_results,
            matches_regex=matches_regex,
            limit=limit,
            skip=skip,
        )


    @staticmethod
    def _collect_search_patterns(search_pipeline_builder: SearchPipelineBuilder) -> list[str]:
        """
        Reads the regex patterns of a search pipeline, which the hits are highlighted against

        A failure here costs the highlighting and nothing else, so it is reported and the search still
        answers its page - the alternative would be failing a search that found what the user asked for

        Args:
            search_pipeline_builder (SearchPipelineBuilder): The builder holding the search criteria

        Returns:
            list[str]: The `$regex` values found in the pipeline, empty when they could not be read
        """
        try:
            return search_pipeline_builder.get_regex_pipes_values()
        except Exception as err:
            LOGGER.error("[aggregate] Failed to read the search patterns: %s. Type: %s", err, type(err))

            return []


    @staticmethod
    def _read_total(facet_result: dict[str, Any]) -> int:
        """
        Reads the match count out of the facet's metadata branch

        The branch is a `$count`, which emits NO document when nothing matched - so an empty branch
        means zero rather than a missing value

        Args:
            facet_result (dict[str, Any]): The single document the `$facet` stage emitted

        Returns:
            int: The number of matched CmdbObjects
        """
        metadata: list[dict[str, Any]] = facet_result.get(SearchFacetKey.METADATA.value, [])

        if not metadata:
            return 0

        return metadata[0].get(SearchGroupKey.TOTAL.value, 0)


    @staticmethod
    def _render_page(
            matched_documents: list[dict[str, Any]],
            request_user: CmdbUser | None,
            resolve: bool) -> list[RenderResult]:
        """
        Renders the matched documents of one page for the requesting user

        `from_data` rather than `CmdbObject(**raw)`: an aggregation result may carry keys the model
        does not declare, and from_data ignores those instead of turning them into silent attributes -
        it also normalises the two timestamps

        Args:
            matched_documents (list[dict[str, Any]]): The page's raw CmdbObject documents
            request_user (CmdbUser | None): User the results are rendered for
            resolve (bool): Resolves referenced CmdbObjects while rendering

        Returns:
            list[RenderResult]: The rendered page, empty when nothing matched
        """
        if not matched_documents:
            return []

        objects: list[CmdbObject] = [CmdbObject.from_data(document) for document in matched_documents]

        return RenderList(objects, request_user, resolve).render_result_list()
