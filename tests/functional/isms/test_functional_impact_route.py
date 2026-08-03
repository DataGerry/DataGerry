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
Functional smoke for the ``/isms/impacts`` REST routes

Covers the route-layer concerns on top of the ImpactManager suites: HTTP status codes, schema
validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400 mapping, and the
ISMS-specific branches - the max-6 limit (403), the calculation_basis float coercion and uniqueness
(400 on insert and on a colliding update), and the 400 when deleting an Impact referenced by a
RiskAssessment. The routes are ISMS-license gated, so the license check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import MAX_ISMS_SCALE_ENTRIES
from cmdb.errors.manager.impact_manager import (
    ImpactManagerInsertError,
    ImpactManagerGetError,
    ImpactManagerUpdateError,
    ImpactManagerDeleteError,
    ImpactManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/impacts'

IMPACT_ID_FOR_GET: int = 97501
IMPACT_ID_FOR_UPDATE: int = 97502
IMPACT_ID_FOR_DELETE: int = 97503
IMPACT_ID_FOR_BLOCKED_DELETE: int = 97504
IMPACT_ID_OTHER: int = 97505
MISSING_IMPACT_ID: int = 97599
RISK_ASSESSMENT_ID: int = 97550

# A block of ids used to fill the collection up to the MAX_ISMS_SCALE_ENTRIES limit
LIMIT_IMPACT_IDS: list[int] = [97511, 97512, 97513, 97514, 97515, 97516]
LIMIT_EXTRA_ID: int = 97517

ALL_IMPACT_IDS: list[int] = [
    IMPACT_ID_FOR_GET, IMPACT_ID_FOR_UPDATE, IMPACT_ID_FOR_DELETE, IMPACT_ID_FOR_BLOCKED_DELETE,
    IMPACT_ID_OTHER, LIMIT_EXTRA_ID, *LIMIT_IMPACT_IDS,
]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]

BASIS_DEFAULT: float = 1.5
BASIS_OTHER: float = 2.5


def _impact_payload(public_id: int, basis: float = BASIS_DEFAULT, name: str = 'Impact') -> dict[str, Any]:
    """Builds an IsmsImpact body accepted by POST / PUT (name + calculation_basis are required)."""
    return {'public_id': public_id, 'name': name, 'calculation_basis': basis}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/impacts routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any impacts / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_IMPACT_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_impact(database_manager: MongoDatabaseManager, database_name: str,
                   public_id: int, basis: float = BASIS_DEFAULT) -> None:
    """Inserts an IsmsImpact doc directly via the collection."""
    database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': 'Impact', 'calculation_basis': basis})


def _insert_risk_assessment_using_impact(database_manager: MongoDatabaseManager, database_name: str,
                                         impact_id: int) -> None:
    """Inserts an IsmsRiskAssessment that references the given impact, to trigger the delete guard."""
    database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
        'public_id': RISK_ASSESSMENT_ID,
        'risk_calculation_before': {'impacts': [{'impact_id': impact_id}]},
    })


