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
Functional smoke for the ``/isms/likelihoods`` REST routes

Covers the route-layer concerns on top of the LikelihoodManager suites: HTTP status codes, schema
validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400 mapping, and the
ISMS-specific branches - the max-6 limit (403), the calculation_basis float coercion and uniqueness
(400 on insert and on a colliding update), and the 400 when deleting a Likelihood referenced by a
RiskAssessment. The routes are ISMS-license gated, so the license check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsLikelihood, IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import MAX_ISMS_SCALE_ENTRIES
from cmdb.errors.manager.likelihood_manager import (
    LikelihoodManagerInsertError,
    LikelihoodManagerGetError,
    LikelihoodManagerUpdateError,
    LikelihoodManagerDeleteError,
    LikelihoodManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/likelihoods'

LIKELIHOOD_ID_FOR_GET: int = 97701
LIKELIHOOD_ID_FOR_UPDATE: int = 97702
LIKELIHOOD_ID_FOR_DELETE: int = 97703
LIKELIHOOD_ID_FOR_BLOCKED_DELETE: int = 97704
LIKELIHOOD_ID_OTHER: int = 97705
MISSING_LIKELIHOOD_ID: int = 97799
RISK_ASSESSMENT_ID: int = 97750

# A block of ids used to fill the collection up to the MAX_ISMS_SCALE_ENTRIES limit
LIMIT_LIKELIHOOD_IDS: list[int] = [97711, 97712, 97713, 97714, 97715, 97716]
LIMIT_EXTRA_ID: int = 97717

ALL_LIKELIHOOD_IDS: list[int] = [
    LIKELIHOOD_ID_FOR_GET, LIKELIHOOD_ID_FOR_UPDATE, LIKELIHOOD_ID_FOR_DELETE, LIKELIHOOD_ID_FOR_BLOCKED_DELETE,
    LIKELIHOOD_ID_OTHER, LIMIT_EXTRA_ID, *LIMIT_LIKELIHOOD_IDS,
]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]

BASIS_DEFAULT: float = 1.5
BASIS_OTHER: float = 2.5


def _likelihood_payload(public_id: int, basis: float = BASIS_DEFAULT, name: str = 'Likelihood') -> dict[str, Any]:
    """Builds an IsmsLikelihood body accepted by POST / PUT (name + calculation_basis are required)."""
    return {'public_id': public_id, 'name': name, 'calculation_basis': basis}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/likelihoods routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any likelihoods / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_LIKELIHOOD_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_likelihood(database_manager: MongoDatabaseManager, database_name: str,
                       public_id: int, basis: float = BASIS_DEFAULT) -> None:
    """Inserts an IsmsLikelihood doc directly via the collection."""
    database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': 'Likelihood', 'calculation_basis': basis})


def _insert_risk_assessment_using_likelihood(database_manager: MongoDatabaseManager, database_name: str,
                                             likelihood_id: int) -> None:
    """Inserts an IsmsRiskAssessment that references the given likelihood, to trigger the delete guard."""
    database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
        'public_id': RISK_ASSESSMENT_ID,
        'risk_calculation_before': {'likelihood_id': likelihood_id, 'likelihood_value': BASIS_DEFAULT},
    })


