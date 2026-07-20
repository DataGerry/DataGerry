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
Unit tests for the shared ISMS report aggregation-pipeline fragment builders

These are pure functions (no database) that emit the $lookup/$unwind stages shared by the Risk
Treatment Plan and Risk Assessments reports; the tests pin the collections joined and the field
names so the two reports stay in sync.
"""
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    build_ra_report_search_stage,
    build_report_facet_stage,
    build_report_pagination_stages,
    extract_report_page,
    object_reference_lookup_stages,
    paginate_report_rows,
    risk_matrix_class_lookup_stages,
    RA_REPORT_SEARCH_FIELDS,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestBuildRaReportSearchStage:
    """build_ra_report_search_stage builds a case-insensitive OR regex $match over the display fields."""

    def test_matches_all_search_fields(self) -> None:
        """The stage ORs a regex clause for every searchable display field."""
        stage = build_ra_report_search_stage('web')

        matched_fields = [next(iter(clause)) for clause in stage['$match']['$or']]
        assert matched_fields == RA_REPORT_SEARCH_FIELDS
        assert RA_REPORT_SEARCH_FIELDS == ['risk_title', 'risk_category', 'protection_goals']

    def test_case_insensitive_regex(self) -> None:
        """Each clause is a case-insensitive regex on the search term."""
        stage = build_ra_report_search_stage('web')

        for clause in stage['$match']['$or']:
            regex = next(iter(clause.values()))
            assert regex == {'$regex': 'web', '$options': 'i'}

    def test_term_is_regex_escaped(self) -> None:
        """Regex metacharacters in the term are escaped so it matches as a literal substring."""
        stage = build_ra_report_search_stage('a.b*c')

        regex = stage['$match']['$or'][0]['risk_title']['$regex']
        assert regex == r'a\.b\*c'


class TestObjectReferenceLookupStages:
    """object_reference_lookup_stages joins the assessed object, its group and its type."""

    def test_joins_object_group_and_type(self) -> None:
        """The three stages look up framework.objects, objectGroups and types under the expected keys."""
        stages = object_reference_lookup_stages()

        joined = {(stage['$lookup']['from'], stage['$lookup']['as']) for stage in stages}

        assert joined == {
            ('framework.objects', 'object'),
            ('framework.objectGroups', 'object_group'),
            ('framework.types', 'object_type'),
        }

    def test_type_lookup_uses_object_type_id(self) -> None:
        """The type lookup keys off the resolved object's type_id."""
        type_stage = next(s for s in object_reference_lookup_stages() if s['$lookup']['as'] == 'object_type')

        assert type_stage['$lookup']['localField'] == 'object.type_id'


class TestRiskMatrixClassLookupStages:
    """risk_matrix_class_lookup_stages resolves a calculation matrix to its cell and risk class."""

    def test_binds_calculation_field_and_output_names(self) -> None:
        """The let bindings read the given calculation field and the outputs use the given names."""
        stages = risk_matrix_class_lookup_stages('risk_calculation_before', 'risk_before', 'risk_before_class')

        matrix_lookup = stages[0]['$lookup']
        assert matrix_lookup['from'] == 'isms.riskMatrix'
        assert matrix_lookup['let'] == {
            'likelihood_id': '$risk_calculation_before.likelihood_id',
            'impact_id': '$risk_calculation_before.maximum_impact_id',
        }
        assert matrix_lookup['as'] == 'risk_before'

        class_lookup = stages[2]['$lookup']
        assert class_lookup['from'] == 'isms.riskClass'
        assert class_lookup['localField'] == 'risk_before.risk_class_id'
        assert class_lookup['as'] == 'risk_before_class'

    def test_emits_lookup_unwind_lookup_unwind(self) -> None:
        """The fragment is exactly: matrix $lookup, $unwind, riskClass $lookup, $unwind."""
        stages = risk_matrix_class_lookup_stages('risk_calculation_after', 'risk_after', 'risk_after_class')

        assert [next(iter(stage)) for stage in stages] == ['$lookup', '$unwind', '$lookup', '$unwind']
        assert stages[1]['$unwind']['path'] == '$risk_after'
        assert stages[3]['$unwind']['path'] == '$risk_after_class'


