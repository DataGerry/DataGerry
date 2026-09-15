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
Functional smoke for the ``/isms/risk_classes`` REST routes

Covers CRUD (incl. the max-MAX_ISMS_RISK_CLASSES limit -> 403), the bulk ``PUT /multiple`` route with
its per-item success/failure results, the manager-error -> 400 mapping, and the DELETE side effect
that resets the deleted class out of the RiskMatrix singleton (public_id 1). The routes are
ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskClass, IsmsRiskMatrix
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import MAX_ISMS_RISK_CLASSES
from cmdb.errors.manager.risk_class_manager import (
    RiskClassManagerInsertError,
    RiskClassManagerGetError,
    RiskClassManagerUpdateError,
    RiskClassManagerDeleteError,
    RiskClassManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_classes'
RISK_MATRIX_SINGLETON_ID: int = 1

RC_ID_FOR_GET: int = 97901
RC_ID_FOR_UPDATE: int = 97902
RC_ID_FOR_DELETE: int = 97903
RC_ID_FOR_BULK: int = 97904
RC_ID_FOR_MATRIX: int = 97905
MISSING_RC_ID: int = 97999

# A block of ids used to fill the collection up to the MAX_ISMS_RISK_CLASSES limit
LIMIT_RC_IDS: list[int] = [97911, 97912, 97913, 97914, 97915, 97916, 97917, 97918, 97919, 97920]
LIMIT_EXTRA_ID: int = 97921

ALL_RC_IDS: list[int] = [
    RC_ID_FOR_GET, RC_ID_FOR_UPDATE, RC_ID_FOR_DELETE, RC_ID_FOR_BULK, RC_ID_FOR_MATRIX,
    LIMIT_EXTRA_ID, *LIMIT_RC_IDS,
]

COLOR: str = '#aabbcc'


def _risk_class_payload(public_id: int, name: str = 'RiskClass') -> dict[str, Any]:
    """Builds an IsmsRiskClass body accepted by POST / PUT (name + color are required)."""
    return {'public_id': public_id, 'name': name, 'color': COLOR}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/risk_class routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any risk classes seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RC_IDS}})

    _purge()
    yield
    _purge()


