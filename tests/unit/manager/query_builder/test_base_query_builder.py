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

import pytest

from cmdb.manager.query_builder.base_query_builder import BaseQueryBuilder
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.manager.query_builder.query_builder_constants import SortPipeline
# -------------------------------------------------------------------------------------------------------------------- #

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