class TestBuildReportPaginationStages:
    """build_report_pagination_stages emits the trailing $sort / $skip / $limit stages."""

    def test_defaults_sort_public_id_skip_zero_limit_ten(self) -> None:
        """With default params it sorts by public_id asc, skips nothing and limits to 10."""
        stages = build_report_pagination_stages(CollectionParameters(''))

        assert stages == [
            {'$sort': {'public_id': 1}},
            {'$skip': 0},
            {'$limit': 10},
        ]

    def test_non_default_sort_adds_public_id_tiebreaker(self) -> None:
        """Sorting by a display field keeps public_id as a secondary key for deterministic paging."""
        stages = build_report_pagination_stages(CollectionParameters('', sort='risk_name', order=-1))

        assert stages[0] == {'$sort': {'risk_name': -1, 'public_id': 1}}

    def test_page_and_limit_compute_skip(self) -> None:
        """Page 3 at limit 25 skips the first 50 rows and limits to 25."""
        stages = build_report_pagination_stages(CollectionParameters('', limit=25, page=3))

        assert {'$skip': 50} in stages
        assert {'$limit': 25} in stages

    def test_limit_zero_emits_no_limit_stage(self) -> None:
        """A limit of 0 (export "all") emits no $limit stage (MongoDB rejects $limit: 0)."""
        # A '0' query-string value is preserved as limit 0 (unlike an int 0, which
        # CollectionParameters would coerce to the default 10)
        stages = build_report_pagination_stages(CollectionParameters('', limit='0'))

        assert stages == [
            {'$sort': {'public_id': 1}},
            {'$skip': 0},
        ]


class TestBuildReportFacetStage:
    """build_report_facet_stage pages the rows and counts the full result set in one $facet."""

    def test_data_branch_pages_and_drops_public_id(self) -> None:
        """The data branch is the pagination stages followed by the public_id-dropping projection."""
        facet = build_report_facet_stage(CollectionParameters('', sort='risk_title', order=1))

        data_branch = facet['$facet']['data']
        assert data_branch[0] == {'$sort': {'risk_title': 1, 'public_id': 1}}
        assert data_branch[-1] == {'$project': {'public_id': 0}}

    def test_total_branch_counts_rows(self) -> None:
        """The total branch counts the rows entering the facet (post-pipeline, not a raw collection)."""
        facet = build_report_facet_stage(CollectionParameters(''))

        assert facet['$facet']['total'] == [{'$count': 'total'}]


class TestExtractReportPage:
    """extract_report_page splits the faceted result document into (rows, total)."""

    def test_splits_rows_and_total(self) -> None:
        """A populated facet document yields its data rows and the total count."""
        rows, total = extract_report_page([{'data': [{'risk_title': 'A'}, {'risk_title': 'B'}],
                                            'total': [{'total': 37}]}])

        assert rows == [{'risk_title': 'A'}, {'risk_title': 'B'}]
        assert total == 37

    def test_empty_result_yields_no_rows_and_zero_total(self) -> None:
        """An empty aggregation result (no documents at all) yields no rows and a zero total."""
        assert extract_report_page([]) == ([], 0)

    def test_empty_total_bucket_yields_zero_total(self) -> None:
        """When the page has no rows the $count branch is empty, so total defaults to 0."""
        rows, total = extract_report_page([{'data': [], 'total': []}])

        assert rows == []
        assert total == 0


class TestPaginateReportRows:
    """paginate_report_rows slices an already-sorted list into the requested page."""

    ROWS = [{'public_id': i} for i in range(1, 8)]

    def test_slices_requested_page(self) -> None:
        """Page 2 at limit 3 returns rows 4-6 and the full total."""
        page, total = paginate_report_rows(self.ROWS, CollectionParameters('', limit=3, page=2))

        assert page == [{'public_id': 4}, {'public_id': 5}, {'public_id': 6}]
        assert total == 7

    def test_first_page_respects_limit(self) -> None:
        """The first page returns at most `limit` rows while total counts every row."""
        page, total = paginate_report_rows(self.ROWS, CollectionParameters('', limit=2))

        assert page == [{'public_id': 1}, {'public_id': 2}]
        assert total == 7

    def test_limit_zero_returns_all_rows(self) -> None:
        """A limit of 0 (export "all") returns every row unsliced."""
        page, total = paginate_report_rows(self.ROWS, CollectionParameters('', limit='0'))

        assert page == self.ROWS
        assert total == 7
