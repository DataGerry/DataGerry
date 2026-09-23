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
Unit tests for cmdb.manager.query_builder.base_query_builder.BaseQueryBuilder

Pure tests: no Mongo. Each test invokes ``BaseQueryBuilder.build`` with hand-built
``BuilderParameters`` and asserts on the shape of the generated aggregation pipeline.
The focus is the ``_append_sort_stage`` branch that handles ``fields.<name>`` sort
keys, since that is the path the routes hit for column sorting in the object list
"""
from typing import Any

from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.query_builder.base_query_builder import BaseQueryBuilder
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.manager.query_builder.query_builder_constants import SortPipeline
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.query_builder.base_query_builder'

PUBLIC_ID_FIELD: str = 'public_id'
TIEBREAK_ORDER: int = 1

EMPTY_CRITERIA: list[dict[str, Any]] = []
SAMPLE_FIELD_NAME: str = 'text-19742'
SAMPLE_SORT_KEY: str = f'{SortPipeline.FIELDS_PREFIX}{SAMPLE_FIELD_NAME}'


def _find_stage(pipeline: list[dict[str, Any]], stage_op: str) -> dict[str, Any] | None:
    """Returns the first stage in ``pipeline`` whose top-level operator is ``stage_op``."""
    for stage in pipeline:
        if stage_op in stage:
            return stage
    return None


def _find_stages(pipeline: list[dict[str, Any]], stage_op: str) -> list[dict[str, Any]]:
    """Returns every stage in ``pipeline`` whose top-level operator is ``stage_op``."""
    return [stage for stage in pipeline if stage_op in stage]


# -------------------------------------------------------------------------------------------------------------------- #
#                                       fields.<name> SORT PIPELINE                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFieldsSortPipeline:
    """Behavior of ``build`` when the sort key targets a value inside the ``fields`` array."""

    @pytest.mark.parametrize('order', [1, -1])
    def test_emits_addfields_sort_and_project_stages(self, order: int) -> None:
        """For ``fields.<name>`` keys, build emits an $addFields, a $sort, and a $project drop stage."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=SAMPLE_SORT_KEY, order=order)

        pipeline = BaseQueryBuilder().build(params)

        assert _find_stage(pipeline, '$addFields') is not None
        assert _find_stage(pipeline, '$sort') is not None
        project_stage = _find_stage(pipeline, '$project')
        assert project_stage is not None
        assert project_stage['$project'] == {SortPipeline.TEMP_KEY: 0}

    def test_addfields_filters_by_inner_field_name_only(self) -> None:
        """The ``fields.`` prefix must be stripped before matching against ``$$f.name``."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=SAMPLE_SORT_KEY, order=1)

        pipeline = BaseQueryBuilder().build(params)
        add_fields = _find_stage(pipeline, '$addFields')

        assert add_fields is not None
        convert_input = add_fields['$addFields'][SortPipeline.TEMP_KEY]['$toLower']['$convert']['input']
        filter_stage = convert_input['$first']['$map']['input']['$filter']
        assert filter_stage['input'] == '$fields'
        assert filter_stage['cond'] == {'$eq': ['$$f.name', SAMPLE_FIELD_NAME]}

    def test_sort_stage_uses_temp_key_with_public_id_tiebreaker(self) -> None:
        """The $sort stage must sort on the temp key and tiebreak ascending on public_id."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=SAMPLE_SORT_KEY, order=-1)

        pipeline = BaseQueryBuilder().build(params)
        sort_stage = _find_stage(pipeline, '$sort')

        assert sort_stage is not None
        assert sort_stage['$sort'] == {SortPipeline.TEMP_KEY: -1, PUBLIC_ID_FIELD: TIEBREAK_ORDER}

    def test_convert_to_string_uses_safe_defaults(self) -> None:
        """The $convert step must default to empty-string on null/non-castable values."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=SAMPLE_SORT_KEY, order=1)

        pipeline = BaseQueryBuilder().build(params)
        add_fields = _find_stage(pipeline, '$addFields')

        assert add_fields is not None
        convert_stage = add_fields['$addFields'][SortPipeline.TEMP_KEY]['$toLower']['$convert']
        assert convert_stage['to'] == 'string'
        assert convert_stage['onError'] == ''
        assert convert_stage['onNull'] == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                       PLAIN SORT KEY (e.g. public_id)                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPlainSortPipeline:
    """Behavior of ``build`` when the sort key is a regular top-level path."""

    def test_emits_single_plain_sort_stage(self) -> None:
        """A non-fields key produces exactly one $sort stage with no $addFields / $project."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=PUBLIC_ID_FIELD, order=-1)

        pipeline = BaseQueryBuilder().build(params)

        assert _find_stage(pipeline, '$addFields') is None
        assert _find_stage(pipeline, '$project') is None
        sort_stages = _find_stages(pipeline, '$sort')
        assert len(sort_stages) == 1
        assert sort_stages[0]['$sort'] == {PUBLIC_ID_FIELD: -1}

    @pytest.mark.parametrize('bad_order', [0, 2, -2])
    def test_invalid_order_is_rejected_for_plain_sort(self, bad_order: int) -> None:
        """The underlying ``sort_`` helper raises on orders outside {-1, 1}."""
        params = BuilderParameters(criteria=EMPTY_CRITERIA, sort=PUBLIC_ID_FIELD, order=bad_order)

        with pytest.raises(ValueError):
            BaseQueryBuilder().build(params)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             count + the builder protocol                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCount:
    """`count` wraps the query in a $count stage, ACL-filtered when a user and permission are given."""

    def test_appends_a_count_stage(self) -> None:
        """The caller reads a single 'total' out of the result, so the stage has to be last."""
        query = BaseQueryBuilder().count(EMPTY_CRITERIA)

        assert query[-1] == {'$count': 'total'}

    def test_without_a_user_the_query_carries_no_acl_stages(self) -> None:
        """An internal count has no requesting user; adding ACL stages would filter against nobody."""
        query = BaseQueryBuilder().count(EMPTY_CRITERIA)

        assert not any('type_id' in str(stage) for stage in query)

    def test_the_acl_filter_precedes_the_count(self) -> None:
        """
        A total counted before the ACL filter is the wrong number

        It is what a pager divides into pages, so counting rows the user may not read would show
        them page links to nothing.
        """
        user = MagicMock()

        with patch(f'{MODULE_PATH}.build_acl_pipeline', return_value=[{'$match': {'acl': True}}]) as acl:
            query = BaseQueryBuilder().count(EMPTY_CRITERIA, user, AccessControlPermission.READ)

        acl.assert_called_once_with(user, AccessControlPermission.READ)
        assert query.index({'$match': {'acl': True}}) < query.index({'$count': 'total'})

    @pytest.mark.parametrize('user, permission', [
        (None, AccessControlPermission.READ),
        (MagicMock(), None),
        (None, None),
    ], ids=['no-user', 'no-permission', 'neither'])
    def test_both_are_required_for_the_acl_stages(self, user, permission) -> None:
        """Half an ACL filter is not a weaker filter - it is one that matches on the wrong thing."""
        with patch(f'{MODULE_PATH}.build_acl_pipeline') as acl:
            BaseQueryBuilder().count(EMPTY_CRITERIA, user, permission)

        acl.assert_not_called()


