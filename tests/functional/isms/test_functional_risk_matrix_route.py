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
Functional smoke for the ``/isms/risk_matrix`` REST routes

Covers the GET-single and PUT routes of the IsmsRiskMatrix: status codes, the GET envelope, the 404
on a missing id, and the manager-error -> 400 mapping. The RiskMatrix is a singleton (public_id 1)
but the routes are generic get/update by id, so these tests operate on a dedicated throwaway id to
avoid disturbing the shared singleton. The routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskMatrix, IsmsImpact, IsmsLikelihood
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerGetError, RiskMatrixManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_matrix'

RISK_MATRIX_ID: int = 97801
MISSING_RISK_MATRIX_ID: int = 97899

ALL_RISK_MATRIX_IDS: list[int] = [RISK_MATRIX_ID]

MATRIX_UNIT: str = 'EUR'
UPDATED_MATRIX_UNIT: str = 'USD'

# The self-heal operates on the SINGLETON, so its tests seed and restore the real one
HEAL_IMPACT_IDS: list[int] = [97810, 97811]
HEAL_LIKELIHOOD_IDS: list[int] = [97820, 97821, 97822]
HEAL_CELL_COUNT: int = len(HEAL_IMPACT_IDS) * len(HEAL_LIKELIHOOD_IDS)
ASSIGNED_RISK_CLASS_ID: int = 97830


def _risk_matrix_payload(public_id: int, matrix_unit: str = MATRIX_UNIT) -> dict[str, Any]:
    """Builds an IsmsRiskMatrix body accepted by PUT (empty cell list, a unit label)."""
    return {'public_id': public_id, 'risk_matrix': [], 'matrix_unit': matrix_unit}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/risk_matrices routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the throwaway matrix doc seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_MATRIX_IDS}})

    _purge()
    yield
    _purge()


def _insert_matrix(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts an IsmsRiskMatrix doc directly via the collection."""
    database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)\
        .insert_one(_risk_matrix_payload(public_id))


class TestGetRiskMatrix:
    """GET /isms/risk_matrices/<id> returns the matrix or 404."""

    def test_get_returns_matrix(self, rest_api,
                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching matrix."""
        _insert_matrix(database_manager, database_name, RISK_MATRIX_ID)

        response = rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == RISK_MATRIX_ID

    def test_get_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_RISK_MATRIX_ID}').status_code == HTTPStatus.NOT_FOUND