class TestPostLikelihood:
    """POST /isms/likelihoods/ creates an IsmsLikelihood with its business-rule guards."""

    def test_creates_likelihood(self, rest_api,
                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid body succeeds and the likelihood becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET))

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
        assert rest_api.post(f'{ROUTE_URL}/', json={'name': 'Likelihood', 'calculation_basis': 'nan-value'})\
            .status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_basis_returns_400(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST reusing an existing calculation_basis returns 400."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_OTHER, BASIS_OTHER)

        response = rest_api.post(f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET, BASIS_OTHER))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_limit_reached_returns_403(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Creating a Likelihood beyond the MAX_ISMS_SCALE_ENTRIES limit returns 403."""
        for index, likelihood_id in enumerate(LIMIT_LIKELIHOOD_IDS):
            _insert_likelihood(database_manager, database_name, likelihood_id, basis=float(index))

        response = rest_api.post(f'{ROUTE_URL}/',
                                 json=_likelihood_payload(LIMIT_EXTRA_ID, basis=float(MAX_ISMS_SCALE_ENTRIES)))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestGetLikelihood:
    """GET /isms/likelihoods/<id> and GET /isms/likelihoods/ return the expected envelopes."""

    def test_get_single_returns_likelihood(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching likelihood."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == LIKELIHOOD_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_LIKELIHOOD_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/likelihoods/ returns a results envelope whose length matches X-Total-Count."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutLikelihood:
    """PUT /isms/likelihoods/<id> updates an IsmsLikelihood and guards basis uniqueness."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}',
                                json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE, BASIS_DEFAULT, 'Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        follow_up = rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}')
        assert follow_up.get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent likelihood returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_LIKELIHOOD_ID}',
                            json=_likelihood_payload(MISSING_LIKELIHOOD_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_update_to_duplicate_basis_returns_400(self, rest_api,
                                                  database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """Changing a likelihood's basis to one already used by another likelihood returns 400."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_UPDATE, BASIS_DEFAULT)
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_OTHER, BASIS_OTHER)

        response = rest_api.put(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}',
                                json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE, BASIS_OTHER))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteLikelihood:
    """DELETE /isms/likelihoods/<id> removes the likelihood unless a RiskAssessment references it."""

    def test_delete_removes_likelihood(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent likelihood returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_LIKELIHOOD_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_blocked_when_used_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Deleting a likelihood referenced by a RiskAssessment returns 400 and preserves it."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_BLOCKED_DELETE)
        _insert_risk_assessment_using_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_BLOCKED_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_BLOCKED_DELETE}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_BLOCKED_DELETE}').status_code == HTTPStatus.OK


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A LikelihoodManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'insert_item', _raiser(LikelihoodManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A LikelihoodManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'iterate_items', _raiser(LikelihoodManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A LikelihoodManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', _raiser(LikelihoodManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A LikelihoodManagerUpdateError (likelihood found, basis unchanged) surfaces as 400."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_UPDATE, BASIS_DEFAULT)
        monkeypatch.setattr(LikelihoodManager, 'update_item', _raiser(LikelihoodManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}',
                                json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE, BASIS_DEFAULT))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A LikelihoodManagerDeleteError (likelihood found, unused) surfaces as 400."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_DELETE)
        monkeypatch.setattr(LikelihoodManager, 'delete_item', _raiser(LikelihoodManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(LikelihoodManager, 'insert_item', lambda *_a, **_k: LIKELIHOOD_ID_FOR_GET)
        monkeypatch.setattr(LikelihoodManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'insert_item', lambda *_a, **_k: LIKELIHOOD_ID_FOR_GET)
        monkeypatch.setattr(LikelihoodManager, 'get_item', _raiser(LikelihoodManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(LikelihoodManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_likelihood_payload(LIKELIHOOD_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(LikelihoodManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', _raiser(LikelihoodManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}', json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', lambda *_a, **_k: {'public_id': LIKELIHOOD_ID_FOR_UPDATE})
        monkeypatch.setattr(LikelihoodManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}', json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', _raiser(LikelihoodManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(LikelihoodManager, 'get_item', lambda *_a, **_k: {'public_id': LIKELIHOOD_ID_FOR_DELETE})
        monkeypatch.setattr(LikelihoodManager, 'delete_item', _raiser(RuntimeError('boom')))

        response = rest_api.delete(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_DELETE}')
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


    def test_update_with_changed_basis_takes_follow_up_path(self, rest_api, monkeypatch,
                                                           database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
        """Updating with a new calculation_basis succeeds via the risk-assessment follow-up path."""
        _insert_likelihood(database_manager, database_name, LIKELIHOOD_ID_FOR_UPDATE)
        # ignore whatever other likelihoods exist in the shared test DB - only the changed-basis path matters
        monkeypatch.setattr(LikelihoodManager, 'likelihood_calculation_basis_exists', lambda *_a, **_k: False)

        response = rest_api.put(f'{ROUTE_URL}/{LIKELIHOOD_ID_FOR_UPDATE}',
                                json=_likelihood_payload(LIKELIHOOD_ID_FOR_UPDATE, BASIS_OTHER))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
