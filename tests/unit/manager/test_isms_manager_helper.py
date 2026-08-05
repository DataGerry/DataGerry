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
Unit tests for the pure ISMS manager helper recompute_max_impact

recompute_max_impact is database-free: given a RiskAssessment matrix's ``impacts`` entries and a
``{impact_id: calculation_basis}`` lookup, it returns the (id, value) of the impact with the highest
basis, or (None, None) when none of the entries has a known basis. It is shared by the ImpactManager
and ImpactCategoryManager recompute paths.
"""
from cmdb.manager.isms_manager.isms_manager_helper import recompute_max_impact
# -------------------------------------------------------------------------------------------------------------------- #

BASIS_BY_ID: dict[int, float] = {1: 1.0, 2: 2.5, 3: 2.0}


class TestRecomputeMaxImpact:
    """recompute_max_impact selects the highest-basis impact from a matrix."""

    def test_empty_matrix_returns_none_none(self) -> None:
        """An empty impacts list yields (None, None)."""
        assert recompute_max_impact([], BASIS_BY_ID) == (None, None)

    def test_single_entry_returns_its_id_and_basis(self) -> None:
        """A single known impact returns its id and calculation_basis."""
        assert recompute_max_impact([{'impact_id': 1}], BASIS_BY_ID) == (1, 1.0)

    def test_returns_entry_with_highest_basis(self) -> None:
        """Across several impacts the one with the highest basis wins (id 2 at 2.5)."""
        impacts = [{'impact_id': 1}, {'impact_id': 2}, {'impact_id': 3}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (2, 2.5)

    def test_entries_without_impact_id_are_skipped(self) -> None:
        """Entries whose impact_id is None are ignored."""
        impacts = [{'impact_id': None}, {'impact_id': 3}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (3, 2.0)

    def test_unknown_impact_ids_are_skipped(self) -> None:
        """An impact_id absent from the basis lookup is ignored."""
        impacts = [{'impact_id': 99}, {'impact_id': 1}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (1, 1.0)

    def test_only_unknown_ids_returns_none_none(self) -> None:
        """When no entry has a known basis the result is (None, None)."""
        assert recompute_max_impact([{'impact_id': 99}], BASIS_BY_ID) == (None, None)

    def test_entries_with_none_basis_are_skipped(self) -> None:
        """An impact whose recorded basis is None does not become the maximum."""
        assert recompute_max_impact([{'impact_id': 1}, {'impact_id': 2}], {1: None, 2: 1.5}) == (2, 1.5)
