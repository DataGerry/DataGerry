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
Integration tests for the IsmsRiskMatrix singleton's recreation and readiness against a real MongoDB

  - ``ensure_default_risk_matrix`` recreates a missing singleton, and a caller that loses the race to recreate
    it - its insert refused by the real unique ``public_id`` index - reads the winner's document back instead
    of failing; exactly one document is stored
  - ``is_risk_matrix_ready`` over the document as the manager reads it: a stored grid of another size than the
    scales is not ready, a current fully classed one is
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import RiskMatrixManager
from cmdb.models.isms_model import IsmsRiskMatrix
from cmdb.models.isms_model.isms_helper import ensure_default_risk_matrix
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.interface.rest_api.routes.isms_routes.isms_config_helper import is_risk_matrix_ready
# -------------------------------------------------------------------------------------------------------------------- #

WINNER_UNIT: str = 'won-the-race'
CLASSED: int = 5
IMPACTS: int = 2
LIKELIHOODS: int = 3


@pytest.fixture(name='matrices')
def fixture_matrices(database_manager: MongoDatabaseManager, database_name: str):
    """
    The singleton's collection, emptied of it for the test and restored after

    The test session does not run the collection validator, so the declared unique ``public_id`` index - the
    one an installed database holds and the race handling relies on - is built here
    """
    matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
    stored = matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})
    matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})
    existing_indexes: set[str] = set(matrices.index_information())
    built: list[str] = [name for name in matrices.create_indexes(IsmsRiskMatrix.get_index_keys())
                        if name not in existing_indexes]
    yield matrices
    matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})

    # Left as the session found it, so a later test seeding the collection by hand is not refused
    for name in built:
        matrices.drop_index(name)

    if stored:
        matrices.insert_one(stored)


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> RiskMatrixManager:
    """A RiskMatrixManager on the test database"""
    return RiskMatrixManager(database_manager)


def _grid(cell_count: int) -> list[dict[str, Any]]:
    """``cell_count`` classed cells"""
    return [{'impact_id': index, 'likelihood_id': index, 'calculated_value': 1.0, 'risk_class_id': CLASSED}
            for index in range(cell_count)]


class TestRecreation:
    """ensure_default_risk_matrix"""

    def test_a_missing_singleton_is_recreated_once(self, matrices, manager: RiskMatrixManager) -> None:
        """The empty default, stored"""
        result = ensure_default_risk_matrix(manager)

        assert result['public_id'] == RISK_MATRIX_PUBLIC_ID and result['risk_matrix'] == []
        assert matrices.count_documents({'public_id': RISK_MATRIX_PUBLIC_ID}) == 1

    def test_a_lost_race_reads_the_winner_back(self, matrices, manager: RiskMatrixManager, monkeypatch) -> None:
        """The other caller's document is stored between this caller's read and its insert"""
        real_get_item = manager.get_item
        calls: list[int] = []

        def _first_read_misses(public_id: int, as_dict: bool = False) -> Any:
            calls.append(public_id)

            if len(calls) == 1:
                matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': [],
                                     'matrix_unit': WINNER_UNIT})
                return None

            return real_get_item(public_id, as_dict=as_dict)

        monkeypatch.setattr(manager, 'get_item', _first_read_misses)

        result = ensure_default_risk_matrix(manager)

        assert result['matrix_unit'] == WINNER_UNIT
        assert matrices.count_documents({'public_id': RISK_MATRIX_PUBLIC_ID}) == 1


class TestReadiness:
    """is_risk_matrix_ready over the stored document"""

    @pytest.mark.parametrize('cell_count, ready', [
        (IMPACTS * LIKELIHOODS, True), (IMPACTS * LIKELIHOODS - 1, False), (IMPACTS * LIKELIHOODS + 1, False),
    ], ids=['current', 'short', 'too-many'])
    def test_the_stored_grid_is_judged_by_its_size(self, matrices, manager: RiskMatrixManager, cell_count: int,
                                                   ready: bool) -> None:
        """Read through the manager, as the status route reads it"""
        matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': _grid(cell_count),
                             'matrix_unit': None})

        stored = manager.get_item(RISK_MATRIX_PUBLIC_ID, as_dict=True)

        assert is_risk_matrix_ready(stored, IMPACTS, LIKELIHOODS) is ready
