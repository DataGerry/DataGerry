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
Implementation of IsmsReportBuilder
"""
from logging import Logger, getLogger

from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager

from cmdb.models.extendable_option_model import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               IsmsReportBuilder - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsReportBuilder:
    """
    Builds Reports for ISMS
    """
    def __init__(
            self,
            risk_assessment_manager: RiskAssessmentManager,
            risk_matrix_manager: RiskMatrixManager,
            extendable_options_manager: ExtendableOptionsManager):
        """
        Initializes the IsmsReportBuilder with the necessary managers

        Args:
            risk_assessment_manager (RiskAssessmentManager): RiskAssessmentManager for handling risk assessments
            risk_matrix_manager (RiskMatrixManager): RiskMatrixManager for handling the risk matrix
            extendable_options_manager (ExtendableOptionsManager): ExtendableOptionsManager for handling
                                                                   extendable options
        """
        self.risk_assessment_manager = risk_assessment_manager
        self.risk_matrix_manager = risk_matrix_manager
        self.extendable_options_manager = extendable_options_manager


    def build_risk_matrix_report(self) -> dict:
        """
        Builds the risk matrices report, consisting of:
        - Risk Matrix Before Treatment
        - Risk Matrix Current State
        - Risk Matrix After Treatment

        Returns:
            dict: A dictionary containing the three matrices
        """
        # Get all IsmsRiskAssessments
        risk_assessments = self.risk_assessment_manager.find_all()

        # Get the IsmsRiskMatrix
        risk_matrix_data = self.risk_matrix_manager.get_item(1, as_dict=True)

        # The 'Implemented' status is only used to pick the after-treatment values for the current-state
        # matrix; fetch it once here (guarding a missing option) instead of once per matrix
        implemented_status_option = self.extendable_options_manager.get_one_by({
            'value': 'Implemented',
            'option_type': OptionType.IMPLEMENTATION_STATE,
            'predefined': True,
        })
        implemented_status_id = implemented_status_option['public_id'] if implemented_status_option else None

        # Prepare the three matrices
        before_treatment_matrix = self._build_matrix(
            risk_assessments, risk_matrix_data, "before_treatment", implemented_status_id
        )
        current_state_matrix = self._build_matrix(
            risk_assessments, risk_matrix_data, "current_state", implemented_status_id
        )
        after_treatment_matrix = self._build_matrix(
            risk_assessments, risk_matrix_data, "after_treatment", implemented_status_id
        )

        # Return the matrices as a dictionary
        return {
            "risk_matrix_before_treatment": before_treatment_matrix,
            "risk_matrix_current_state": current_state_matrix,
            "risk_matrix_after_treatment": after_treatment_matrix
        }


    def _build_matrix(
            self,
            risk_assessments: list[dict],
            risk_matrix_data: dict | None,
            matrix_type: str,
            implemented_status_id: int | None) -> list[dict]:
        """
        Builds a single matrix based on the given matrix type

        The assessments are indexed once by their (maximum_impact_id, likelihood_id) for this matrix
        type, so each matrix cell is filled by a single dict lookup instead of scanning every
        assessment per cell.

        Args:
            risk_assessments (list[dict]): List of risk assessments to evaluate
            risk_matrix_data (dict | None): Risk matrix data to map impacts and likelihoods
            matrix_type (str): The type of matrix to build (before_treatment, current_state, after_treatment)
            implemented_status_id (int | None): public_id of the 'Implemented' status, or None if it does
                                                not exist (then no assessment counts as implemented)

        Returns:
            list: A list of dictionaries, each representing a matrix cell with counts and risk_assessment_ids
        """
        # Index the assessments by the (maximum_impact_id, likelihood_id) they map to for this matrix type
        assessments_by_cell: dict[tuple[int, int], list[int]] = {}

        for risk_assessment in risk_assessments:
            cell_key = self._assessment_cell_key(risk_assessment, matrix_type, implemented_status_id)

            if cell_key is not None:
                assessments_by_cell.setdefault(cell_key, []).append(risk_assessment['public_id'])

        matrix = []

        for cell_data in (risk_matrix_data or {}).get('risk_matrix', []):
            ra_ids = assessments_by_cell.get((cell_data['impact_id'], cell_data['likelihood_id']), [])

            matrix.append({
                'row': cell_data['row'],
                'column': cell_data['column'],
                'risk_class_id': cell_data['risk_class_id'],
                'count': len(ra_ids),
                'risk_assessment_ids': ra_ids,
            })

        return matrix


    @staticmethod
    def _assessment_cell_key(
            risk_assessment: dict,
            matrix_type: str,
            implemented_status_id: int | None) -> tuple[int, int] | None:
        """
        Determines the (maximum_impact_id, likelihood_id) cell an assessment maps to for a matrix type.

        For the current-state matrix an assessment uses its after-treatment values only when its
        implementation_status equals the 'Implemented' status, otherwise its before-treatment values.

        Args:
            risk_assessment (dict): The assessment to place
            matrix_type (str): before_treatment / current_state / after_treatment
            implemented_status_id (int | None): public_id of the 'Implemented' status, or None

        Returns:
            tuple[int, int] | None: The cell key, or None when the assessment has no usable values
        """
        if matrix_type == "before_treatment":
            calculation = risk_assessment.get('risk_calculation_before')
        elif matrix_type == "after_treatment":
            calculation = risk_assessment.get('risk_calculation_after')
        elif matrix_type == "current_state":
            is_implemented = (implemented_status_id is not None
                              and risk_assessment.get('implementation_status') == implemented_status_id)
            calculation = (risk_assessment.get('risk_calculation_after') if is_implemented
                           else risk_assessment.get('risk_calculation_before'))
        else:
            return None

        if not calculation:
            return None

        maximum_impact_id = calculation.get('maximum_impact_id')
        likelihood_id = calculation.get('likelihood_id')

        if maximum_impact_id is None or likelihood_id is None:
            return None

        return (maximum_impact_id, likelihood_id)
