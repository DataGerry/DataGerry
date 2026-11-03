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
names so the two reports stay in sync. ``read_report_page`` is driven through a recording stub manager,
which pins which aggregations it runs for a page, an export and a page above the ``$facet`` bound.
"""
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    build_ra_report_search_stage,
    build_report_count_stage,
    build_report_facet_stage,
    build_report_filter_stages,
    build_report_pagination_stages,
    build_report_rows_stages,
    extract_report_page,
    extract_report_total,
    read_report_page,
    total_from_rows,
    uses_report_facet,
    field_path,
    field_reference,
    object_reference_lookup_stages,
    paginate_report_rows,
    risk_matrix_class_lookup_stages,
    RA_REPORT_SEARCH_FIELDS,
    risk_assessment_report_projection_stage,
    variable_reference,
)
from cmdb.database.database_constants import LONG_QUERY_TIME_LIMIT_MS
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import REPORT_FACET_MAX_LIMIT, ReportAlias
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
# -------------------------------------------------------------------------------------------------------------------- #


class TestFieldPaths:
    """field_path / field_reference / variable_reference join enum keys into plain-string paths."""

    def test_field_path_joins_the_keys_with_dots(self) -> None:
        """The keys are joined outermost first."""
        assert field_path(ReportAlias.RISK, RiskKey.NAME) == 'risk.name'

    def test_field_reference_puts_one_dollar_in_front(self) -> None:
        """A field reference is the path behind a single `$`."""
        assert field_reference(ReportAlias.RISK, RiskKey.NAME) == '$risk.name'
        assert field_reference(ReportAlias.RISK) == '$risk'

    def test_variable_reference_puts_two_dollars_in_front(self) -> None:
        """A variable reference is the path behind `$$`."""
        assert variable_reference('pg', ProtectionGoalKey.NAME) == '$$pg.name'

    def test_the_results_are_plain_strings(self) -> None:
        """An enum member must never reach MongoDB, so every result is a plain `str`."""
        for result in (
            field_path(ReportAlias.RISK, RiskKey.NAME),
            field_reference(ReportAlias.RISK),
            variable_reference('pg', ProtectionGoalKey.NAME),
            field_path(ReportAlias.RISK),
        ):
            assert type(result) is str  # pylint: disable=unidiomatic-typecheck


class TestRiskAssessmentReportProjectionStage:
    """The RiskAssessment projection's keys reach MongoDB as plain strings."""

    def test_every_key_is_a_plain_string(self) -> None:
        """Enum members as projection keys would still work, but only by the str mix-in - pin the plain form."""
        projection = risk_assessment_report_projection_stage()['$project']

        assert all(type(key) is str for key in projection)  # pylint: disable=unidiomatic-typecheck

    def test_priority_labels_follow_the_stored_value(self) -> None:
        """The four stored priorities map to their labels in order; anything else is null."""
        switch = risk_assessment_report_projection_stage()['$project']['priority']['$switch']

        assert [(branch['case']['$eq'], branch['then']) for branch in switch['branches']] == [
            (['$priority', 1], 'Low'),
            (['$priority', 2], 'Medium'),
            (['$priority', 3], 'High'),
            (['$priority', 4], 'Very High'),
        ]
        assert switch['default'] is None


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
        stages = object_reference_lookup_stages([])

        joined = {(stage['$lookup']['from'], stage['$lookup']['as']) for stage in stages}

        assert joined == {
            ('framework.objects', 'object'),
            ('framework.objectGroups', 'object_group'),
            ('framework.types', 'object_type'),
        }

    def test_type_lookup_uses_object_type_id(self) -> None:
        """The type lookup keys off the resolved object's type_id."""
        type_stage = next(s for s in object_reference_lookup_stages([]) if s['$lookup']['as'] == 'object_type')

        assert type_stage['$lookup']['localField'] == 'object.type_id'

    @staticmethod
    def _type_pipeline(denied_type_ids: list[int]) -> list[dict]:
        """The pipeline of the type $lookup built for the given denied types"""
        stages = object_reference_lookup_stages(denied_type_ids)

        return next(s for s in stages if s['$lookup']['as'] == 'object_type')['$lookup']['pipeline']

    def test_type_lookup_skips_the_denied_types(self) -> None:
        """A denied type's label is never joined: the pipeline opens with a $nin on its public_id, sorted"""
        pipeline = self._type_pipeline([9, 4])

        assert pipeline[0] == {'$match': {'public_id': {'$nin': [4, 9]}}}
        assert pipeline[1] == {'$project': {'_id': 0, 'label': 1}}

    def test_type_lookup_has_no_match_when_nothing_is_denied(self) -> None:
        """A reader who may read every type gets the plain projection - no empty $nin"""
        assert self._type_pipeline([]) == [{'$project': {'_id': 0, 'label': 1}}]

    def test_only_the_type_lookup_is_narrowed(self) -> None:
        """The object and group joins stay unscoped - the object id must still reach the resolver"""
        for stage in object_reference_lookup_stages([4]):
            if stage['$lookup']['as'] != 'object_type':
                assert all('$match' not in step for step in stage['$lookup']['pipeline'])


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

