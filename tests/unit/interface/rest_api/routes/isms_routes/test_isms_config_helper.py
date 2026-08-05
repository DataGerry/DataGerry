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
"""
from cmdb.interface.rest_api.routes.isms_routes.isms_config_helper import build_isms_config_status
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
