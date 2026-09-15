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
The risk-matrix report of ISMS: three views of one grid

The report answers `GET /rest/isms/reports/risk_matrix` with the IsmsRiskMatrix grid counted three
times - by every risk assessment's before-treatment calculation, by its after-treatment one, and by
whichever applies to its current state. Each reported cell carries the identity keys of
`RiskMatrixCellKey` plus `count` and `risk_assessment_ids`; the Angular `ReportRiskMatrix` model
mirrors the three matrix keys and the cell shape, so both are a frontend contract.

Four things decide the numbers, and each of them used to be able to go wrong silently:

* **the current-state rule.** An assessment contributes its after-treatment values only when its
  ``implementation_status`` is the predefined IMPLEMENTED option, and its before-treatment values
  otherwise. That option is resolved by value (`ImplementationState.IMPLEMENTED`) - if it is missing,
  NOTHING counts as implemented and the current-state matrix equals the before-treatment one, which
  is why that case is logged rather than passed over
* **an unconfigured matrix is a state, not an answer.** The IsmsRiskMatrix is a singleton the ISMS
  config wizard produces; until it exists the report says so with ``configured: false`` beside three
  empty grids, instead of returning three empty grids that look like "nothing assessed yet"
* **a drifted cell costs its own cell only.** A grid cell missing one of its keys is reported and
  skipped; it used to raise a KeyError that the route turned into a 500 for the whole report
* **the reads are bounded.** The assessments are read ONCE, projected to the four keys the report
  uses, and indexed for all three matrices in a single pass - so the report costs two queries
  whatever the number of assessments, and does not carry their impacts, dates and references along

This is a service, not a model: it takes three managers and orchestrates reads. It lived in
`cmdb/models/isms_model/` until 2026-09-09, which made importing the ISMS model package pull in three
managers - the framework layer sits above the managers, so this is where that dependency belongs
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager

from cmdb.models.extendable_option_model import ExtendableOptionKey, OptionType
from cmdb.models.isms_model.implementation_state_enum import ImplementationState
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_matrix_constants import (
    MatrixType,
    RiskMatrixCellKey,
    RiskMatrixReportKey,
    RiskMatrixKey,
    RISK_MATRIX_PUBLIC_ID,
)
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey

from cmdb.errors.framework_isms import RiskMatrixReportError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ASSESSMENT_PROJECTION',
    'RiskMatrixReportBuilder',
]

LOGGER: Logger = getLogger(__name__)

# The only keys of a risk assessment the report reads. MongoDB returns '_id' unless it is excluded
ASSESSMENT_PROJECTION: dict[str, int] = {
    RiskAssessmentKey.PUBLIC_ID.value: 1,
    RiskAssessmentKey.IMPLEMENTATION_STATUS.value: 1,
    RiskCalculationKey.BEFORE.value: 1,
    RiskCalculationKey.AFTER.value: 1,
    '_id': 0,
}

# The keys of a grid cell that are copied into its reported cell
REPORTED_CELL_KEYS: tuple[RiskMatrixCellKey, ...] = (
    RiskMatrixCellKey.ROW,
    RiskMatrixCellKey.COLUMN,
    RiskMatrixCellKey.RISK_CLASS_ID,
)