class TestBuildReportFilterStages:
    """
    build_report_filter_stages accepts both shapes the API documents for ``?filter=``

    ``CollectionParameters`` types it ``dict | list[dict]``, and the rest of the backend reads it that
    way: ``BaseQueryBuilder.__init_query`` treats a dict as one ``$match`` and a list as stages to
    splice in, and ``objects_routes`` branches on both. The report routes must not wrap the value
    unconditionally, so a list produced ``{"$match": [...]}`` - which MongoDB rejects, making a
    documented filter shape answer 500.
    """

    def test_a_dict_becomes_one_match_stage(self) -> None:
        """The ordinary case: a Mongo query document."""
        assert build_report_filter_stages({'risk_category': 'Legal'}) == [
            {'$match': {'risk_category': 'Legal'}}
        ]

    def test_a_list_is_spliced_in_as_stages(self) -> None:
        """The shape most at risk of a 500: the caller already sent pipeline stages."""
        stages = [{'$match': {'priority': 3}}, {'$sort': {'risk_title': 1}}]

        assert build_report_filter_stages(stages) == stages

    def test_the_returned_list_is_a_copy(self) -> None:
        """The caller's list must not be mutated when the route appends its facet stage."""
        stages = [{'$match': {'priority': 3}}]

        result = build_report_filter_stages(stages)
        result.append({'$limit': 1})

        assert stages == [{'$match': {'priority': 3}}]

    def test_an_empty_filter_adds_no_stage(self) -> None:
        """
        No filter means no stage at all

        The frontend's treatment-plan component sends ``filter: ''``, which CollectionParameters
        normalises to ``{}`` - so this is the shape most requests actually take.
        """
        assert len(build_report_filter_stages({})) == 0
        assert len(build_report_filter_stages([])) == 0
        assert len(build_report_filter_stages(None)) == 0


# A page size above the bound, so the page is read through a cursor
LARGE_PAGE_LIMIT: int = REPORT_FACET_MAX_LIMIT + 1
# A total that differs from every row count below, so a test tells a counted total from a derived one
COUNTED_TOTAL: int = 4321
# Rows the stub manager answers - distinct values so a mix-up between reads shows
EXPORT_ROWS: list[dict[str, Any]] = [{'risk_title': 'Export A'}, {'risk_title': 'Export B'}]
FACET_ROWS: list[dict[str, Any]] = [{'risk_title': 'Page A'}]
FACET_TOTAL: int = 37
# The stage the caller's own pipeline consists of in the read_report_page tests
CALLER_STAGE: dict[str, Any] = {'$match': {'priority': 3}}


def _rows(count: int) -> list[dict[str, Any]]:
    """`count` distinct report rows"""
    return [{'risk_title': f'Row {index}'} for index in range(count)]


