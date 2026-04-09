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

        # Prepare the three matrices
        before_treatment_matrix = self._build_matrix(risk_assessments, risk_matrix_data, "before_treatment")
        current_state_matrix = self._build_matrix(risk_assessments, risk_matrix_data, "current_state")
        after_treatment_matrix = self._build_matrix(risk_assessments, risk_matrix_data, "after_treatment")

        # Return the matrices as a dictionary
        return {
            "risk_matrix_before_treatment": before_treatment_matrix,
            "risk_matrix_current_state": current_state_matrix,
            "risk_matrix_after_treatment": after_treatment_matrix
        }


    def _build_matrix(
            self,
            risk_assessments: list[dict],
            risk_matrix_data: dict,
            matrix_type: str) -> list[dict]:
        """
        Builds a single matrix based on the given matrix type

        Args:
            risk_assessments (list[dict]): List of risk assessments to evaluate
            risk_matrix_data (dict): Risk matrix data to map impacts and likelihoods
            matrix_type (str): The type of matrix to build (before_treatment, current_state, after_treatment)

        Returns:
            list: A list of dictionaries, each representing a matrix cell with counts and risk_assessment_ids
        """
        implemented_status_option = self.extendable_options_manager.get_one_by({
                'value': 'Implemented',
                'option_type': OptionType.IMPLEMENTATION_STATE,
                'predefined': True,
        })

        implemented_status_id = implemented_status_option['public_id']

        matrix = []

        for cell_data in risk_matrix_data['risk_matrix']:
            row = cell_data['row']
            col = cell_data['column']
            impact_id = cell_data['impact_id']
            likelihood_id = cell_data['likelihood_id']

            matrix_cell = {
                'row': row,
                'column': col,
                'risk_class_id': cell_data['risk_class_id'],
                'count': 0,
                'risk_assessment_ids': []
            }

            for risk_assessment in risk_assessments:
                if matrix_type == "before_treatment":
                    maximum_impact_id = risk_assessment['risk_calculation_before']['maximum_impact_id']
                    likelihood_id_assessment = risk_assessment['risk_calculation_before']['likelihood_id']
                elif matrix_type == "current_state":
                    if risk_assessment.get('implementation_status') == implemented_status_id:
                        maximum_impact_id = risk_assessment['risk_calculation_after']['maximum_impact_id']
                        likelihood_id_assessment = risk_assessment['risk_calculation_after']['likelihood_id']
                    else:
                        maximum_impact_id = risk_assessment['risk_calculation_before']['maximum_impact_id']
                        likelihood_id_assessment = risk_assessment['risk_calculation_before']['likelihood_id']
                elif matrix_type == "after_treatment":
                    maximum_impact_id = risk_assessment['risk_calculation_after']['maximum_impact_id']
                    likelihood_id_assessment = risk_assessment['risk_calculation_after']['likelihood_id']
                else:
                    continue

                if maximum_impact_id is None or likelihood_id_assessment is None:
                    continue

                if impact_id == maximum_impact_id and likelihood_id == likelihood_id_assessment:
                    matrix_cell['count'] += 1
                    matrix_cell['risk_assessment_ids'].append(risk_assessment['public_id'])

            matrix.append(matrix_cell)

        return matrix
