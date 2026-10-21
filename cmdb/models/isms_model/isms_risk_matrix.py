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
Implementation of IsmsRiskMatrix in DataGerry - ISMS

The IsmsRiskMatrix is a **singleton** (collection ``isms.riskMatrix``, always public_id 1): one grid of
cells, one cell per (IsmsImpact, IsmsLikelihood) pair, each carrying the two levels' product and the
IsmsRiskClass an admin assigned to it.

**The grid is regenerated from the scales, never edited as a whole.** Every impact and likelihood write
rebuilds it and carries the existing risk-class assignments over by (impact_id, likelihood_id) - see
``isms_risk_matrix_helper`` - and a read repairs a grid that no longer matches the scales. That is why
an absent ``risk_matrix`` key is read as an EMPTY grid rather than None: every reader indexes it as a
list, and a matrix with no scales configured legitimately has no cells.

``RiskMatrixKey`` names the document's keys and drives the shared ``CmdbDAO`` ``from_data`` /
``to_json``, so this model defines neither; ``RiskMatrixCellKey`` names what is inside a cell
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_matrix_constants import RiskMatrixKey

from cmdb.class_schema.isms_model.isms_risk_matrix_schema import get_isms_risk_matrix_schema

from cmdb.errors.models.isms_risk_matrix import (
    IsmsRiskMatrixInitError,
    IsmsRiskMatrixInitFromDataError,
    IsmsRiskMatrixToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                IsmsRiskMatrix - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRiskMatrix(CmdbDAO):
    """
    Implementation of IsmsRiskMatrix.

    The matrix cells are build from bottom left line by line

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskMatrix"

    SCHEMA: dict[str, Any] = get_isms_risk_matrix_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither.
    # REQUIRED_INIT_KEYS stays empty on purpose: besides its public_id the singleton has no key it
    # cannot be created without - the seeded default carries an empty grid and no unit
    KEYS = RiskMatrixKey
    INIT_FROM_DATA_ERROR = IsmsRiskMatrixInitFromDataError
    TO_JSON_ERROR = IsmsRiskMatrixToJsonError

    def __init__(
            self,
            *,
            public_id: int,
            risk_matrix: list[dict[str, Any]] | None = None,
            matrix_unit: str | None = None,
        ) -> None:
        """
        Initialises an IsmsRiskMatrix

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsRiskMatrix - always RISK_MATRIX_PUBLIC_ID in practice
            risk_matrix (list[dict[str, Any]], optional): The grid's cells. An absent value becomes an
                EMPTY LIST rather than None: every reader indexes it as a list, and a matrix whose
                scales are not configured yet has no cells
            matrix_unit (str, optional): The optional unit value of the IsmsRiskMatrix

        Raises:
            IsmsRiskMatrixInitError: When the IsmsRiskMatrix could not be initialised
        """
        try:
            self.risk_matrix = risk_matrix or []
            self.matrix_unit = matrix_unit

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskMatrixInitError(err) from err
