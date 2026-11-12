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
Unit tests for cmdb.framework.ci_explorer.neighbour_budget - what one item_limit slot is

One slot is one distinct neighbour: the first ``remaining`` neighbours of a list sorted by neighbour id are kept with
every entry (edge) that reaches them, and the cut reports whether anything was left out.
"""
import pytest

from cmdb.framework.ci_explorer.neighbour_budget import count_neighbours, cut_to_neighbour_budget
# -------------------------------------------------------------------------------------------------------------------- #


def _neighbour(entry: tuple[int, str]) -> int:
    """The neighbour an (id, edge) entry reaches"""
    return entry[0]


SORTED_EDGES: list[tuple[int, str]] = [(1, 'a'), (1, 'b'), (2, 'a'), (3, 'a'), (3, 'b')]


@pytest.mark.parametrize('remaining, kept', [
    (0, []),
    (1, [(1, 'a'), (1, 'b')]),
    (2, [(1, 'a'), (1, 'b'), (2, 'a')]),
    (3, SORTED_EDGES),
], ids=['none', 'one', 'two', 'all'])
def test_the_first_neighbours_are_kept_with_all_their_edges(remaining: int, kept: list[tuple[int, str]]) -> None:
    """A neighbour reached twice costs one slot"""
    assert cut_to_neighbour_budget(SORTED_EDGES, remaining, _neighbour)[0] == kept


@pytest.mark.parametrize('remaining, truncated', [(0, True), (2, True), (3, False), (10, False)])
def test_the_cut_reports_whether_a_neighbour_was_left_out(remaining: int, truncated: bool) -> None:
    """What a source logs"""
    assert cut_to_neighbour_budget(SORTED_EDGES, remaining, _neighbour)[1] is truncated


def test_an_empty_list_is_no_cut() -> None:
    """Nothing to keep, nothing left out"""
    assert cut_to_neighbour_budget([], 0, _neighbour) == ([], False)


def test_the_input_is_not_changed() -> None:
    """The source's list stays as it was"""
    edges = list(SORTED_EDGES)

    cut_to_neighbour_budget(edges, 1, _neighbour)

    assert edges == SORTED_EDGES


def test_distinct_neighbours_are_counted() -> None:
    """What a source spends of the shared budget"""
    assert count_neighbours(SORTED_EDGES, _neighbour) == 3
    assert count_neighbours([], _neighbour) == 0


def test_a_missing_id_counts_as_one_neighbour() -> None:
    """The orchestrator drops such a document later; counting must not fail first"""
    assert count_neighbours([(None, 'a'), (None, 'b'), (1, 'a')], _neighbour) == 2
