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
Unit tests for build_isms_config_status

The helper is pure (no database): it maps the per-section entry counts plus the risk-matrix
"all cells classed" flag to the readiness booleans returned by GET /isms/config/status. The scale
sections become ready at their minimum thresholds, and the risk_matrix flag additionally requires
all three scale sections to be ready.

``is_risk_matrix_ready`` judges the stored matrix without repairing it: missing, stale (another cell count than
impacts x likelihoods) or not fully classed is not ready.
"""
from typing import Any

import pytest

from cmdb.interface.rest_api.routes.isms_routes.isms_config_helper import (
    build_isms_config_status,
    is_risk_matrix_ready,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    MIN_CONFIGURED_RISK_CLASSES,
    MIN_CONFIGURED_LIKELIHOODS,
    MIN_CONFIGURED_IMPACTS,
    MIN_CONFIGURED_IMPACT_CATEGORIES,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestBuildIsmsConfigStatus:
    """build_isms_config_status maps entry counts to per-section readiness flags."""

    def test_all_zero_counts_are_not_ready(self) -> None:
        """With nothing configured every flag is False."""
        assert build_isms_config_status(0, 0, 0, 0, False) == {
            'risk_classes': False,
            'likelihoods': False,
            'impacts': False,
            'impact_categories': False,
            'risk_matrix': False,
        }

    def test_each_section_ready_at_its_minimum(self) -> None:
        """Every scale section flips to ready exactly at its configured minimum."""
        status = build_isms_config_status(
            MIN_CONFIGURED_RISK_CLASSES,
            MIN_CONFIGURED_LIKELIHOODS,
            MIN_CONFIGURED_IMPACTS,
            MIN_CONFIGURED_IMPACT_CATEGORIES,
            True,
        )

        assert status['risk_classes'] is True
        assert status['likelihoods'] is True
        assert status['impacts'] is True
        assert status['impact_categories'] is True

    def test_one_below_minimum_is_not_ready(self) -> None:
        """A count one short of the minimum keeps that section not ready."""
        status = build_isms_config_status(
            MIN_CONFIGURED_RISK_CLASSES - 1,
            MIN_CONFIGURED_LIKELIHOODS,
            MIN_CONFIGURED_IMPACTS,
            MIN_CONFIGURED_IMPACT_CATEGORIES,
            True,
        )

        assert status['risk_classes'] is False

    def test_risk_matrix_requires_all_scale_sections_ready(self) -> None:
        """Even with all cells classed, risk_matrix stays False while a scale section is short."""
        status = build_isms_config_status(
            MIN_CONFIGURED_RISK_CLASSES,
            MIN_CONFIGURED_LIKELIHOODS,
            MIN_CONFIGURED_IMPACTS - 1,
            MIN_CONFIGURED_IMPACT_CATEGORIES,
            True,
        )

        assert status['risk_matrix'] is False

    def test_risk_matrix_requires_all_cells_classed(self) -> None:
        """With every scale section ready, risk_matrix follows the all-cells-classed flag."""
        ready_counts = (
            MIN_CONFIGURED_RISK_CLASSES,
            MIN_CONFIGURED_LIKELIHOODS,
            MIN_CONFIGURED_IMPACTS,
            MIN_CONFIGURED_IMPACT_CATEGORIES,
        )

        assert build_isms_config_status(*ready_counts, False)['risk_matrix'] is False
        assert build_isms_config_status(*ready_counts, True)['risk_matrix'] is True

    def test_impact_categories_independent_of_risk_matrix(self) -> None:
        """impact_categories readiness does not feed into the risk_matrix flag."""
        status = build_isms_config_status(
            MIN_CONFIGURED_RISK_CLASSES,
            MIN_CONFIGURED_LIKELIHOODS,
            MIN_CONFIGURED_IMPACTS,
            0,
            True,
        )

        assert status['impact_categories'] is False
        assert status['risk_matrix'] is True


# ----------------------------------------------- is_risk_matrix_ready ----------------------------------------------- #

IMPACTS: int = 3
LIKELIHOODS: int = 2
CLASSED_CELL: dict[str, int] = {'risk_class_id': 7}
UNCLASSED_CELL: dict[str, int] = {'risk_class_id': 0}


def _matrix(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """A stored IsmsRiskMatrix holding ``cells``"""
    return {'public_id': 1, 'risk_matrix': cells, 'matrix_unit': None}


class TestIsRiskMatrixReady:
    """Current and fully classed, as stored"""

    def test_a_current_fully_classed_grid_is_ready(self) -> None:
        """One classed cell per pair"""
        assert is_risk_matrix_ready(_matrix([CLASSED_CELL] * (IMPACTS * LIKELIHOODS)), IMPACTS, LIKELIHOODS)

    @pytest.mark.parametrize('cells', [
        [CLASSED_CELL] * (IMPACTS * LIKELIHOODS - 1),
        [CLASSED_CELL] * (IMPACTS * LIKELIHOODS + 1),
        [],
    ], ids=['short', 'too-many', 'empty'])
    def test_a_stale_grid_is_not_ready(self, cells: list[dict[str, Any]]) -> None:
        """Every stored cell classed, but not one per pair of the current scales"""
        assert not is_risk_matrix_ready(_matrix(cells), IMPACTS, LIKELIHOODS)

    def test_an_unclassed_cell_is_not_ready(self) -> None:
        """The right size, one cell without a class"""
        cells = [CLASSED_CELL] * (IMPACTS * LIKELIHOODS - 1) + [UNCLASSED_CELL]

        assert not is_risk_matrix_ready(_matrix(cells), IMPACTS, LIKELIHOODS)

    @pytest.mark.parametrize('stored', [None, {}], ids=['missing', 'empty-document'])
    def test_a_missing_matrix_is_not_ready(self, stored: dict[str, Any] | None) -> None:
        """Reported, not recreated"""
        assert not is_risk_matrix_ready(stored, IMPACTS, LIKELIHOODS)

    def test_empty_scales_and_an_empty_grid_are_not_ready(self) -> None:
        """0 x 0 cells match, but a grid with no cells is never finished"""
        assert not is_risk_matrix_ready(_matrix([]), 0, 0)
