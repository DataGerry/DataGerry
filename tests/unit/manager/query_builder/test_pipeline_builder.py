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
Unit tests for PipelineBuilder

The base of every aggregation builder in the manager layer - `SearchPipelineBuilder`,
`QuickSearchPipelineBuilder`, `SearchReferencesPipelineBuilder` and, through `BaseQueryBuilder`,
every paged read. It owns the stage list itself: appending to it, replacing it, clearing it and
reporting its length.

`__len__` and `clear` have no obvious caller, which makes them look like dead code. They are not:
`Builder` declares `__len__` **abstract**, so removing it makes every concrete builder
uninstantiable, and `BaseQueryBuilder.clear` delegates here. Both are tested below so a caller-grep
does not lead to their removal.
"""
import pytest

from cmdb.manager.query_builder.pipeline_builder import PipelineBuilder
from cmdb.manager.query_builder.builder import Builder
# pylint: disable=use-implicit-booleaness-not-comparison
# `== []` rather than `not ...`: these assert the pipeline is an empty LIST, which is what the
# builders hand to pymongo - `not x` would also pass for None.
# -------------------------------------------------------------------------------------------------------------------- #

MATCH_STAGE: dict = {'$match': {'active': True}}
LIMIT_STAGE: dict = {'$limit': 10}


class TestTheStageList:
    """The pipeline is the builder's only state."""

    def test_a_new_builder_is_empty(self) -> None:
        """Nothing is assumed about the pipeline until a caller adds a stage."""
        assert PipelineBuilder().pipeline == []

    def test_a_given_pipeline_is_adopted(self) -> None:
        """`SearcherFramework` hands an already-built pipeline in for the builder to extend."""
        assert PipelineBuilder([MATCH_STAGE]).pipeline == [MATCH_STAGE]

    def test_the_default_is_not_shared_between_builders(self) -> None:
        """A mutable default would leak one search's stages into the next one."""
        first = PipelineBuilder()
        first.add_pipe(MATCH_STAGE)

        assert PipelineBuilder().pipeline == []

    def test_add_pipe_appends_in_order(self) -> None:
        """Stage order is the aggregation's semantics, not a detail."""
        builder = PipelineBuilder()
        builder.add_pipe(MATCH_STAGE)
        builder.add_pipe(LIMIT_STAGE)

        assert builder.pipeline == [MATCH_STAGE, LIMIT_STAGE]

    def test_the_pipeline_can_be_replaced_wholesale(self) -> None:
        """`SearchPipelineBuilder.build` rebuilds the list rather than appending to it."""
        builder = PipelineBuilder([MATCH_STAGE])
        builder.pipeline = [LIMIT_STAGE]

        assert builder.pipeline == [LIMIT_STAGE]


class TestClear:
    """Emptying the builder for reuse."""

    def test_clear_empties_the_pipeline(self) -> None:
        """`BaseQueryBuilder.clear` delegates here - this is not an unused convenience."""
        builder = PipelineBuilder([MATCH_STAGE, LIMIT_STAGE])
        builder.clear()

        assert builder.pipeline == []

    def test_clearing_an_empty_builder_is_a_no_op(self) -> None:
        """Reuse must not depend on whether anything was built first."""
        builder = PipelineBuilder()
        builder.clear()

        assert builder.pipeline == []

    def test_a_cleared_builder_can_be_used_again(self) -> None:
        """The point of clearing is the next build, so the list has to stay usable."""
        builder = PipelineBuilder([MATCH_STAGE])
        builder.clear()
        builder.add_pipe(LIMIT_STAGE)

        assert builder.pipeline == [LIMIT_STAGE]


class TestLen:
    """`__len__` implements an abstract method - it cannot be removed."""

    def test_it_is_declared_abstract_on_the_base(self) -> None:
        """
        This is why removing the override does not just lose a convenience

        It makes the concrete class abstract, and every manager that constructs a query builder dies
        with `TypeError: Can't instantiate abstract class ... without an implementation for '__len__'`.
        """
        assert '__len__' in Builder.__abstractmethods__

    def test_an_empty_builder_has_length_zero(self) -> None:
        """The stage count of a builder nothing has been added to."""
        assert len(PipelineBuilder()) == 0

    def test_it_counts_the_stages(self) -> None:
        """Not the documents a stage matches - the stages themselves."""
        assert len(PipelineBuilder([MATCH_STAGE, LIMIT_STAGE])) == 2

    def test_it_follows_the_pipeline(self) -> None:
        """Reading a stale count after a clear would misreport an empty pipeline as full."""
        builder = PipelineBuilder([MATCH_STAGE])
        builder.clear()

        assert len(builder) == 0


class TestBuild:
    """The one method a subclass has to provide."""

    def test_the_base_refuses_to_build(self) -> None:
        """`PipelineBuilder` owns the stage list; what goes in it is the subclass's business."""
        with pytest.raises(NotImplementedError):
            PipelineBuilder().build()
