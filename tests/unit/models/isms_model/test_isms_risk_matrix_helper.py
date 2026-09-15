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
Unit tests for the IsmsRiskMatrix helpers

Isolated from Mongo with stub managers, so the whole module is unit-testable: the singleton self-heal
(``ensure_default_risk_matrix``), the pure grid builders (``_generate_risk_matrix`` /
``_transfer_risk_classes``), the wizard's completeness check (``check_risk_classes_set_in_matrix``) and
- new on 2026-09-07 - the **assembly** itself, ``calculate_risk_matrix``, which was the only real logic
gap left in ``cmdb/models/isms_model/``.

Three behaviours pinned here changed that day, and each was a reachable defect:

  - **the matrix is regenerated with no minimum-configuration guard.** Requiring at least one
    IsmsRiskClass - which is not an input to the calculation - meant that configuring risk classes
    *last* left the grid permanently empty, because no risk-class route recalculates
  - **an empty grid is not "all cells assigned".** ``all([])`` is vacuously true, so the config wizard
    reported the risk-matrix step complete for a grid with zero cells
  - **an emptied scale produces an empty grid, not a stale one.** The old guard left cells naming a
    deleted level behind, and those can never match again - a re-added level gets a new public_id

The assignment transfer keys on the (impact_id, likelihood_id) pair, which is what makes an admin's
risk-class choices survive a ``calculation_basis`` change that reorders the grid; that is asserted
directly rather than through the routes.
"""
from typing import Any, Optional

import pytest

from cmdb.models.isms_model.isms_helper import (
    ensure_default_risk_matrix,
    ensure_risk_matrix_matches_scales,
    check_risk_classes_set_in_matrix,
)
from cmdb.models.isms_model.isms_helper.isms_risk_matrix_helper import (
    SCALE_SORT_ASCENDING,
    SCALE_SORT_FIELD,
    _generate_risk_matrix,
    _transfer_risk_classes,
    calculate_risk_matrix,
    remove_deleted_risk_class_from_matrix,
)
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.isms_model.isms_risk_matrix_constants import RiskMatrixKey
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


class _AmnesiacRiskMatrixManager(_StubRiskMatrixManager):
    """
    A manager whose insert does not become readable

    Models the one case the second read cannot recover from - a write that did not land, or a read
    against a replica that has not caught up - so the fallback is exercised rather than assumed.
    """

    def insert_item(self, document: dict[str, Any]) -> int:
        """Records the insert but leaves get_item answering None"""
        self.inserted.append(document)

        return document[RiskMatrixKey.PUBLIC_ID]


def test_returns_the_written_default_when_the_read_back_fails() -> None:
    """
    ensure_default_risk_matrix never returns None

    Every caller indexes the result immediately (``result['risk_matrix']``), so returning None turned
    an unreadable insert into a TypeError and a 500 rather than an empty matrix.
    """
    manager = _AmnesiacRiskMatrixManager(None)

    result = ensure_default_risk_matrix(manager)

    assert result is not None
    assert result[RiskMatrixKey.PUBLIC_ID] == RISK_MATRIX_PUBLIC_ID
    assert result[RiskMatrixKey.RISK_MATRIX] == []


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


def test_check_false_for_empty_matrix() -> None:
    """
    An empty grid is not "all cells assigned"

    ``all([])`` is vacuously true, which made the config wizard report the risk-matrix step complete
    for a matrix with no cells - reachable whenever the grid had never been generated.
    """
    assert check_risk_classes_set_in_matrix({RiskMatrixKey.RISK_MATRIX: []}) is False


def test_check_false_for_a_document_without_a_grid() -> None:
    """A document missing the key entirely is the same answer as an empty one."""
    assert check_risk_classes_set_in_matrix({}) is False


def test_check_reads_the_cell_key_defensively() -> None:
    """A cell missing risk_class_id counts as unassigned rather than raising."""
    assert check_risk_classes_set_in_matrix({RiskMatrixKey.RISK_MATRIX: [{}]}) is False

# ------------------------------------------------ calculate_risk_matrix --------------------------------------------- #

class _StubScaleManager:
    """Stub Impact/Likelihood manager serving a fixed scale and recording how it was read"""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries: list[dict[str, Any]] = entries
        self.read_with: list[tuple] = []
        self.counted: int = 0

    def get_many(self, sort: str, direction: int) -> list[dict[str, Any]]:
        """Returns the scale, recording the sort it was asked for"""
        self.read_with.append((sort, direction))

        return self._entries

    def count_documents(self, criteria: Optional[dict[str, Any]] = None, limit: Optional[int] = None) -> int:
        """Returns the scale size, recording that the cheap check was used"""
        self.counted += 1

        return len(self._entries)


class _RecordingRiskMatrixManager(_StubRiskMatrixManager):
    """A _StubRiskMatrixManager that also records update_item calls"""

    def __init__(self, initial: Optional[dict[str, Any]]) -> None:
        super().__init__(initial)
        self.updated: list[tuple[int, dict[str, Any]]] = []

    def update_item(self, public_id: int, document: dict[str, Any]) -> None:
        """Records the write and keeps it as the current document"""
        self.updated.append((public_id, document))
        self._current = document


def _calculate_with(monkeypatch: pytest.MonkeyPatch,
                    impacts: list[dict[str, Any]],
                    likelihoods: list[dict[str, Any]],
                    matrix: Optional[dict[str, Any]]) -> tuple[_RecordingRiskMatrixManager,
                                                               _StubScaleManager, _StubScaleManager]:
    """
    Runs calculate_risk_matrix against stub managers

    Args:
        monkeypatch (pytest.MonkeyPatch): Patches ManagerProvider.get_manager
        impacts (list[dict[str, Any]]): The impact scale the stub serves
        likelihoods (list[dict[str, Any]]): The likelihood scale the stub serves
        matrix (dict[str, Any] | None): The stored matrix, or None to exercise the self-heal

    Returns:
        tuple: The matrix manager and the two scale managers, for assertions
    """
    matrix_manager = _RecordingRiskMatrixManager(matrix)
    impact_manager = _StubScaleManager(impacts)
    likelihood_manager = _StubScaleManager(likelihoods)
    by_type = {
        ManagerType.RISK_MATRIX: matrix_manager,
        ManagerType.IMPACT: impact_manager,
        ManagerType.LIKELIHOOD: likelihood_manager,
    }

    monkeypatch.setattr(ManagerProvider, 'get_manager',
                        staticmethod(lambda manager_type, _request_user: by_type[manager_type]))

    calculate_risk_matrix(None)

    return matrix_manager, impact_manager, likelihood_manager


def test_calculate_writes_a_full_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """The assembly: read the singleton, regenerate, transfer, write back to public_id 1."""
    matrix_manager, _, _ = _calculate_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0), _scale_entry(11, 3.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        matrix={RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID, RiskMatrixKey.RISK_MATRIX: [],
                RiskMatrixKey.MATRIX_UNIT: None},
    )

    assert len(matrix_manager.updated) == 1
    written_id, written = matrix_manager.updated[0]
    assert written_id == RISK_MATRIX_PUBLIC_ID
    assert len(written[RiskMatrixKey.RISK_MATRIX]) == 2
    assert {cell[CELL_CALCULATED_VALUE_KEY] for cell in written[RiskMatrixKey.RISK_MATRIX]} == {2.0, 3.0}


def test_calculate_carries_an_existing_assignment_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    An admin's risk-class choice survives a scale change

    This is the whole reason the transfer keys on (impact_id, likelihood_id): the grid is reordered by
    calculation_basis, so a weight change moves the cell but must not move its class.
    """
    stored = {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: [
            {CELL_IMPACT_ID_KEY: 10, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 7},
        ],
        RiskMatrixKey.MATRIX_UNIT: None,
    }

    matrix_manager, _, _ = _calculate_with(
        monkeypatch,
        # The kept pair's impact is now the heavier one, so its cell moves to the second column
        impacts=[_scale_entry(11, 1.0), _scale_entry(10, 5.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        matrix=stored,
    )

    written = matrix_manager.updated[0][1][RiskMatrixKey.RISK_MATRIX]
    kept = next(cell for cell in written if cell[CELL_IMPACT_ID_KEY] == 10)
    added = next(cell for cell in written if cell[CELL_IMPACT_ID_KEY] == 11)

    assert kept[CELL_RISK_CLASS_ID_KEY] == 7
    assert added[CELL_RISK_CLASS_ID_KEY] == 0


def test_calculate_runs_without_any_risk_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The guard this file used to carry is gone, and no risk-class manager is consulted at all

    Requiring one meant that configuring risk classes last left the grid permanently empty: the
    calculation only runs on impact and likelihood writes, so nothing came back to fill it in.
    """
    matrix_manager, _, _ = _calculate_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0)],
        likelihoods=[_scale_entry(20, 3.0)],
        matrix={RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID, RiskMatrixKey.RISK_MATRIX: [],
                RiskMatrixKey.MATRIX_UNIT: None},
    )

    written = matrix_manager.updated[0][1][RiskMatrixKey.RISK_MATRIX]

    assert len(written) == 1
    assert written[0][CELL_CALCULATED_VALUE_KEY] == 6.0


@pytest.mark.parametrize('impacts, likelihoods', [
    ([], [{'public_id': 20, 'calculation_basis': 1.0}]),
    ([{'public_id': 10, 'calculation_basis': 2.0}], []),
    ([], []),
])
def test_calculate_empties_the_grid_when_a_scale_is_empty(
        monkeypatch: pytest.MonkeyPatch, impacts: list[dict[str, Any]],
        likelihoods: list[dict[str, Any]]) -> None:
    """
    An emptied scale leaves an empty grid, not a stale one

    The old guard skipped the write, so cells naming a deleted level stayed in the document. They can
    never match again - a re-added level gets a new public_id - so keeping them preserved nothing and
    hid the real state from the reports and the wizard.
    """
    stored = {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: [
            {CELL_IMPACT_ID_KEY: 10, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 7},
        ],
        RiskMatrixKey.MATRIX_UNIT: None,
    }

    matrix_manager, _, _ = _calculate_with(monkeypatch, impacts, likelihoods, stored)

    assert matrix_manager.updated[0][1][RiskMatrixKey.RISK_MATRIX] == []


def test_calculate_reads_both_scales_in_ascending_weight_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grid is built from its bottom-left corner, which is what the sort is for."""
    _, impact_manager, likelihood_manager = _calculate_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        matrix={RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID, RiskMatrixKey.RISK_MATRIX: [],
                RiskMatrixKey.MATRIX_UNIT: None},
    )

    assert impact_manager.read_with == [(SCALE_SORT_FIELD, SCALE_SORT_ASCENDING)]
    assert likelihood_manager.read_with == [(SCALE_SORT_FIELD, SCALE_SORT_ASCENDING)]


def test_calculate_self_heals_a_missing_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deleted matrix document is recreated before the grid is written into it."""
    matrix_manager, _, _ = _calculate_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        matrix=None,
    )

    assert len(matrix_manager.inserted) == 1
    assert len(matrix_manager.updated[0][1][RiskMatrixKey.RISK_MATRIX]) == 1


# ---------------------------------------- remove_deleted_risk_class_from_matrix ------------------------------------- #

def test_remove_resets_only_the_deleted_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cells of the deleted class go back to unassigned; every other cell is left alone."""
    stored = {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: [
            {CELL_IMPACT_ID_KEY: 10, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 7},
            {CELL_IMPACT_ID_KEY: 11, CELL_LIKELIHOOD_ID_KEY: 20, CELL_RISK_CLASS_ID_KEY: 8},
            {CELL_IMPACT_ID_KEY: 12, CELL_LIKELIHOOD_ID_KEY: 20},
        ],
        RiskMatrixKey.MATRIX_UNIT: None,
    }
    matrix_manager = _RecordingRiskMatrixManager(stored)
    monkeypatch.setattr(ManagerProvider, 'get_manager',
                        staticmethod(lambda _manager_type, _request_user: matrix_manager))

    remove_deleted_risk_class_from_matrix(7, None)

    written = matrix_manager.updated[0][1][RiskMatrixKey.RISK_MATRIX]

    assert written[0][CELL_RISK_CLASS_ID_KEY] == 0
    assert written[1][CELL_RISK_CLASS_ID_KEY] == 8
    # The cell carrying no assignment at all is read defensively rather than raising
    assert CELL_RISK_CLASS_ID_KEY not in written[2]


# ----------------------------------------- ensure_risk_matrix_matches_scales ---------------------------------------- #

def _heal_with(monkeypatch: pytest.MonkeyPatch,
               impacts: list[dict[str, Any]],
               likelihoods: list[dict[str, Any]],
               stored: dict[str, Any]) -> tuple[dict[str, Any], _RecordingRiskMatrixManager,
                                                _StubScaleManager, _StubScaleManager]:
    """
    Runs ensure_risk_matrix_matches_scales against stub managers

    Args:
        monkeypatch (pytest.MonkeyPatch): Patches ManagerProvider.get_manager
        impacts (list[dict[str, Any]]): The impact scale the stub serves
        likelihoods (list[dict[str, Any]]): The likelihood scale the stub serves
        stored (dict[str, Any]): The matrix as currently stored

    Returns:
        tuple: The served matrix, the matrix manager and the two scale managers, for assertions
    """
    matrix_manager = _RecordingRiskMatrixManager(stored)
    impact_manager = _StubScaleManager(impacts)
    likelihood_manager = _StubScaleManager(likelihoods)
    by_type = {
        ManagerType.RISK_MATRIX: matrix_manager,
        ManagerType.IMPACT: impact_manager,
        ManagerType.LIKELIHOOD: likelihood_manager,
    }

    monkeypatch.setattr(ManagerProvider, 'get_manager',
                        staticmethod(lambda manager_type, _request_user: by_type[manager_type]))

    served = ensure_risk_matrix_matches_scales(None, stored)

    return served, matrix_manager, impact_manager, likelihood_manager


def _matrix_doc(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """A stored matrix document carrying the given cells"""
    return {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: cells,
        RiskMatrixKey.MATRIX_UNIT: None,
    }


def test_a_matching_grid_is_served_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The healthy path writes nothing and never loads a scale - two counts is the whole cost."""
    stored = _matrix_doc(_generate_risk_matrix([_scale_entry(10, 2.0), _scale_entry(11, 3.0)],
                                               [_scale_entry(20, 1.0)]))

    served, matrix_manager, impact_manager, likelihood_manager = _heal_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0), _scale_entry(11, 3.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        stored=stored,
    )

    assert served is stored
    assert matrix_manager.updated == []
    assert (impact_manager.counted, likelihood_manager.counted) == (1, 1)
    assert impact_manager.read_with == [] and likelihood_manager.read_with == []


def test_an_empty_grid_is_rebuilt_from_the_scales(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The reported failure: scales configured, grid empty, and nothing but a scale write rebuilt it

    Every database configured under the old minimum-configuration guard is in this state, and removing
    that guard did not repair a single one of them - the grid is only written by the six scale routes.
    """
    served, matrix_manager, _, _ = _heal_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0), _scale_entry(11, 3.0)],
        likelihoods=[_scale_entry(20, 1.0), _scale_entry(21, 2.0)],
        stored=_matrix_doc([]),
    )

    assert len(served[RiskMatrixKey.RISK_MATRIX]) == 4
    assert len(matrix_manager.updated) == 1


