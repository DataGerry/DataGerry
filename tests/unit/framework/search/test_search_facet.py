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
Unit tests for cmdb.framework.search.search_facet

Pure tests: no Mongo, no Flask. The module returns aggregation stages, so the stages themselves are
what is asserted.

Three things are pinned because nothing else would notice them changing: the paging semantics (0 or
less means unlimited, which MongoDB can only express by OMITTING the `$limit` - it refuses a
`$limit: 0` - and a negative skip is clamped), the ORDER of the group branch (tally first, resolve
the labels of the surviving rows second, which is what keeps a 50,000-match search from performing
50,000 lookups), and the group entry's keys, which the Angular result bar reads and re-submits.
"""
from typing import Any

import pytest

from cmdb.framework.search.search_constants import (
    SearchFacetKey,
    SearchFormType,
    SearchGroupKey,
)
from cmdb.framework.search.search_facet import (
    MONGO_ID_KEY,
    TYPE_LOOKUP_FIELD,
    build_page_stages,
    build_search_facet,
    build_total_stages,
    build_type_group_stages,
)
from cmdb.models.type_model import CmdbType, TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

FACET: str = '$facet'
GROUP: str = '$group'
LOOKUP: str = '$lookup'
UNWIND: str = '$unwind'
PROJECT: str = '$project'
SORT: str = '$sort'
SKIP: str = '$skip'
LIMIT: str = '$limit'
COUNT: str = '$count'

PAGE_SIZE: int = 25
OFFSET: int = 50


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 build_total_stages                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_total_branch_is_a_single_count() -> None:
    """The metadata branch counts the whole matched set, under the key the searcher reads"""
    assert build_total_stages() == [{COUNT: SearchGroupKey.TOTAL.value}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 build_page_stages                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildPageStages:
    """The paging branch, where a limit of 0 means 'every match' rather than 'none'."""

    def test_skip_and_limit_are_applied_in_that_order(self) -> None:
        """Skipping before limiting is what makes page N the Nth page"""
        assert build_page_stages(OFFSET, PAGE_SIZE) == [{SKIP: OFFSET}, {LIMIT: PAGE_SIZE}]

    @pytest.mark.parametrize('limit', [0, -1], ids=['zero', 'negative'])
    def test_an_unlimited_page_omits_the_limit_stage(self, limit: int) -> None:
        """
        MongoDB refuses a `$limit: 0`

        Sending one failed the whole aggregation, and the route reported that as an empty 204 - so
        asking for every result answered with none.
        """
        assert build_page_stages(0, limit) == []

    def test_a_negative_skip_is_clamped(self) -> None:
        """`$skip: -1` is refused by MongoDB just as `$limit: 0` is"""
        assert build_page_stages(-5, PAGE_SIZE) == [{LIMIT: PAGE_SIZE}]

    def test_the_first_page_carries_no_skip(self) -> None:
        """A `$skip: 0` is a stage that does nothing"""
        assert build_page_stages(0, PAGE_SIZE) == [{LIMIT: PAGE_SIZE}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_type_group_stages                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildTypeGroupStages:
    """The per-type tallies: grouped first, labelled second, ordered by size."""

    @staticmethod
    def _stages() -> list[dict[str, Any]]:
        """The group branch."""
        return build_type_group_stages()

    def test_the_tally_happens_before_the_label_lookup(self) -> None:
        """
        The order IS the optimisation

        Looking a type up per matched object and grouping afterwards produces the same rows at the
        cost of one lookup per match, which is what this branch used to do.
        """
        stages = self._stages()

        assert list(stages[0]) == [GROUP]
        assert list(stages[1]) == [LOOKUP]

    def test_the_group_tallies_by_type_id(self) -> None:
        """One row per CmdbType, carrying how many matches belong to it"""
        assert self._stages()[0][GROUP] == {
            MONGO_ID_KEY: '$type_id',
            SearchGroupKey.TOTAL.value: {'$sum': 1},
        }

    def test_the_lookup_joins_the_types_collection_on_the_group_id(self) -> None:
        """The group's own id is the type id the labels are read for"""
        assert self._stages()[1][LOOKUP] == {
            'from': CmdbType.COLLECTION,
            'localField': MONGO_ID_KEY,
            'foreignField': TypeSchemaKey.PUBLIC_ID.value,
            'as': TYPE_LOOKUP_FIELD,
        }

    def test_a_type_that_no_longer_exists_drops_out(self) -> None:
        """The `$unwind` is what does it: an entry offers a filter, and a filter needs a label"""
        assert self._stages()[2] == {UNWIND: f'${TYPE_LOOKUP_FIELD}'}

    def test_the_projected_entry_is_a_ready_made_type_parameter(self) -> None:
        """
        The keys the Angular result bar reads and re-submits as a TYPE tag

        `searchText` and `searchLabel` are both the type's label; `settings.types` carries the single
        type id, which is the shape a TYPE search parameter expects.
        """
        label_expression = f'${TYPE_LOOKUP_FIELD}.{TypeSchemaKey.LABEL.value}'

        assert self._stages()[3][PROJECT] == {
            MONGO_ID_KEY: 0,
            SearchGroupKey.SEARCH_TEXT.value: label_expression,
            SearchGroupKey.SEARCH_FORM.value: SearchFormType.TYPE.value,
            SearchGroupKey.SEARCH_LABEL.value: label_expression,
            SearchGroupKey.SETTINGS.value: {SearchGroupKey.TYPES.value: [f'${MONGO_ID_KEY}']},
            SearchGroupKey.TOTAL.value: 1,
        }

    def test_the_biggest_group_comes_first(self) -> None:
        """The filter bar lists the types with the most matches at the top"""
        assert self._stages()[-1] == {SORT: {SearchGroupKey.TOTAL.value: -1}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_search_facet                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildSearchFacet:
    """One stage answering three questions about the same matched set."""

    def test_the_facet_carries_exactly_the_three_declared_branches(self) -> None:
        """Their names are what the searcher reads the result document by"""
        facet = build_search_facet(OFFSET, PAGE_SIZE)

        assert set(facet[FACET]) == {key.value for key in SearchFacetKey}

    def test_each_branch_is_the_stage_list_of_its_builder(self) -> None:
        """The facet composes the three builders and adds nothing of its own"""
        facet = build_search_facet(OFFSET, PAGE_SIZE)[FACET]

        assert facet[SearchFacetKey.METADATA.value] == build_total_stages()
        assert facet[SearchFacetKey.DATA.value] == build_page_stages(OFFSET, PAGE_SIZE)
        assert facet[SearchFacetKey.GROUP.value] == build_type_group_stages()

    def test_an_unlimited_search_has_an_empty_page_branch(self) -> None:
        """Every match is on the page, so neither stage is needed"""
        assert build_search_facet(0, 0)[FACET][SearchFacetKey.DATA.value] == []
