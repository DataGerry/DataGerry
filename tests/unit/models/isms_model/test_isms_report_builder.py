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
Unit tests for IsmsReportBuilder.build_risk_matrix_report

The builder is isolated from Mongo with stub managers. Covers the before/current/after cell counting,
the current-state 'Implemented' branch, and the two guards added with the query optimisation: a
missing 'Implemented' option (nothing counts as implemented) and a missing RiskMatrix (empty matrices)
must both avoid the previous None-dereference crash.
"""
from typing import Any, Optional

from cmdb.models.isms_model import IsmsReportBuilder
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_ID: int = 10
LIKELIHOOD_ID: int = 20
OTHER_IMPACT_ID: int = 11
OTHER_LIKELIHOOD_ID: int = 21
RISK_CLASS_ID: int = 3
IMPLEMENTED_STATUS_ID: int = 99

RISK_ASSESSMENT_ID: int = 1

MATRIX_BEFORE: str = 'risk_matrix_before_treatment'
MATRIX_CURRENT: str = 'risk_matrix_current_state'
MATRIX_AFTER: str = 'risk_matrix_after_treatment'


class _StubRiskAssessmentManager:
    """Serves a fixed list of risk-assessment documents."""

    def __init__(self, risk_assessments: list[dict[str, Any]]) -> None:
        self._risk_assessments = risk_assessments

    def find_all(self) -> list[dict[str, Any]]:
        """Returns the configured risk assessments."""
        return self._risk_assessments


class _StubRiskMatrixManager:
    """Serves a fixed RiskMatrix document (or None when absent)."""

    def __init__(self, matrix: Optional[dict[str, Any]]) -> None:
        self._matrix = matrix

    def get_item(self, _public_id: int, **_kwargs: Any) -> Optional[dict[str, Any]]:
        """Returns the configured matrix document."""
        return self._matrix


class _StubExtendableOptionsManager:
    """Serves a fixed 'Implemented' option (or None when it does not exist)."""

    def __init__(self, implemented_option: Optional[dict[str, Any]]) -> None:
        self._implemented_option = implemented_option

    def get_one_by(self, _criteria: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Returns the configured 'Implemented' option."""
        return self._implemented_option


def _matrix_with_one_cell() -> dict[str, Any]:
    """A RiskMatrix with a single cell at (IMPACT_ID, LIKELIHOOD_ID)."""
    return {
        'risk_matrix': [{
            'row': 0, 'column': 0, 'impact_id': IMPACT_ID,
            'likelihood_id': LIKELIHOOD_ID, 'risk_class_id': RISK_CLASS_ID,
        }]
    }


def _assessment(implementation_status: Optional[int]) -> dict[str, Any]:
    """An assessment whose before-matrix hits the cell and after-matrix does not."""
    return {
        'public_id': RISK_ASSESSMENT_ID,
        'implementation_status': implementation_status,
        'risk_calculation_before': {'maximum_impact_id': IMPACT_ID, 'likelihood_id': LIKELIHOOD_ID},
        'risk_calculation_after': {'maximum_impact_id': OTHER_IMPACT_ID, 'likelihood_id': OTHER_LIKELIHOOD_ID},
    }


def _build(risk_assessments: list[dict[str, Any]], matrix: Optional[dict[str, Any]],
           implemented_option: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Runs build_risk_matrix_report with the given stubbed data."""
    builder = IsmsReportBuilder(
        _StubRiskAssessmentManager(risk_assessments),
        _StubRiskMatrixManager(matrix),
        _StubExtendableOptionsManager(implemented_option),
    )
    return builder.build_risk_matrix_report()


def _cell(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the single cell of a built matrix."""
    return matrix[0]


def test_before_treatment_counts_matching_assessment() -> None:
    """The before-treatment matrix counts the assessment whose before-values hit the cell."""
    report = _build([_assessment(IMPLEMENTED_STATUS_ID)], _matrix_with_one_cell(),
                    {'public_id': IMPLEMENTED_STATUS_ID})

    assert _cell(report[MATRIX_BEFORE])['count'] == 1
    assert _cell(report[MATRIX_BEFORE])['risk_assessment_ids'] == [RISK_ASSESSMENT_ID]


def test_after_treatment_does_not_count_non_matching() -> None:
    """The after-treatment matrix does not count the assessment (its after-values miss the cell)."""
    report = _build([_assessment(IMPLEMENTED_STATUS_ID)], _matrix_with_one_cell(),
                    {'public_id': IMPLEMENTED_STATUS_ID})

    assert _cell(report[MATRIX_AFTER])['count'] == 0


def test_current_state_uses_after_values_when_implemented() -> None:
    """An implemented assessment contributes its after-values to the current-state matrix (miss here)."""
    report = _build([_assessment(IMPLEMENTED_STATUS_ID)], _matrix_with_one_cell(),
                    {'public_id': IMPLEMENTED_STATUS_ID})

    assert _cell(report[MATRIX_CURRENT])['count'] == 0


def test_missing_implemented_option_treats_nothing_as_implemented() -> None:
    """With no 'Implemented' option, current-state falls back to before-values (no crash)."""
    report = _build([_assessment(IMPLEMENTED_STATUS_ID)], _matrix_with_one_cell(), None)

    assert _cell(report[MATRIX_CURRENT])['count'] == 1


def test_missing_matrix_yields_empty_matrices() -> None:
    """A missing RiskMatrix singleton yields empty matrices instead of crashing."""
    report = _build([_assessment(IMPLEMENTED_STATUS_ID)], None, {'public_id': IMPLEMENTED_STATUS_ID})

    assert not report[MATRIX_BEFORE]
    assert not report[MATRIX_CURRENT]
    assert not report[MATRIX_AFTER]


def test_assessment_missing_calculation_block_is_skipped() -> None:
    """An assessment lacking a risk_calculation block is skipped, not a KeyError crash (None-guard)."""
    incomplete = {'public_id': RISK_ASSESSMENT_ID, 'implementation_status': None}

    report = _build([incomplete], _matrix_with_one_cell(), {'public_id': IMPLEMENTED_STATUS_ID})

    assert _cell(report[MATRIX_BEFORE])['count'] == 0
    assert _cell(report[MATRIX_CURRENT])['count'] == 0
    assert _cell(report[MATRIX_AFTER])['count'] == 0