def test_healing_keeps_the_existing_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repair must never cost the admin their risk-class assignments."""
    assigned = _generate_risk_matrix([_scale_entry(10, 2.0)], [_scale_entry(20, 1.0)])
    assigned[0][CELL_RISK_CLASS_ID_KEY] = 7

    served, _, _, _ = _heal_with(
        monkeypatch,
        impacts=[_scale_entry(10, 2.0), _scale_entry(11, 3.0)],
        likelihoods=[_scale_entry(20, 1.0)],
        stored=_matrix_doc(assigned),
    )

    kept = [cell for cell in served[RiskMatrixKey.RISK_MATRIX]
            if cell[CELL_IMPACT_ID_KEY] == 10 and cell[CELL_LIKELIHOOD_ID_KEY] == 20]

    assert kept[0][CELL_RISK_CLASS_ID_KEY] == 7


def test_empty_scales_and_an_empty_grid_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh installation is consistent, not stale: 0 cells is exactly what no scales produce."""
    stored = _matrix_doc([])

    served, matrix_manager, _, _ = _heal_with(monkeypatch, impacts=[], likelihoods=[], stored=stored)

    assert served is stored
    assert matrix_manager.updated == []


def test_a_stale_grid_left_by_an_emptied_scale_is_rebuilt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cells naming levels that no longer exist are dropped, not served."""
    served, _, _, _ = _heal_with(
        monkeypatch,
        impacts=[],
        likelihoods=[],
        stored=_matrix_doc(_generate_risk_matrix([_scale_entry(10, 2.0)], [_scale_entry(20, 1.0)])),
    )

    assert served[RiskMatrixKey.RISK_MATRIX] == []
