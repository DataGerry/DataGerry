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
Unit tests for the pure IsmsRiskMatrix helpers

Covers ``ensure_default_risk_matrix`` (singleton self-heal, isolated from Mongo with a stub
manager), the pure grid builders ``_generate_risk_matrix`` / ``_transfer_risk_classes``, and
``check_risk_classes_set_in_matrix`` - none of which touch the database.
"""
from typing import Any, Optional

from cmdb.models.isms_model.isms_helper import ensure_default_risk_matrix, check_risk_classes_set_in_matrix
from cmdb.models.isms_model.isms_helper.isms_risk_matrix_helper import (
    _generate_risk_matrix,
    _transfer_risk_classes,
)
from cmdb.database.predefined_data.predefined_data_constants import RiskMatrixKey
# -------------------------------------------------------------------------------------------------------------------- #

EXISTING_MATRIX_ID: int = 1

CALCULATION_BASIS_KEY: str = 'calculation_basis'
CELL_IMPACT_ID_KEY: str = 'impact_id'
CELL_LIKELIHOOD_ID_KEY: str = 'likelihood_id'
CELL_CALCULATED_VALUE_KEY: str = 'calculated_value'
CELL_RISK_CLASS_ID_KEY: str = 'risk_class_id'


def _scale_entry(public_id: int, basis: float) -> dict[str, Any]:
    """Builds an impact/likelihood entry as consumed by _generate_risk_matrix."""
    return {RiskMatrixKey.PUBLIC_ID: public_id, CALCULATION_BASIS_KEY: basis}


class _StubRiskMatrixManager:
    """
    Stub RiskMatrixManager recording inserts and serving a configurable get_item result

    get_item returns ``initial`` until an insert happens, then serves the inserted document, so a
    single instance models both the "already present" and "missing then recreated" flows
    """

    def __init__(self, initial: Optional[dict[str, Any]]) -> None:
        self._current: Optional[dict[str, Any]] = initial
        self.inserted: list[dict[str, Any]] = []

    def get_item(self, public_id: int, as_dict: bool = False) -> Optional[dict[str, Any]]:
        """Returns the current document for public_id 1, else None"""
        return self._current if public_id == EXISTING_MATRIX_ID else None

    def insert_item(self, document: dict[str, Any]) -> int:
        """Records the insert and makes the document the new current matrix"""
        self.inserted.append(document)
        self._current = document

        return document[RiskMatrixKey.PUBLIC_ID]


def test_returns_existing_matrix_without_inserting() -> None:
    """When the singleton already exists it is returned as-is and no insert is performed"""
    existing: dict[str, Any] = {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: [{'risk_class_id': 2}],
        RiskMatrixKey.MATRIX_UNIT: 'EUR',
    }
    manager = _StubRiskMatrixManager(existing)

    result = ensure_default_risk_matrix(manager)

    assert result is existing
    assert manager.inserted == []


def test_creates_default_matrix_when_missing() -> None:
    """When the singleton is missing the empty default is inserted at public_id 1 and returned"""
    manager = _StubRiskMatrixManager(None)

    result = ensure_default_risk_matrix(manager)

    assert len(manager.inserted) == 1
    assert result[RiskMatrixKey.PUBLIC_ID] == EXISTING_MATRIX_ID
    assert result[RiskMatrixKey.RISK_MATRIX] == []
    assert result[RiskMatrixKey.MATRIX_UNIT] is None


# ----------------------------------------------- _generate_risk_matrix ---------------------------------------------- #

def test_generate_builds_one_cell_per_impact_likelihood_pair() -> None:
    """The grid has impacts x likelihoods cells, each with calculated_value = impact x likelihood."""
    impacts = [_scale_entry(10, 2.0), _scale_entry(11, 3.0)]
    likelihoods = [_scale_entry(20, 1.0), _scale_entry(21, 4.0)]

    matrix = _generate_risk_matrix(impacts, likelihoods)

    assert len(matrix) == 4
    assert all(cell[CELL_RISK_CLASS_ID_KEY] == 0 for cell in matrix)
    assert {cell[CELL_CALCULATED_VALUE_KEY] for cell in matrix} == {2.0, 3.0, 8.0, 12.0}


def test_generate_returns_empty_when_no_impacts() -> None:
    """With no impacts there are no cells."""
    assert _generate_risk_matrix([], [_scale_entry(20, 1.0)]) == []


def test_generate_returns_empty_when_no_likelihoods() -> None:
    """With no likelihoods there are no cells."""
    assert _generate_risk_matrix([_scale_entry(10, 2.0)], []) == []


# ---------------------------------------------- _transfer_risk_classes ---------------------------------------------- #

def test_transfer_carries_matching_cell_and_defaults_others() -> None:
    """A cell keeps the old risk_class_id when (impact_id, likelihood_id) matches, else defaults to 0."""
    old_matrix = [{CELL_IMPACT_ID_KEY: 10, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 5}]
    new_matrix = [
        {CELL_IMPACT_ID_KEY: 10, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 0},
        {CELL_IMPACT_ID_KEY: 11, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 0},
    ]

    result = _transfer_risk_classes(old_matrix, new_matrix)

    assert result[0][CELL_RISK_CLASS_ID_KEY] == 5
    assert result[1][CELL_RISK_CLASS_ID_KEY] == 0


# ------------------------------------------ check_risk_classes_set_in_matrix ---------------------------------------- #

def test_check_true_when_all_cells_have_a_class() -> None:
    """All cells with risk_class_id > 0 yields True."""
    matrix = {RiskMatrixKey.RISK_MATRIX: [{CELL_RISK_CLASS_ID_KEY: 1}, {CELL_RISK_CLASS_ID_KEY: 2}]}

    assert check_risk_classes_set_in_matrix(matrix) is True


def test_check_false_when_a_cell_is_unset() -> None:
    """A single cell with risk_class_id 0 yields False."""
    matrix = {RiskMatrixKey.RISK_MATRIX: [{CELL_RISK_CLASS_ID_KEY: 1}, {CELL_RISK_CLASS_ID_KEY: 0}]}

    assert check_risk_classes_set_in_matrix(matrix) is False


def test_check_true_for_empty_matrix() -> None:
    """An empty matrix vacuously yields True."""
    assert check_risk_classes_set_in_matrix({RiskMatrixKey.RISK_MATRIX: []}) is True
