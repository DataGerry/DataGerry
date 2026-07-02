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
Pure helper logic for the ISMS configuration-status route
"""
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    MIN_CONFIGURED_RISK_CLASSES,
    MIN_CONFIGURED_LIKELIHOODS,
    MIN_CONFIGURED_IMPACTS,
    MIN_CONFIGURED_IMPACT_CATEGORIES,
)
# -------------------------------------------------------------------------------------------------------------------- #


def build_isms_config_status(
        risk_class_amount: int,
        likelihood_amount: int,
        impact_amount: int,
        impact_category_amount: int,
        risk_matrix_classes_set: bool) -> dict[str, bool]:
    """
    Builds the per-section readiness flags reported by GET /isms/config/status.

    A section is "ready" once it holds at least its minimum configured entries. The risk matrix is
    only ready when every cell has a risk class assigned AND the three scale sections it is derived
    from (risk classes, likelihoods, impacts) are themselves ready.

    Args:
        risk_class_amount (int): Number of configured IsmsRiskClasses
        likelihood_amount (int): Number of configured IsmsLikelihoods
        impact_amount (int): Number of configured IsmsImpacts
        impact_category_amount (int): Number of configured IsmsImpactCategories
        risk_matrix_classes_set (bool): Whether every RiskMatrix cell has a risk_class_id assigned

    Returns:
        dict[str, bool]: Readiness flag per configuration section
    """
    risk_classes_ready: bool = risk_class_amount >= MIN_CONFIGURED_RISK_CLASSES
    likelihoods_ready: bool = likelihood_amount >= MIN_CONFIGURED_LIKELIHOODS
    impacts_ready: bool = impact_amount >= MIN_CONFIGURED_IMPACTS

    return {
        'risk_classes': risk_classes_ready,
        'likelihoods': likelihoods_ready,
        'impacts': impacts_ready,
        'impact_categories': impact_category_amount >= MIN_CONFIGURED_IMPACT_CATEGORIES,
        'risk_matrix': risk_matrix_classes_set and risk_classes_ready and likelihoods_ready and impacts_ready,
    }
