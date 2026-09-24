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
Helper methods for calculating the IsmsRiskMatrix

The risk matrix is the grid the whole ISMS risk evaluation reads: one cell per (IsmsImpact,
IsmsLikelihood) pair, carrying their product and the IsmsRiskClass an admin assigned to it. Four
properties of it are worth knowing before changing anything here:

**It is a singleton**, always stored at ``RISK_MATRIX_PUBLIC_ID`` (1), seeded empty at setup.
``ensure_default_risk_matrix`` recreates that default if the document is missing, so no caller has to
handle its absence.

**A cell's identity is its (impact_id, likelihood_id) pair, not its position.** The grid is ordered by
``calculation_basis``, so changing a level's weight moves cells around; keying the transfer on the
public_ids is what keeps an admin's risk-class assignments attached to the right pair across that
reordering.

**The grid is regenerated from scratch on every scale change and is always consistent with the current
scales.** ``calculate_risk_matrix`` is called by all six impact and likelihood write routes (insert,
update, delete of either). It deliberately has NO minimum-configuration guard:

  - it must not require at least one IsmsRiskClass, which is not an input to the calculation at all -
    and since no risk-class route recalculates, configuring risk classes *last* left the matrix
    permanently empty while the config wizard reported that step complete
  - it must not require a non-empty scale, which would leave a **stale** grid behind when one is emptied:
    cells naming a deleted level. Those cells can never match again - a re-added level gets a new
    public_id - so keeping them preserved nothing and hid the real state

With no guard, an empty scale produces an empty grid (the cross-product of nothing), which is what the
wizard's own scale-minimum checks already report as unfinished.

