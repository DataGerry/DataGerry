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

``GET /isms/config/status`` needs no right, so it only reads: the counts and the stored IsmsRiskMatrix go in,
the five readiness flags come out. The matrix is judged as stored, without the repair
``GET /isms/risk_matrix/1`` performs - ``is_risk_matrix_ready`` holds a missing matrix, and a grid whose shape
no longer matches the scales, to "not ready" instead of fixing them
"""
from typing import Any

from cmdb.models.isms_model.isms_helper import check_risk_classes_set_in_matrix
from cmdb.models.isms_model.isms_risk_matrix_constants import RiskMatrixKey
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    IsmsConfigStatusKey,
    MIN_CONFIGURED_RISK_CLASSES,
    MIN_CONFIGURED_LIKELIHOODS,
    MIN_CONFIGURED_IMPACTS,
    MIN_CONFIGURED_IMPACT_CATEGORIES,
)
# -------------------------------------------------------------------------------------------------------------------- #


def is_risk_matrix_ready(risk_matrix: dict[str, Any] | None, impact_amount: int, likelihood_amount: int) -> bool:
    """
    Judges whether the stored IsmsRiskMatrix is finished, without repairing it

    Ready means: it exists, it holds exactly one cell per (impact, likelihood) pair of the current scales, and
    every cell has a risk class. A grid of another size is stale - a restored dump, or one built under the old
    minimum-configuration guard - and ``GET /isms/risk_matrix/1`` rebuilds it on its next read, possibly with
    unassigned cells, so it is not counted as finished before that

    Args:
        risk_matrix (dict[str, Any] | None): The stored IsmsRiskMatrix, or None when it does not exist
        impact_amount (int): Number of IsmsImpacts
        likelihood_amount (int): Number of IsmsLikelihoods

    Returns:
        bool: True when the matrix is current and fully classed
    """
    if not risk_matrix:
        return False

    cells: list[Any] = risk_matrix.get(RiskMatrixKey.RISK_MATRIX) or []

    if len(cells) != impact_amount * likelihood_amount:
        return False

    return check_risk_classes_set_in_matrix(risk_matrix)


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
        risk_matrix_classes_set (bool): Whether the RiskMatrix is current and every cell has a risk class
            (``is_risk_matrix_ready``)

    Returns:
        dict[str, bool]: Readiness flag per configuration section
    """
    risk_classes_ready: bool = risk_class_amount >= MIN_CONFIGURED_RISK_CLASSES
    likelihoods_ready: bool = likelihood_amount >= MIN_CONFIGURED_LIKELIHOODS
    impacts_ready: bool = impact_amount >= MIN_CONFIGURED_IMPACTS

    return {
        IsmsConfigStatusKey.RISK_CLASSES.value: risk_classes_ready,
        IsmsConfigStatusKey.LIKELIHOODS.value: likelihoods_ready,
        IsmsConfigStatusKey.IMPACTS.value: impacts_ready,
        IsmsConfigStatusKey.IMPACT_CATEGORIES.value: impact_category_amount >= MIN_CONFIGURED_IMPACT_CATEGORIES,
        IsmsConfigStatusKey.RISK_MATRIX.value: (
            risk_matrix_classes_set and risk_classes_ready and likelihoods_ready and impacts_ready
        ),
    }