# The cell keys the report needs to place an assessment - a cell without them cannot be filled
CELL_IDENTITY_KEYS: tuple[RiskMatrixCellKey, ...] = (
    RiskMatrixCellKey.IMPACT_ID,
    RiskMatrixCellKey.LIKELIHOOD_ID,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            RiskMatrixReportBuilder - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskMatrixReportBuilder:
    """
    Builds the ISMS risk-matrix report

    The other ISMS reports (statement of applicability, risk treatment plan, ...) are assembled in
    `isms_report_helper.py` at the route layer; this one has enough rules of its own to live apart
    """

    def __init__(
            self,
            risk_assessment_manager: RiskAssessmentManager,
            risk_matrix_manager: RiskMatrixManager,
            extendable_options_manager: ExtendableOptionsManager) -> None:
        """
        Initialises the RiskMatrixReportBuilder with the managers it reads through

        Args:
            risk_assessment_manager (RiskAssessmentManager): db interface for IsmsRiskAssessments
            risk_matrix_manager (RiskMatrixManager): db interface for the IsmsRiskMatrix singleton
            extendable_options_manager (ExtendableOptionsManager): db interface for
                CmdbExtendableOptions, used to resolve the IMPLEMENTED status
        """
        self.risk_assessment_manager: RiskAssessmentManager = risk_assessment_manager
        self.risk_matrix_manager: RiskMatrixManager = risk_matrix_manager
        self.extendable_options_manager: ExtendableOptionsManager = extendable_options_manager


    def build_risk_matrix_report(self) -> dict[str, Any]:
        """
        Builds the risk-matrix report: the grid counted before treatment, currently and after treatment

        Two queries and one pass over the assessments, whatever their number

        Raises:
            RiskMatrixReportError: When one of the reads behind the report fails

        Returns:
            dict[str, Any]: `configured` plus one entry per `MatrixType`, keyed by its `report_key`
                            and holding the reported cells of that matrix
        """
        try:
            assessments: list[dict[str, Any]] = self.risk_assessment_manager.find_all(
                projection=ASSESSMENT_PROJECTION,
            )
            risk_matrix: dict[str, Any] | None = self.risk_matrix_manager.get_item(
                RISK_MATRIX_PUBLIC_ID, as_dict=True,
            )
        except Exception as err:
            LOGGER.error("[build_risk_matrix_report] Exception: %s. Type: %s", err, type(err))

            raise RiskMatrixReportError(err) from err

        grid: list[dict[str, Any]] = (risk_matrix or {}).get(RiskMatrixKey.RISK_MATRIX.value) or []

        if not grid:
            # The config wizard has not produced the matrix yet. Reporting it is what keeps this apart
            # from a configured matrix that nothing has been assessed against
            LOGGER.warning("[build_risk_matrix_report] The IsmsRiskMatrix is not configured yet")

        assessments_by_cell: dict[MatrixType, dict[tuple[int, int], list[int]]] = self._index_assessments(
            assessments,
        )

        report: dict[str, Any] = {RiskMatrixReportKey.CONFIGURED.value: bool(grid)}

        for matrix_type in MatrixType:
            report[matrix_type.report_key] = self._build_matrix(grid, assessments_by_cell[matrix_type])

        return report


    def _index_assessments(
            self,
            assessments: list[dict[str, Any]]) -> dict[MatrixType, dict[tuple[int, int], list[int]]]:
        """
        Indexes every assessment by the cell it occupies, for all three matrices in one pass

        Each matrix is a lookup from the ``(maximum_impact_id, likelihood_id)`` pair to the ids of the
        assessments in that cell, so filling a cell is a dict lookup rather than a scan - and the
        assessments are walked once rather than once per matrix

        Args:
            assessments (list[dict[str, Any]]): The projected IsmsRiskAssessment documents

        Returns:
            dict[MatrixType, dict[tuple[int, int], list[int]]]: The three indexes
        """
        implemented_status_id: int | None = self._implemented_status_id()
        indexes: dict[MatrixType, dict[tuple[int, int], list[int]]] = {
            matrix_type: {} for matrix_type in MatrixType
        }

        for assessment in assessments:
            public_id: Any = assessment.get(RiskAssessmentKey.PUBLIC_ID.value)

            if not isinstance(public_id, int):
                LOGGER.warning("[_index_assessments] Skipping an IsmsRiskAssessment without a public_id")
                continue

            for matrix_type in MatrixType:
                cell_key: tuple[int, int] | None = self._assessment_cell_key(
                    assessment, matrix_type, implemented_status_id,
                )

                if cell_key is not None:
                    indexes[matrix_type].setdefault(cell_key, []).append(public_id)

        return indexes


    def _implemented_status_id(self) -> int | None:
        """
        Resolves the public_id of the predefined IMPLEMENTED implementation-status option

        Only the current-state matrix needs it, and it is read once for the whole report. A missing
        option is reported, because it silently turns the current-state matrix into a copy of the
        before-treatment one: with no id to compare against, no assessment counts as implemented

        Raises:
            RiskMatrixReportError: When the option lookup fails

        Returns:
            int | None: The option's public_id, or None when the option does not exist
        """
        try:
            implemented_option: dict[str, Any] | None = self.extendable_options_manager.get_one_by({
                ExtendableOptionKey.VALUE.value: ImplementationState.IMPLEMENTED.value,
                ExtendableOptionKey.OPTION_TYPE.value: OptionType.IMPLEMENTATION_STATE.value,
                ExtendableOptionKey.PREDEFINED.value: True,
            })
        except Exception as err:
            LOGGER.error("[_implemented_status_id] Exception: %s. Type: %s", err, type(err))

            raise RiskMatrixReportError(err) from err

        status_id: Any = (implemented_option or {}).get(ExtendableOptionKey.PUBLIC_ID.value)

        if not isinstance(status_id, int):
            LOGGER.warning(
                "[_implemented_status_id] The predefined '%s' option is missing - the current-state "
                "matrix will report every IsmsRiskAssessment with its before-treatment values",
                ImplementationState.IMPLEMENTED.value,
            )

            return None

        return status_id


    @staticmethod
    def _build_matrix(
            grid: list[dict[str, Any]],
            assessments_by_cell: dict[tuple[int, int], list[int]]) -> list[dict[str, Any]]:
        """
        Reports one matrix: every grid cell with the assessments that fall into it

        A cell that does not carry its identity pair cannot be filled and is skipped with a warning -
        reading it unguarded used to fail the whole report with a 500

        Args:
            grid (list[dict[str, Any]]): The IsmsRiskMatrix grid cells
            assessments_by_cell (dict[tuple[int, int], list[int]]): assessment ids by cell identity

        Returns:
            list[dict[str, Any]]: The reported cells, in grid order
        """
        matrix: list[dict[str, Any]] = []

        for cell in grid:
            identity: tuple[Any, ...] = tuple(cell.get(key.value) for key in CELL_IDENTITY_KEYS)

            if any(value is None for value in identity):
                LOGGER.warning("[_build_matrix] Skipping a risk-matrix cell without its impact/likelihood: %r",
                               cell)
                continue

            assessment_ids: list[int] = assessments_by_cell.get(identity, [])

            reported_cell: dict[str, Any] = {key.value: cell.get(key.value) for key in REPORTED_CELL_KEYS}
            reported_cell[RiskMatrixReportKey.COUNT.value] = len(assessment_ids)
            reported_cell[RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value] = assessment_ids

            matrix.append(reported_cell)

        return matrix


    @staticmethod
    def _assessment_cell_key(
            assessment: dict[str, Any],
            matrix_type: MatrixType,
            implemented_status_id: int | None) -> tuple[int, int] | None:
        """
        Determines the cell an assessment occupies in one matrix

        The current-state matrix uses the assessment's after-treatment values only when its
        ``implementation_status`` is the IMPLEMENTED option, and its before-treatment values otherwise

        Args:
            assessment (dict[str, Any]): The assessment to place
            matrix_type (MatrixType): The matrix being built
            implemented_status_id (int | None): public_id of the IMPLEMENTED status, or None when the
                option does not exist - then no assessment counts as implemented

        Returns:
            tuple[int, int] | None: The `(maximum_impact_id, likelihood_id)` cell, or None when the
                                    assessment carries no usable calculation for this matrix
        """
        if matrix_type is MatrixType.CURRENT_STATE:
            is_implemented: bool = (
                implemented_status_id is not None
                and assessment.get(RiskAssessmentKey.IMPLEMENTATION_STATUS.value) == implemented_status_id
            )
            calculation_key: str = (
                RiskCalculationKey.AFTER.value if is_implemented else RiskCalculationKey.BEFORE.value
            )
        elif matrix_type is MatrixType.AFTER_TREATMENT:
            calculation_key = RiskCalculationKey.AFTER.value
        else:
            calculation_key = RiskCalculationKey.BEFORE.value

        calculation: Any = assessment.get(calculation_key)

        if not isinstance(calculation, dict):
            return None

        maximum_impact_id: Any = calculation.get(RiskCalculationKey.MAXIMUM_IMPACT_ID.value)
        likelihood_id: Any = calculation.get(RiskCalculationKey.LIKELIHOOD_ID.value)

        if maximum_impact_id is None or likelihood_id is None:
            return None

        return (maximum_impact_id, likelihood_id)