class TestPutRiskMatrix:
    """PUT /isms/risk_matrices/<id> updates the matrix."""

    def test_update_persists_unit(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated matrix_unit."""
        _insert_matrix(database_manager, database_name, RISK_MATRIX_ID)

        response = rest_api.put(f'{ROUTE_URL}/{RISK_MATRIX_ID}',
                                json=_risk_matrix_payload(RISK_MATRIX_ID, UPDATED_MATRIX_UNIT))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        follow_up = rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_ID}')
        assert follow_up.get_json()['result']['matrix_unit'] == UPDATED_MATRIX_UNIT

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent matrix returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_RISK_MATRIX_ID}',
                            json=_risk_matrix_payload(MISSING_RISK_MATRIX_ID)).status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskMatrixManagerGetError on get surfaces as 400."""
        monkeypatch.setattr(RiskMatrixManager, 'get_item', _raiser(RiskMatrixManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskMatrixManagerUpdateError (matrix found) surfaces as 400."""
        _insert_matrix(database_manager, database_name, RISK_MATRIX_ID)
        monkeypatch.setattr(RiskMatrixManager, 'update_item', _raiser(RiskMatrixManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{RISK_MATRIX_ID}', json=_risk_matrix_payload(RISK_MATRIX_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_get_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get surfaces as 500."""
        monkeypatch.setattr(RiskMatrixManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskMatrixManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(RiskMatrixManager, 'get_item', _raiser(RiskMatrixManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{RISK_MATRIX_ID}',
                            json=_risk_matrix_payload(RISK_MATRIX_ID)).status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(RiskMatrixManager, 'get_item', lambda *_a, **_k: {'public_id': RISK_MATRIX_ID})
        monkeypatch.setattr(RiskMatrixManager, 'update_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{RISK_MATRIX_ID}',
                            json=_risk_matrix_payload(RISK_MATRIX_ID)).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestStaleGridIsRepairedOnRead:
    """
    GET rebuilds the singleton's grid when it no longer matches the configured scales

    The reported defect: a database whose scales were configured while the old minimum-configuration
    guard was in place holds an EMPTY grid, and removing that guard repaired nothing - the matrix is
    only ever written by the six impact and likelihood write routes, so without this the customer sees
    an empty array until someone happens to edit a scale.
    """

    @pytest.fixture(autouse=True)
    def _singleton_state(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the scales and an empty singleton grid, restoring both afterwards."""
        matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
        impacts = database_manager.get_collection(IsmsImpact.COLLECTION, database_name)
        likelihoods = database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)

        stored_singleton = matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})

        impacts.insert_many([{'public_id': public_id, 'name': f'Impact {public_id}',
                              'calculation_basis': float(index + 1)}
                             for index, public_id in enumerate(HEAL_IMPACT_IDS)])
        likelihoods.insert_many([{'public_id': public_id, 'name': f'Likelihood {public_id}',
                                  'calculation_basis': float(index + 1)}
                                 for index, public_id in enumerate(HEAL_LIKELIHOOD_IDS)])

        # The state every affected database is in: scales configured, grid never built
        matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})
        matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': [], 'matrix_unit': None})

        yield matrices

        impacts.delete_many({'public_id': {'$in': HEAL_IMPACT_IDS}})
        likelihoods.delete_many({'public_id': {'$in': HEAL_LIKELIHOOD_IDS}})
        matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})

        if stored_singleton:
            matrices.insert_one(stored_singleton)

    @staticmethod
    def _store_grid(matrices, cells: list[dict[str, Any]]) -> None:
        """Puts the singleton into a known grid state"""
        matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})
        matrices.insert_one({'public_id': RISK_MATRIX_PUBLIC_ID, 'risk_matrix': cells,
                             'matrix_unit': None})

    def test_an_empty_grid_is_rebuilt(self, rest_api, _singleton_state) -> None:
        """Impacts and likelihoods configured, grid empty - the read answers with the full grid."""
        self._store_grid(_singleton_state, [])

        response = rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()['result']['risk_matrix']) == HEAL_CELL_COUNT

    def test_the_repair_is_persisted(self, rest_api, _singleton_state) -> None:
        """The rebuilt grid is written back, so every later reader sees it without recomputing."""
        self._store_grid(_singleton_state, [])

        rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}')

        stored = _singleton_state.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})

        assert len(stored['risk_matrix']) == HEAL_CELL_COUNT

    def test_a_current_grid_is_not_rewritten(self, rest_api, _singleton_state) -> None:
        """The healthy path must not touch the document - an assignment in it proves it was kept."""
        rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}')

        healed = _singleton_state.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})['risk_matrix']
        healed[0]['risk_class_id'] = ASSIGNED_RISK_CLASS_ID
        self._store_grid(_singleton_state, healed)

        response = rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}')
        served = response.get_json()['result']['risk_matrix']

        assert len(served) == HEAL_CELL_COUNT
        assert served[0]['risk_class_id'] == ASSIGNED_RISK_CLASS_ID

    def test_the_repair_keeps_existing_assignments(self, rest_api, _singleton_state) -> None:
        """A grid built for a smaller scale is extended, not replaced: the assignment survives."""
        rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}')

        healed = _singleton_state.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})['risk_matrix']
        kept_cell = dict(healed[0], risk_class_id=ASSIGNED_RISK_CLASS_ID)
        self._store_grid(_singleton_state, [kept_cell])

        served = rest_api.get(f'{ROUTE_URL}/{RISK_MATRIX_PUBLIC_ID}').get_json()['result']['risk_matrix']
        survivor = [cell for cell in served
                    if cell['impact_id'] == kept_cell['impact_id']
                    and cell['likelihood_id'] == kept_cell['likelihood_id']]

        assert len(served) == HEAL_CELL_COUNT
        assert survivor[0]['risk_class_id'] == ASSIGNED_RISK_CLASS_ID

    def test_another_id_is_still_a_404(self, rest_api, _singleton_state) -> None:
        """Only the singleton is healed - no other id has scales to be measured against."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_RISK_MATRIX_ID}').status_code == HTTPStatus.NOT_FOUND