**A risk class is assigned per cell, and 0 means "not yet"** - see ``UNASSIGNED_RISK_CLASS_ID``. That
is what ``check_risk_classes_set_in_matrix`` reads, and why an empty grid is NOT "all cells assigned"
"""
from typing import Any

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model.isms_risk_matrix_constants import (
    RISK_MATRIX_PUBLIC_ID,
    RiskMatrixKey,
    UNASSIGNED_RISK_CLASS_ID,
    RiskMatrixCellKey,
)

from cmdb.manager import LikelihoodManager, ImpactManager, RiskMatrixManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.database.predefined_data.isms_data import get_default_risk_matrix

# -------------------------------------------------------------------------------------------------------------------- #

# The scales are read in ascending weight order, because the grid is built from its bottom-left corner
SCALE_SORT_FIELD: str = 'calculation_basis'
SCALE_SORT_ASCENDING: int = 1

# -------------------------------------------------------------------------------------------------------------------- #
def ensure_default_risk_matrix(risk_matrix_manager: RiskMatrixManager) -> dict[str, Any]:
    """
    Returns the singleton IsmsRiskMatrix, creating the empty default if it is missing

    The RiskMatrix is a singleton seeded once at setup; if its document is absent (e.g. it was
    deleted, or the database was created before the matrix was seeded) this recreates the default
    so callers never have to handle a missing matrix. The default carries the singleton public_id, an
    empty cell list and no unit.

    Never returns None: if the document cannot be read back after being inserted, the default that was
    just written is returned, because the contract every caller relies on is that it can index the
    result immediately

    Args:
        risk_matrix_manager (RiskMatrixManager): Manager used to read and, if needed, create the matrix

    Returns:
        dict[str, Any]: The current (or freshly created) IsmsRiskMatrix document
    """
    current_risk_matrix: dict[str, Any] | None = risk_matrix_manager.get_item(RISK_MATRIX_PUBLIC_ID,
                                                                             as_dict=True)

    if not current_risk_matrix:
        default_risk_matrix: dict[str, Any] = get_default_risk_matrix()
        risk_matrix_manager.insert_item(default_risk_matrix)
        current_risk_matrix = risk_matrix_manager.get_item(RISK_MATRIX_PUBLIC_ID, as_dict=True)

        # The read back is what picks up whatever the insert stored; the default is the fallback so
        # this function keeps its promise of returning an indexable document
        if not current_risk_matrix:
            return default_risk_matrix

    return current_risk_matrix


def calculate_risk_matrix(request_user: CmdbUser) -> dict[str, Any]:
    """
    Regenerates the IsmsRiskMatrix from the current impact and likelihood scales

    Called by every impact and likelihood write route. The grid is rebuilt from scratch and the
    previous cells' risk-class assignments are carried over by (impact_id, likelihood_id), so a scale
    change keeps every assignment whose pair still exists and drops the rest. An empty scale yields an
    empty grid - see the module docstring for why there is no minimum-configuration guard

    Args:
        request_user (CmdbUser): The user requesting this operation

    Returns:
        dict[str, Any]: The IsmsRiskMatrix as it was just written, so a caller needing the fresh grid
                        does not have to read it back
    """
    likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)

    all_likelihoods = likelihood_manager.get_many(SCALE_SORT_FIELD, SCALE_SORT_ASCENDING)
    all_impacts = impact_manager.get_many(SCALE_SORT_FIELD, SCALE_SORT_ASCENDING)

    current_risk_matrix = ensure_default_risk_matrix(risk_matrix_manager)

    new_risk_matrix_values = _generate_risk_matrix(all_impacts, all_likelihoods)

    current_risk_matrix[RiskMatrixKey.RISK_MATRIX] = _transfer_risk_classes(
        current_risk_matrix[RiskMatrixKey.RISK_MATRIX],
        new_risk_matrix_values,
    )

    risk_matrix_manager.update_item(RISK_MATRIX_PUBLIC_ID, current_risk_matrix)

    return current_risk_matrix


def ensure_risk_matrix_matches_scales(request_user: CmdbUser,
                                      stored_risk_matrix: dict[str, Any]) -> dict[str, Any]:
    """
    Rebuilds the stored grid when its shape no longer matches the current scales

    **Why a read repairs anything at all.** The grid is only ever written by the six impact and
    likelihood write routes, so a database whose stored grid is wrong stays wrong forever - no read,
    no restart and no later scale configuration corrects it. That is not hypothetical: every database
    configured under the old minimum-configuration guard (scales created before the first
    IsmsRiskClass) holds an empty grid that the guard's removal did not repair, and a restored dump or
    a directly seeded database can arrive in the same state. Recomputing on read is what makes the
    grid self-correcting.

    **The check is two counts, not two scale loads.** The healthy path - every read of a correctly
    built matrix - costs one `count_documents` per scale and nothing else; the full scales are only
    read when the shape actually disagrees. A grid whose CELL COUNT matches the cross-product is
    treated as current: the pairs inside it can only drift through a scale write, and every scale
    write rebuilds the grid.

    Rebuilding preserves the admin's work - `_transfer_risk_classes` carries every assignment whose
    (impact_id, likelihood_id) pair still exists - so healing can never lose a risk-class assignment

    Args:
        request_user (CmdbUser): The user requesting this operation
        stored_risk_matrix (dict[str, Any]): The IsmsRiskMatrix as currently stored

    Returns:
        dict[str, Any]: The stored matrix when its shape is current, otherwise the rebuilt one
    """
    impact_manager: ImpactManager = ManagerProvider.get_manager(ManagerType.IMPACT, request_user)
    likelihood_manager: LikelihoodManager = ManagerProvider.get_manager(ManagerType.LIKELIHOOD, request_user)

    expected_cell_count: int = impact_manager.count_documents() * likelihood_manager.count_documents()
    stored_cell_count: int = len(stored_risk_matrix.get(RiskMatrixKey.RISK_MATRIX) or [])

    if stored_cell_count == expected_cell_count:
        return stored_risk_matrix

    return calculate_risk_matrix(request_user)


def remove_deleted_risk_class_from_matrix(deleted_risk_class_id: int, request_user: CmdbUser) -> None:
    """
    Resets every cell that referenced a deleted IsmsRiskClass to "not yet assigned"

    The grid itself is untouched - only the assignment is dropped, because the cell's impact and
    likelihood still exist

    Args:
        deleted_risk_class_id (int): The public_id of the deleted RiskClass
        request_user (CmdbUser): The user requesting this operation
    """
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)

    current_risk_matrix = ensure_default_risk_matrix(risk_matrix_manager)

    for cell in current_risk_matrix[RiskMatrixKey.RISK_MATRIX]:
        if cell.get(RiskMatrixCellKey.RISK_CLASS_ID.value) == deleted_risk_class_id:
            cell[RiskMatrixCellKey.RISK_CLASS_ID.value] = UNASSIGNED_RISK_CLASS_ID

    risk_matrix_manager.update_item(RISK_MATRIX_PUBLIC_ID, current_risk_matrix)


def check_risk_classes_set_in_matrix(risk_matrix: dict) -> bool:
    """
    Checks whether every cell of the given risk matrix has an IsmsRiskClass assigned

    An EMPTY grid is not "all cells assigned": the config wizard reads this to decide whether the risk
    matrix step is finished, and a matrix with no cells is one nothing can be evaluated against. That
    is the one thing this cannot answer with ``all()`` alone, which is vacuously true for an empty list

    Args:
        risk_matrix (dict): The IsmsRiskMatrix document, carrying its list of cells

    Returns:
        bool: True if the grid has cells and each one names a risk class, otherwise False
    """
    cells: list[dict[str, Any]] = risk_matrix.get(RiskMatrixKey.RISK_MATRIX, [])

    if not cells:
        return False

    return all(
        cell.get(RiskMatrixCellKey.RISK_CLASS_ID.value, UNASSIGNED_RISK_CLASS_ID) > UNASSIGNED_RISK_CLASS_ID
        for cell in cells
    )

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def _generate_risk_matrix(impacts: list[dict[str, Any]], likelihoods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Generates a risk matrix starting from the bottom-left corner, filling row-wise

    Every cell starts unassigned; ``_transfer_risk_classes`` is what carries the previous grid's
    assignments over. An empty scale on either axis yields an empty grid

    Args:
        impacts (list[dict[str, Any]]): The impact scale, ascending by calculation_basis (columns)
        likelihoods (list[dict[str, Any]]): The likelihood scale, ascending by basis (rows)

    Returns:
        list[dict[str, Any]]: A list of IsmsRiskMatrix cells
    """
    risk_matrix = []

    for row_idx, likelihood in enumerate(likelihoods):  # Loop through likelihoods (rows)
        for col_idx, impact in enumerate(impacts):  # Loop through impacts (columns)
            impact_value = impact[SCALE_SORT_FIELD]
            likelihood_value = likelihood[SCALE_SORT_FIELD]

            risk_matrix.append({
                RiskMatrixCellKey.ROW.value: row_idx,
                RiskMatrixCellKey.COLUMN.value: col_idx,
                RiskMatrixCellKey.IMPACT_ID.value: impact[RiskMatrixKey.PUBLIC_ID],
                RiskMatrixCellKey.IMPACT_VALUE.value: impact_value,
                RiskMatrixCellKey.LIKELIHOOD_ID.value: likelihood[RiskMatrixKey.PUBLIC_ID],
                RiskMatrixCellKey.LIKELIHOOD_VALUE.value: likelihood_value,
                RiskMatrixCellKey.CALCULATED_VALUE.value: round(float(impact_value) * float(likelihood_value), 2),
                RiskMatrixCellKey.RISK_CLASS_ID.value: UNASSIGNED_RISK_CLASS_ID,
            })

    return risk_matrix