class _RecordingManager:
    """Answers each aggregation with the next queued result and records the pipeline and options it got"""

    def __init__(self, *results: list[dict[str, Any]]) -> None:
        self.results: list[list[dict[str, Any]]] = list(results)
        self.calls: list[tuple[list[dict[str, Any]], int, dict[str, Any]]] = []

    def aggregate_within_time_limit(
            self, pipeline: list[dict[str, Any]], time_limit_ms: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Records the call and answers the next queued result"""
        self.calls.append((pipeline, time_limit_ms, kwargs))
        return self.results.pop(0)

    def stage_names(self, call: int) -> list[str]:
        """The operator of every stage of one recorded aggregation"""
        return [next(iter(stage)) for stage in self.calls[call][0]]


class TestBuildReportRowsStages:
    """build_report_rows_stages pages the rows and drops the public_id tiebreaker."""

    def test_is_the_pagination_stages_then_the_projection(self) -> None:
        """The paging comes first, so the tiebreaker resolves before the projection drops it."""
        params = CollectionParameters('', sort='risk_title', order=-1, limit=25, page=2)

        assert build_report_rows_stages(params) == [
            *build_report_pagination_stages(params),
            {'$project': {'public_id': 0}},
        ]

    def test_limit_zero_has_no_limit_stage(self) -> None:
        """Every row: sort, skip nothing, project."""
        assert build_report_rows_stages(CollectionParameters('', limit='0')) == [
            {'$sort': {'public_id': 1}},
            {'$skip': 0},
            {'$project': {'public_id': 0}},
        ]


class TestBuildReportCountStage:
    """build_report_count_stage counts under the facet's total key."""

    def test_counts_under_total(self) -> None:
        """The same key the facet's total branch uses, so one reader serves both."""
        assert build_report_count_stage() == {'$count': 'total'}


class TestUsesReportFacet:
    """uses_report_facet keeps the one-document $facet to bounded pages."""

    def test_a_default_page_uses_the_facet(self) -> None:
        """The frontend's paged views (limit 10) read in one pass."""
        assert uses_report_facet(CollectionParameters('')) is True

    def test_the_bound_itself_uses_the_facet(self) -> None:
        """The bound is inclusive."""
        assert uses_report_facet(CollectionParameters('', limit=REPORT_FACET_MAX_LIMIT)) is True

    def test_above_the_bound_uses_a_cursor(self) -> None:
        """One row more and the page is read through a cursor."""
        assert uses_report_facet(CollectionParameters('', limit=LARGE_PAGE_LIMIT)) is False

    def test_limit_zero_uses_a_cursor(self) -> None:
        """The export: every row, so never inside one 16 MB document."""
        assert uses_report_facet(CollectionParameters('', limit='0')) is False


class TestTotalFromRows:
    """total_from_rows derives the total only when the rows decide it."""

    def test_limit_zero_counts_the_rows(self) -> None:
        """Every row was read, so the total is their number."""
        assert total_from_rows(_rows(3), CollectionParameters('', limit='0')) == 3

    def test_limit_zero_with_no_rows_is_zero(self) -> None:
        """An empty export has a total of 0."""
        assert total_from_rows([], CollectionParameters('', limit='0')) == 0

    def test_a_short_first_page_is_the_whole_result(self) -> None:
        """Fewer rows than the limit on page 1: nothing more exists."""
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT)

        assert total_from_rows(_rows(5), params) == 5

    def test_a_short_later_page_adds_the_skipped_rows(self) -> None:
        """The last page: the rows before it plus its own."""
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT, page=3)

        assert total_from_rows(_rows(7), params) == 2 * LARGE_PAGE_LIMIT + 7

    def test_an_empty_first_page_is_zero(self) -> None:
        """Nothing skipped and nothing read: the result is empty."""
        assert total_from_rows([], CollectionParameters('', limit=LARGE_PAGE_LIMIT)) == 0

    def test_a_full_page_needs_a_count(self) -> None:
        """More rows may follow, so the rows cannot tell."""
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT)

        assert total_from_rows(_rows(LARGE_PAGE_LIMIT), params) is None

    def test_an_empty_page_past_the_first_needs_a_count(self) -> None:
        """The result ends somewhere before the skip - where, the rows do not say."""
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT, page=2)

        assert total_from_rows([], params) is None


