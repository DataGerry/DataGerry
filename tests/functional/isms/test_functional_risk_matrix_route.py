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
from cmdb.models.isms_model import IsmsRiskMatrix
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.risk_matrix_manager import RiskMatrixManagerGetError, RiskMatrixManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_matrix'

RISK_MATRIX_ID: int = 97801
MISSING_RISK_MATRIX_ID: int = 97899

ALL_RISK_MATRIX_IDS: list[int] = [RISK_MATRIX_ID]

MATRIX_UNIT: str = 'EUR'
UPDATED_MATRIX_UNIT: str = 'USD'


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