class TestPostImpact:
    """POST /isms/impacts/ creates an IsmsImpact with its business-rule guards."""

    def test_creates_impact(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid body succeeds and the impact becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_name_returns_400(self, rest_api) -> None:
        """A POST without the required name fails schema validation with 400."""
        response = rest_api.post(
            f'{ROUTE_URL}/', json={'calculation_basis': BASIS_DEFAULT},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_non_float_basis_returns_400(self, rest_api) -> None:
        """A calculation_basis that cannot be coerced to float returns 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json={'name': 'Impact', 'calculation_basis': 'nan-value'})\
            .status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_basis_returns_400(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST reusing an existing calculation_basis returns 400."""
        _insert_impact(database_manager, database_name, IMPACT_ID_OTHER, BASIS_OTHER)

        response = rest_api.post(f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET, BASIS_OTHER))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_limit_reached_returns_403(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Creating an Impact beyond the MAX_ISMS_SCALE_ENTRIES limit returns 403."""
        for index, impact_id in enumerate(LIMIT_IMPACT_IDS):
            _insert_impact(database_manager, database_name, impact_id, basis=float(index))

        response = rest_api.post(f'{ROUTE_URL}/',
                                 json=_impact_payload(LIMIT_EXTRA_ID, basis=float(MAX_ISMS_SCALE_ENTRIES)))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestGetImpact:
    """GET /isms/impacts/<id> and GET /isms/impacts/ return the expected envelopes."""

    def test_get_single_returns_impact(self, rest_api,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching impact."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == IMPACT_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_IMPACT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/impacts/ returns a results envelope whose length matches X-Total-Count."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutImpact:
    """PUT /isms/impacts/<id> updates an IsmsImpact and guards basis uniqueness."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}',
                                json=_impact_payload(IMPACT_ID_FOR_UPDATE, BASIS_DEFAULT, 'Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent impact returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_IMPACT_ID}',
                            json=_impact_payload(MISSING_IMPACT_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_update_to_duplicate_basis_returns_400(self, rest_api,
                                                  database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """Changing an impact's basis to one already used by another impact returns 400."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_UPDATE, BASIS_DEFAULT)
        _insert_impact(database_manager, database_name, IMPACT_ID_OTHER, BASIS_OTHER)

        response = rest_api.put(f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}',
                                json=_impact_payload(IMPACT_ID_FOR_UPDATE, BASIS_OTHER))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteImpact:
    """DELETE /isms/impacts/<id> removes the impact unless a RiskAssessment references it."""

    def test_delete_removes_impact(self, rest_api,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{IMPACT_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent impact returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_IMPACT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_blocked_when_used_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Deleting an impact referenced by a RiskAssessment returns 400 and preserves it."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_BLOCKED_DELETE)
        _insert_risk_assessment_using_impact(database_manager, database_name, IMPACT_ID_FOR_BLOCKED_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{IMPACT_ID_FOR_BLOCKED_DELETE}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_BLOCKED_DELETE}').status_code == HTTPStatus.OK


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'insert_item', _raiser(ImpactManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'iterate_items', _raiser(ImpactManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'get_item', _raiser(ImpactManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ImpactManagerUpdateError (impact found, basis unchanged) surfaces as 400."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_UPDATE, BASIS_DEFAULT)
        monkeypatch.setattr(ImpactManager, 'update_item', _raiser(ImpactManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}',
                                json=_impact_payload(IMPACT_ID_FOR_UPDATE, BASIS_DEFAULT))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ImpactManagerDeleteError (impact found, unused) surfaces as 400."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_DELETE)
        monkeypatch.setattr(ImpactManager, 'delete_item', _raiser(ImpactManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{IMPACT_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(ImpactManager, 'insert_item', lambda *_a, **_k: IMPACT_ID_FOR_GET)
        monkeypatch.setattr(ImpactManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'insert_item', lambda *_a, **_k: IMPACT_ID_FOR_GET)
        monkeypatch.setattr(ImpactManager, 'get_item', _raiser(ImpactManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ImpactManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_impact_payload(IMPACT_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ImpactManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ImpactManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{IMPACT_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'get_item', _raiser(ImpactManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}', json=_impact_payload(IMPACT_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(ImpactManager, 'get_item', lambda *_a, **_k: {'public_id': IMPACT_ID_FOR_UPDATE})
        monkeypatch.setattr(ImpactManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}', json=_impact_payload(IMPACT_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(ImpactManager, 'get_item', _raiser(ImpactManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{IMPACT_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(ImpactManager, 'get_item', lambda *_a, **_k: {'public_id': IMPACT_ID_FOR_DELETE})
        monkeypatch.setattr(ImpactManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{IMPACT_ID_FOR_DELETE}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


    def test_update_with_changed_basis_takes_follow_up_path(self, rest_api, monkeypatch,
                                                           database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """Updating with a new calculation_basis succeeds via the risk-assessment follow-up path."""
        _insert_impact(database_manager, database_name, IMPACT_ID_FOR_UPDATE)
        # ignore whatever other impacts exist in the shared test DB - only the changed-basis path matters
        monkeypatch.setattr(ImpactManager, 'impact_calculation_basis_exists', lambda *_a, **_k: False)

        response = rest_api.put(f'{ROUTE_URL}/{IMPACT_ID_FOR_UPDATE}',
                                json=_impact_payload(IMPACT_ID_FOR_UPDATE, BASIS_OTHER))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
