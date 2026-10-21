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
Integration tests for the IsmsRiskMatrix self-heal, run against the bound collections

The unit tests pin the decision with stub managers and the route tests pin the HTTP contract; what is
only observable here is that the repair survives the real database: the cheap check reads its counts
from the real scale collections, and the rebuilt grid is written back through the real manager, past
the collection's schema validator.

The defect this guards against was reported against a running installation, not found in a test: a
database whose scales were configured while the old minimum-configuration guard was in place holds an
EMPTY grid, and removing that guard repaired none of them - the matrix is written by the six impact
and likelihood write routes alone, so nothing but a scale edit ever rebuilt it.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.isms_model import IsmsImpact, IsmsLikelihood, IsmsRiskMatrix
from cmdb.models.isms_model.isms_helper import ensure_risk_matrix_matches_scales
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.models.isms_model.isms_risk_matrix_constants import RiskMatrixKey
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_IDS: list[int] = [97501, 97502]
LIKELIHOOD_IDS: list[int] = [97511, 97512, 97513]

FULL_CELL_COUNT: int = len(IMPACT_IDS) * len(LIKELIHOOD_IDS)

ASSIGNED_RISK_CLASS_ID: int = 97520

CELL_IMPACT_ID_KEY: str = 'impact_id'
CELL_LIKELIHOOD_ID_KEY: str = 'likelihood_id'
CELL_RISK_CLASS_ID_KEY: str = 'risk_class_id'


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager,
                     monkeypatch: pytest.MonkeyPatch) -> RiskMatrixManager:
    """
    Wires the REAL ISMS managers to the test database behind ManagerProvider

    The helper resolves its three managers through the provider, which normally needs a request user
    and an application context; pointing it at managers built on the test database is what lets the
    repair run against real collections.
    """
    by_type = {
        ManagerType.IMPACT: ImpactManager(database_manager),
        ManagerType.LIKELIHOOD: LikelihoodManager(database_manager),
        ManagerType.RISK_MATRIX: RiskMatrixManager(database_manager),
    }

    monkeypatch.setattr(ManagerProvider, 'get_manager',
                        staticmethod(lambda manager_type, _request_user: by_type[manager_type]))

    return by_type[ManagerType.RISK_MATRIX]


@pytest.fixture(autouse=True)
def _seeded_scales(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the two scales and an EMPTY singleton - the state every affected database is in

    The singleton is shared, so whatever was stored before is put back afterwards.
    """
    impacts = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
    likelihoods = database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)
    matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)

    stored_singleton = matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})

    impacts.insert_many([{'public_id': public_id, 'name': f'Impact {public_id}',
                          'calculation_basis': float(index + 1)}
                         for index, public_id in enumerate(IMPACT_IDS)])
    likelihoods.insert_many([{'public_id': public_id, 'name': f'Likelihood {public_id}',
                              'calculation_basis': float(index + 1)}
                             for index, public_id in enumerate(LIKELIHOOD_IDS)])
    matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})
    matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': [], 'matrix_unit': None})

    yield matrices

    impacts.delete_many({'public_id': {'$in': IMPACT_IDS}})
    likelihoods.delete_many({'public_id': {'$in': LIKELIHOOD_IDS}})
    matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})

    if stored_singleton:
        matrices.insert_one(stored_singleton)


def _stored_cells(matrices) -> list[dict[str, Any]]:
    """Reads the singleton's cells straight from the collection"""
    return matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})[RiskMatrixKey.RISK_MATRIX]


def _heal(risk_matrix_manager: RiskMatrixManager) -> dict[str, Any]:
    """Runs the self-heal over whatever the collection currently holds"""
    stored = risk_matrix_manager.get_item(RISK_MATRIX_PUBLIC_ID, as_dict=True)

    return ensure_risk_matrix_matches_scales(None, stored)


def test_an_empty_grid_is_rebuilt_and_persisted(managers, _seeded_scales) -> None:
    """The reported state, repaired against the real database and written back through the manager."""
    served = _heal(managers)

    assert len(served[RiskMatrixKey.RISK_MATRIX]) == FULL_CELL_COUNT
    assert len(_stored_cells(_seeded_scales)) == FULL_CELL_COUNT


def test_a_second_read_changes_nothing(managers, _seeded_scales) -> None:
    """Once repaired, the cheap count check agrees and the document is left alone."""
    _heal(managers)
    before = _stored_cells(_seeded_scales)

    served = _heal(managers)

    assert served[RiskMatrixKey.RISK_MATRIX] == before
    assert _stored_cells(_seeded_scales) == before


def test_the_counts_come_from_the_real_collections(managers, _seeded_scales,
                                                   database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
    """
    A scale that shrank behind the application's back is noticed on the next read

    This is the drift a restored dump or a direct database edit produces - nothing calls a scale route,
    so only the read can catch it.
    """
    _heal(managers)

    database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
        .delete_one({'public_id': IMPACT_IDS[0]})

    served = _heal(managers)

    assert len(served[RiskMatrixKey.RISK_MATRIX]) == len(LIKELIHOOD_IDS)
    assert len(_stored_cells(_seeded_scales)) == len(LIKELIHOOD_IDS)


def test_the_repair_keeps_an_assignment(managers, _seeded_scales) -> None:
    """An admin's risk-class assignment survives the rebuild, keyed on its (impact, likelihood) pair."""
    _heal(managers)

    cells = _stored_cells(_seeded_scales)
    kept_cell = dict(cells[0], **{CELL_RISK_CLASS_ID_KEY: ASSIGNED_RISK_CLASS_ID})
    _seeded_scales.update_one({'public_id': RISK_MATRIX_PUBLIC_ID},
                              {'$set': {RiskMatrixKey.RISK_MATRIX: [kept_cell]}})

    served = _heal(managers)
    survivor = [cell for cell in served[RiskMatrixKey.RISK_MATRIX]
                if cell[CELL_IMPACT_ID_KEY] == kept_cell[CELL_IMPACT_ID_KEY]
                and cell[CELL_LIKELIHOOD_ID_KEY] == kept_cell[CELL_LIKELIHOOD_ID_KEY]]

    assert len(served[RiskMatrixKey.RISK_MATRIX]) == FULL_CELL_COUNT
    assert survivor[0][CELL_RISK_CLASS_ID_KEY] == ASSIGNED_RISK_CLASS_ID