class TestExtractReportTotal:
    """extract_report_total reads a $count result."""

    def test_reads_the_count(self) -> None:
        """The one document $count answers."""
        assert extract_report_total([{'total': COUNTED_TOTAL}]) == COUNTED_TOTAL

    def test_no_document_is_zero(self) -> None:
        """$count answers nothing when no row reached it."""
        assert extract_report_total([]) == 0


class TestReadReportPage:
    """read_report_page picks one $facet pass for a page and a cursor for everything else."""

    def test_a_page_is_one_facet_pass(self) -> None:
        """One aggregation, ending in the facet, split into rows and total."""
        manager = _RecordingManager([{'data': FACET_ROWS, 'total': [{'total': FACET_TOTAL}]}])
        params = CollectionParameters('', limit=10)

        assert read_report_page(manager, [CALLER_STAGE], params) == (FACET_ROWS, FACET_TOTAL)
        assert manager.calls[0][0] == [CALLER_STAGE, build_report_facet_stage(params)]

    def test_an_export_is_one_cursor_read_without_a_facet(self) -> None:
        """limit=0: the rows stages only, and the total is the number of rows read."""
        manager = _RecordingManager(EXPORT_ROWS)
        params = CollectionParameters('', limit='0')

        assert read_report_page(manager, [CALLER_STAGE], params) == (EXPORT_ROWS, len(EXPORT_ROWS))
        assert manager.calls[0][0] == [CALLER_STAGE, *build_report_rows_stages(params)]
        assert len(manager.calls) == 1

    def test_a_full_large_page_counts_in_a_second_read(self) -> None:
        """Above the bound and full: the rows through a cursor, then the same pipeline counted."""
        rows = _rows(LARGE_PAGE_LIMIT)
        manager = _RecordingManager(rows, [{'total': COUNTED_TOTAL}])
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT)

        assert read_report_page(manager, [CALLER_STAGE], params) == (rows, COUNTED_TOTAL)
        assert manager.stage_names(0) == ['$match', '$sort', '$skip', '$limit', '$project']
        assert manager.calls[1][0] == [CALLER_STAGE, build_report_count_stage()]

    def test_a_short_large_page_needs_no_count(self) -> None:
        """Above the bound but the last page: the rows decide the total, one read only."""
        manager = _RecordingManager(EXPORT_ROWS)
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT, page=2)

        assert read_report_page(manager, [CALLER_STAGE], params) == (
            EXPORT_ROWS, LARGE_PAGE_LIMIT + len(EXPORT_ROWS),
        )
        assert len(manager.calls) == 1

    def test_an_empty_large_page_past_the_end_counts(self) -> None:
        """A page past the last row: no rows, and the total read by a count."""
        manager = _RecordingManager([], [{'total': COUNTED_TOTAL}])
        params = CollectionParameters('', limit=LARGE_PAGE_LIMIT, page=5)

        assert read_report_page(manager, [CALLER_STAGE], params) == ([], COUNTED_TOTAL)
        assert manager.stage_names(1) == ['$match', '$count']

    def test_every_read_runs_under_the_long_budget_with_disk_use(self) -> None:
        """Both reads of the counted path carry the budget and allowDiskUse."""
        manager = _RecordingManager(_rows(LARGE_PAGE_LIMIT), [])
        read_report_page(manager, [CALLER_STAGE], CollectionParameters('', limit=LARGE_PAGE_LIMIT))

        assert [(budget, options) for _pipeline, budget, options in manager.calls] == [
            (LONG_QUERY_TIME_LIMIT_MS, {'allowDiskUse': True}),
        ] * 2

    def test_the_callers_pipeline_is_not_changed(self) -> None:
        """The stages are added to a copy - the caller's list keeps only its own stage."""
        pipeline: list[dict[str, Any]] = [CALLER_STAGE]
        manager = _RecordingManager(_rows(LARGE_PAGE_LIMIT), [])
        read_report_page(manager, pipeline, CollectionParameters('', limit=LARGE_PAGE_LIMIT))

        assert pipeline == [CALLER_STAGE]
