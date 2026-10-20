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
Constants of the IsmsRiskMatrix: its singleton id, its document keys and the keys of one matrix cell

``RiskMatrixKey`` names the document's three top-level keys and drives the shared ``CmdbDAO``
``from_data`` / ``to_json``. It lives in the model layer rather than next to the seeded default, so the
MODEL layer never imports its own document shape from the database-seeding package. The seed data
imports it from here, which is the normal direction: predefined data builds model documents.

``RiskMatrixCellKey`` names the keys *inside* a cell - shared by all four risk-matrix helpers, the
Cerberus schema, the report builder and the report routes' aggregations.

``UNASSIGNED_RISK_CLASS_ID`` is the value a cell carries while no IsmsRiskClass is assigned to it. It
is 0 rather than null because the whole grid is written at once: a freshly generated cell and a cell
whose risk class was deleted are the same state, and the config wizard's "are all cells assigned"
check reads it as "not yet"
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MatrixType',
    'RiskMatrixKey',
    'RiskMatrixCellKey',
    'RiskMatrixReportKey',
    'RISK_MATRIX_PUBLIC_ID',
    'UNASSIGNED_RISK_CLASS_ID',
]

# The IsmsRiskMatrix is a singleton: one document, always at this public_id
RISK_MATRIX_PUBLIC_ID: int = 1

# A cell with no IsmsRiskClass assigned yet
UNASSIGNED_RISK_CLASS_ID: int = 0



class RiskMatrixKey(BaseStrEnum):
    """
    Document keys of an IsmsRiskMatrix

    Three keys and a singleton: the grid itself, and the optional unit an admin labels its values with.
    ``RISK_MATRIX`` is the key every reader indexes as a list, which is why the model coerces an absent
    value to an empty grid rather than leaving it None
    """
    PUBLIC_ID = 'public_id'
    RISK_MATRIX = 'risk_matrix'
    MATRIX_UNIT = 'matrix_unit'


class RiskMatrixCellKey(BaseStrEnum):
    """
    Keys of one cell of the IsmsRiskMatrix grid

    A cell's IDENTITY is the (impact_id, likelihood_id) pair, not its row/column: the grid is ordered
    by ``calculation_basis``, so changing a level's weight moves the cell but must not move the risk
    class an admin assigned to it. ``_transfer_risk_classes`` keys on exactly that pair for that reason
    """
    ROW = 'row'
    COLUMN = 'column'
    IMPACT_ID = 'impact_id'
    IMPACT_VALUE = 'impact_value'
    LIKELIHOOD_ID = 'likelihood_id'
    LIKELIHOOD_VALUE = 'likelihood_value'
    CALCULATED_VALUE = 'calculated_value'
    RISK_CLASS_ID = 'risk_class_id'


class MatrixType(BaseStrEnum):
    """
    The three matrices of the risk-matrix report

    Each is the same grid counted differently: BEFORE_TREATMENT places every risk assessment by its
    before-treatment calculation, AFTER_TREATMENT by its after-treatment one, and CURRENT_STATE by
    whichever applies - the after-treatment values only for an assessment whose implementation status
    is `ImplementationState.IMPLEMENTED`.

    `report_key` is the key that matrix takes in the response, and the Angular `ReportRiskMatrix`
    model mirrors those three, so they are a frontend-visible contract
    """
    BEFORE_TREATMENT = 'before_treatment'
    CURRENT_STATE = 'current_state'
    AFTER_TREATMENT = 'after_treatment'


    @property
    def report_key(self) -> str:
        """
        The key this matrix is reported under

        Returns:
            str: The response key, e.g. 'risk_matrix_before_treatment'
        """
        return f'{RiskMatrixKey.RISK_MATRIX.value}_{self.value}'


class RiskMatrixReportKey(BaseStrEnum):
    """
    The keys of the risk-matrix report that are the report's own

    A reported cell carries the identity keys of `RiskMatrixCellKey` (row, column, risk_class_id) plus
    these two, and CONFIGURED sits beside the three matrices: an ISMS whose risk matrix the config
    wizard has not produced yet answers with three empty grids, and without this flag that is
    indistinguishable from a configured matrix nothing has been assessed against
    """
    COUNT = 'count'
    RISK_ASSESSMENT_IDS = 'risk_assessment_ids'
    CONFIGURED = 'configured'