def _insert_risk_class(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts an IsmsRiskClass doc directly via the collection."""
    database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': 'RiskClass', 'color': COLOR})


class TestPostRiskClass:
    """POST /isms/risk_class/ creates an IsmsRiskClass with the count-limit guard."""

    def test_creates_risk_class(self, rest_api,
                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid body succeeds and the risk class becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_name_returns_400(self, rest_api) -> None:
        """A POST without the required name fails schema validation with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json={'color': COLOR}).status_code == HTTPStatus.BAD_REQUEST

    def test_limit_reached_returns_403(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Creating a RiskClass beyond the MAX_ISMS_RISK_CLASSES limit returns 403."""
        for risk_class_id in LIMIT_RC_IDS:
            _insert_risk_class(database_manager, database_name, risk_class_id)

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(LIMIT_EXTRA_ID))

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestGetRiskClass:
    """GET /isms/risk_class/<id> and GET /isms/risk_class/ return the expected envelopes."""

    def test_get_single_returns_risk_class(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching risk class."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{RC_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == RC_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_RC_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/risk_class/ returns a results envelope whose length matches X-Total-Count."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutRiskClass:
    """PUT /isms/risk_class/<id> updates a single IsmsRiskClass."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}',
                                json=_risk_class_payload(RC_ID_FOR_UPDATE, 'Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent risk class returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_RC_ID}',
                            json=_risk_class_payload(MISSING_RC_ID)).status_code == HTTPStatus.NOT_FOUND


class TestUpdateMultipleRiskClasses:
    """PUT /isms/risk_class/multiple reports a per-item result for each entry."""

    def test_reports_per_item_status(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A mixed batch yields success, not-found, and missing-public_id results respectively."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_BULK)

        payload = [
            _risk_class_payload(RC_ID_FOR_BULK, 'Updated'),
            _risk_class_payload(MISSING_RC_ID),
            {'name': 'NoId', 'color': COLOR},
        ]

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        results = response.get_json()
        statuses = {result.get('public_id'): result['status'] for result in results}
        assert statuses[RC_ID_FOR_BULK] == 'success'
        assert statuses[MISSING_RC_ID] == 'failed'
        assert statuses[None] == 'failed'


class TestDeleteRiskClass:
    """DELETE /isms/risk_class/<id> removes the class and resets it out of the RiskMatrix."""

    def test_delete_removes_risk_class(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{RC_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{RC_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent risk class returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_RC_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_resets_risk_class_in_matrix(self, rest_api,
                                               database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """Deleting a risk class resets every matrix cell that referenced it back to 0."""
        matrix_collection = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_MATRIX)
        matrix_collection.update_one(
            {'public_id': RISK_MATRIX_SINGLETON_ID},
            {'$set': {'risk_matrix': [{'row': 0, 'column': 0, 'risk_class_id': RC_ID_FOR_MATRIX}]}},
            upsert=True,
        )
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{RC_ID_FOR_MATRIX}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            matrix = matrix_collection.find_one({'public_id': RISK_MATRIX_SINGLETON_ID})
            assert matrix['risk_matrix'][0]['risk_class_id'] == 0
        finally:
            matrix_collection.update_one(
                {'public_id': RISK_MATRIX_SINGLETON_ID}, {'$set': {'risk_matrix': []}}
            )


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskClassManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'insert_item', _raiser(RiskClassManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskClassManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'iterate_items', _raiser(RiskClassManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RiskClassManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'get_item', _raiser(RiskClassManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RC_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskClassManagerUpdateError (class found) surfaces as 400."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_UPDATE)
        monkeypatch.setattr(RiskClassManager, 'update_item', _raiser(RiskClassManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}', json=_risk_class_payload(RC_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A RiskClassManagerDeleteError (class found) surfaces as 400."""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_DELETE)
        monkeypatch.setattr(RiskClassManager, 'delete_item', _raiser(RiskClassManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{RC_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(RiskClassManager, 'insert_item', lambda *_a, **_k: RC_ID_FOR_GET)
        monkeypatch.setattr(RiskClassManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'insert_item', lambda *_a, **_k: RC_ID_FOR_GET)
        monkeypatch.setattr(RiskClassManager, 'get_item', _raiser(RiskClassManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(RiskClassManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(RiskClassManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(RiskClassManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{RC_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'get_item', _raiser(RiskClassManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}', json=_risk_class_payload(RC_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(RiskClassManager, 'get_item', lambda *_a, **_k: {'public_id': RC_ID_FOR_UPDATE})
        monkeypatch.setattr(RiskClassManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}', json=_risk_class_payload(RC_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(RiskClassManager, 'get_item', _raiser(RiskClassManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{RC_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(RiskClassManager, 'get_item', lambda *_a, **_k: {'public_id': RC_ID_FOR_DELETE})
        monkeypatch.setattr(RiskClassManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{RC_ID_FOR_DELETE}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


    def test_update_multiple_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error in the bulk /multiple update surfaces as 500."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.isms_routes.risk_class_routes.update_multiple_items',
            _raiser(RuntimeError('boom')),
        )

        assert rest_api.put(f'{ROUTE_URL}/multiple', json=[]).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_multiple_http_error_is_reraised(self, rest_api, monkeypatch) -> None:
        """An HTTPException from the bulk /multiple update propagates unchanged (not masked as 500)."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.isms_routes.risk_class_routes.update_multiple_items',
            _raiser(BadRequest()),
        )

        assert rest_api.put(f'{ROUTE_URL}/multiple', json=[]).status_code == HTTPStatus.BAD_REQUEST