def _transfer_risk_classes(old_matrix: list[dict[str, Any]],
                           new_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Transfers risk_class_id values from the old risk matrix to the new matrix where applicable

    Keyed on the (impact_id, likelihood_id) pair rather than on row/column, so an assignment survives
    a weight change that reorders the grid and is dropped only when its pair no longer exists. Reads
    the old cells defensively: a hand-edited or pre-migration cell missing a key must not take a scale
    change down with a KeyError

    Args:
        old_matrix (list[dict[str, Any]]): The previous risk matrix
        new_matrix (list[dict[str, Any]]): The newly generated risk matrix

    Returns:
        list[dict[str, Any]]: Updated new risk matrix with transferred risk_class_id values
    """
    # Create a lookup dictionary from the old matrix using (impact_id, likelihood_id) as key
    old_risk_lookup: dict[tuple[Any, Any], int] = {
        (cell.get(RiskMatrixCellKey.IMPACT_ID.value), cell.get(RiskMatrixCellKey.LIKELIHOOD_ID.value)):
            cell.get(RiskMatrixCellKey.RISK_CLASS_ID.value, UNASSIGNED_RISK_CLASS_ID)
        for cell in old_matrix
    }

    # Iterate over new matrix and transfer risk_class_id if match is found
    for cell in new_matrix:
        key = (cell[RiskMatrixCellKey.IMPACT_ID.value], cell[RiskMatrixCellKey.LIKELIHOOD_ID.value])
        cell[RiskMatrixCellKey.RISK_CLASS_ID.value] = old_risk_lookup.get(key, UNASSIGNED_RISK_CLASS_ID)

    return new_matrix
