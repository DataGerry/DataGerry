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
Helper Methods for calculating the IsmsRiskMatrix
"""
from logging import Logger, getLogger
from typing import Tuple

from cmdb.models.user_model import CmdbUser

from cmdb.manager import RiskClassManager, LikelihoodManager, ImpactManager, RiskMatrixManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
def calculate_risk_matrix(request_user: CmdbUser) -> None:
    """
    Calculates the IsmsRiskMatrix with current values

    Args:
        request_user (CmdbUser): The user requesting this operation
    """
    risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, request_user)
    likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)

    all_risk_classes = risk_class_manager.get_many()
    all_likelihoods = likelihood_manager.get_many('calculation_basis', 1)
    all_impacts = impact_manager.get_many('calculation_basis', 1)

    # Only calculate the matrix if the minimum requirements are met
    if len(all_risk_classes) > 0 and len(all_likelihoods) > 0 and len(all_impacts) > 0:
        current_risk_matrix = risk_matrix_manager.get_item(1, as_dict=True)

        new_risk_matrix_values = __generate_risk_matrix(all_impacts, all_likelihoods)

        new_matrix_with_risk_classes = __transfer_risk_classes(current_risk_matrix['risk_matrix'],
                                                               new_risk_matrix_values)

        current_risk_matrix['risk_matrix'] = new_matrix_with_risk_classes

        risk_matrix_manager.update_item(1, current_risk_matrix)


def remove_deleted_risk_class_from_matrix(deleted_risk_class_id: int, request_user: CmdbUser) -> None:
    """
    Replaces all occurrences of the deleted RiskClass ID in the risk matrix with 0

    Args:
        deleted_risk_class_id (int): The public_id of the deleted RiskClass
        request_user (CmdbUser): The user requesting this operation

    Returns:
        dict: Updated risk matrix with deleted risk class replaced by 0
    """
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)

    current_risk_matrix = risk_matrix_manager.get_item(1, as_dict=True)

    for cell in current_risk_matrix['risk_matrix']:
        if cell["risk_class_id"] == deleted_risk_class_id:
            cell["risk_class_id"] = 0  # Reset to default

    risk_matrix_manager.update_item(1, current_risk_matrix)


def check_risk_classes_set_in_matrix(risk_matrix: dict) -> bool:
    """
    Checks if all cells in the given risk matrix have a risk_class_id set (i.e., greater than 0).

    Args:
        risk_matrix (Dict): The risk matrix dictionary containing a list of cells

    Returns:
        bool: True if all cells have a risk_class_id greater than 0, otherwise False
    """
    return all(cell.get("risk_class_id", 0) > 0 for cell in risk_matrix.get("risk_matrix", []))

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def __generate_risk_matrix(impacts: list[dict], likelihoods: list[dict]) -> list[dict]:
    """
    Generates a risk matrix starting from the bottom-left corner, filling row-wise

    Args:
        impacts (list[dict]): List of impact objects
        likelihoods (list[dict]): List of likelihood objects

    Returns:
        list[dict]: A list of IsmsRiskMatrix cells
    """
    risk_matrix = []

    for row_idx, likelihood in enumerate(likelihoods):  # Loop through likelihoods (rows)
        for col_idx, impact in enumerate(impacts):  # Loop through impacts (columns)
            cell = {
                'row': row_idx,
                'column': col_idx,
                'impact_id': impact['public_id'],
                'impact_value': impact['calculation_basis'],
                'likelihood_id': likelihood['public_id'],
                'likelihood_value': likelihood['calculation_basis'],
                'calculated_value': round(float(impact['calculation_basis']) * float(likelihood['calculation_basis']),
                                          2),
                'risk_class_id': 0
            }
            risk_matrix.append(cell)

    return risk_matrix


def __transfer_risk_classes(old_matrix: list[dict], new_matrix: list[dict]) -> list[dict]:
    """
    Transfers risk_class_id values from the old risk matrix to the new matrix where applicable

    Args:
        old_matrix (list[dict]): The previous risk matrix.
        new_matrix (list[dict]): The newly generated risk matrix.

    Returns:
        list[dict]: Updated new risk matrix with transferred risk_class_id values
    """
    # Create a lookup dictionary from the old matrix using (impact_id, likelihood_id) as key
    old_risk_lookup: dict[Tuple[int, int], int] = {
        (cell["impact_id"], cell["likelihood_id"]): cell["risk_class_id"] for cell in old_matrix
    }

    # Iterate over new matrix and transfer risk_class_id if match is found
    for cell in new_matrix:
        key = (cell["impact_id"], cell["likelihood_id"])
        cell["risk_class_id"] = old_risk_lookup.get(key, 0)  # Default to 0 if not found

    return new_matrix