class TestTheBuilderProtocol:
    """`__len__` is declared abstract on `Builder`, so every concrete builder has to implement it."""

    def test_an_empty_builder_has_no_stages(self) -> None:
        """`len(builder)` is the stage count, which is 0 before anything is built."""
        assert len(BaseQueryBuilder()) == 0

    def test_it_reports_the_number_of_stages(self) -> None:
        """Removing this method makes the class abstract and uninstantiable - it is not dead code."""
        builder = BaseQueryBuilder()
        builder.count(EMPTY_CRITERIA)

        assert len(builder) == len(builder.query)


# -------------------------------------------------------------------------------------------------------------------- #
#                                     how a criteria becomes stages                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestHowCriteriaBecomesStages:
    """
    The branch a client pipeline reaches, and the reason the guard is not here

    A dict criteria becomes one `$match`; a **list** criteria is spliced into the aggregation
    verbatim, stage for stage. Unguarded that is reachable straight from `?filter=`, so a
    caller could append `$lookup` and read any collection in the database.

    The splice itself is deliberate and stays: the frontend builds real stages, and `objects_manager`
    hands its own `$lookup` + `$unwind` pipeline in here as criteria. What changed is upstream -
    `CollectionParameters` now refuses a client filter that is not on the allow-list, so by the time
    a client's value reaches this method it has already been checked. These tests pin the splice, not
    the checking; the guard's own unit tests
    pins that.
    """

    def test_a_dict_criteria_becomes_a_single_match(self) -> None:
        """One stage, wrapping the document as given."""
        params = BuilderParameters(criteria={PUBLIC_ID_FIELD: 5}, sort=PUBLIC_ID_FIELD, order=1)

        pipeline = BaseQueryBuilder().build(params)

        assert pipeline[0] == {'$match': {PUBLIC_ID_FIELD: 5}}

    def test_a_list_criteria_is_spliced_in_verbatim(self) -> None:
        """
        Every element becomes a stage, unchanged and in order

        This is what makes a list filter powerful enough to be worth guarding: whatever is in the
        list is what MongoDB runs.
        """
        stages: list[dict[str, Any]] = [
            {'$match': {PUBLIC_ID_FIELD: 5}},
            {'$addFields': {'public_id_str': {'$toString': f'${PUBLIC_ID_FIELD}'}}},
        ]
        params = BuilderParameters(criteria=stages, sort=PUBLIC_ID_FIELD, order=1)

        pipeline = BaseQueryBuilder().build(params)

        assert pipeline[:2] == stages

    def test_the_builders_own_stages_always_follow_the_criteria(self) -> None:
        """
        Why `$out` / `$merge` fail on their own, and why that is not a guard

        The pager appends `$sort` / `$skip` after the client's stages, so a write stage - which must
        be last - was rejected by MongoDB for a reason that had nothing to do with permission. A
        pipeline that put a client stage last would have written.
        """
        params = BuilderParameters(criteria=[{'$match': {}}], sort=PUBLIC_ID_FIELD, order=1)

        pipeline = BaseQueryBuilder().build(params)

        assert pipeline[-1] != {'$match': {}}
        assert any('$skip' in stage for stage in pipeline)

    def test_a_list_criteria_reaches_the_count_pipeline_too(self) -> None:
        """
        `count()` splices the same list, and the totals aggregation is a second execution of it

        A guard placed in only one of the two would have left the other open.
        """
        stages: list[dict[str, Any]] = [{'$match': {PUBLIC_ID_FIELD: 5}}]

        pipeline = BaseQueryBuilder().count(stages)

        assert pipeline[0] == stages[0]
        assert pipeline[-1] == {'$count': 'total'}
