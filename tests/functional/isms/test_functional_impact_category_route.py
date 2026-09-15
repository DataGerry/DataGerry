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
Functional smoke for the ``/isms/impact_categories`` REST routes

Covers the route-layer concerns on top of the ImpactCategoryManager: HTTP status codes, schema
validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400 mapping, and the
``/multiple`` bulk-update route including its 400 guard against a non-list body and the per-item
success / failure summary. The routes are ISMS-license gated, so the license check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsImpactCategory, IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.impact_category_manager import (
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerGetError,
    ImpactCategoryManagerUpdateError,
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/impact_categories'

CATEGORY_ID_FOR_GET: int = 95601
CATEGORY_ID_FOR_UPDATE: int = 95602
CATEGORY_ID_FOR_DELETE: int = 95603
CATEGORY_ID_FOR_INSERT: int = 95604
CATEGORY_ID_MULTI_A: int = 95605
CATEGORY_ID_MULTI_B: int = 95606
MISSING_CATEGORY_ID: int = 95699
RISK_ASSESSMENT_ID: int = 95650

ALL_CATEGORY_IDS: list[int] = [
    CATEGORY_ID_FOR_GET, CATEGORY_ID_FOR_UPDATE, CATEGORY_ID_FOR_DELETE, CATEGORY_ID_FOR_INSERT,
    CATEGORY_ID_MULTI_A, CATEGORY_ID_MULTI_B,
]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]


def _category_payload(public_id: int, name: str = 'Category') -> dict[str, Any]:
    """Builds an IsmsImpactCategory body accepted by POST / PUT (name is required)."""
    return {'public_id': public_id, 'name': name, 'impact_descriptions': [], 'sort': 1}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/impact_categories routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any categories / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CATEGORY_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_category(database_manager: MongoDatabaseManager, database_name: str,
                     public_id: int, name: str = 'Category') -> None:
    """Inserts an IsmsImpactCategory doc directly via the collection."""
    database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': name, 'impact_descriptions': [], 'sort': 1})


class TestPostImpactCategory:
    """POST /isms/impact_categories/ creates an IsmsImpactCategory."""

    def test_creates_category(self, rest_api) -> None:
        """A POST with a valid body succeeds and the category becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_category_payload(CATEGORY_ID_FOR_INSERT))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_name_returns_400(self, rest_api) -> None:
        """A POST without the required name fails schema validation with 400."""
        response = rest_api.post(
            f'{ROUTE_URL}/', json={'impact_descriptions': []},
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGetImpactCategory:
    """GET /isms/impact_categories/<id> and GET /isms/impact_categories/ return the expected envelopes."""

    def test_get_single_returns_category(self, rest_api,
                                         database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching category."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == CATEGORY_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/impact_categories/ returns a results envelope whose length matches X-Total-Count."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutImpactCategory:
    """PUT /isms/impact_categories/<id> updates a single IsmsImpactCategory."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}',
                                json=_category_payload(CATEGORY_ID_FOR_UPDATE, 'Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent category returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}',
                            json=_category_payload(MISSING_CATEGORY_ID)).status_code == HTTPStatus.NOT_FOUND


class TestPutMultipleImpactCategories:
    """PUT /isms/impact_categories/multiple bulk-updates records and guards the body shape."""

    def test_non_list_body_returns_400(self, rest_api) -> None:
        """A non-list JSON body is rejected with 400 rather than causing a 500."""
        response = rest_api.put(f'{ROUTE_URL}/multiple', json={'public_id': CATEGORY_ID_MULTI_A})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_bulk_update_reports_per_item_status(self, rest_api,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """A mixed batch reports success for an existing item and failures for missing / id-less ones."""
        _insert_category(database_manager, database_name, CATEGORY_ID_MULTI_A)

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=[
            _category_payload(CATEGORY_ID_MULTI_A, 'Updated'),
            _category_payload(MISSING_CATEGORY_ID),
            {'name': 'No id'},
        ])

        assert response.status_code == HTTPStatus.OK
        results = response.get_json()
        by_id = {entry['public_id']: entry['status'] for entry in results}
        assert by_id[CATEGORY_ID_MULTI_A] == 'success'
        assert by_id[MISSING_CATEGORY_ID] == 'failed'
        assert by_id[None] == 'failed'
        assert rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_MULTI_A}').get_json()['result']['name'] == 'Updated'


class TestDeleteImpactCategory:
    """DELETE /isms/impact_categories/<id> removes the category and cascades to RiskAssessments."""

    def test_delete_removes_category(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent category returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactCategoryManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'create_with_follow_up',
                            _raiser(ImpactCategoryManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_category_payload(CATEGORY_ID_FOR_INSERT))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactCategoryManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'iterate_items',
                            _raiser(ImpactCategoryManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ImpactCategoryManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item',
                            _raiser(ImpactCategoryManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ImpactCategoryManagerUpdateError (category found) surfaces as 400."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)
        monkeypatch.setattr(ImpactCategoryManager, 'update_item',
                            _raiser(ImpactCategoryManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}',
                                json=_category_payload(CATEGORY_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ImpactCategoryManagerDeleteError (category found) surfaces as 400."""
        _insert_category(database_manager, database_name, CATEGORY_ID_FOR_DELETE)
        monkeypatch.setattr(ImpactCategoryManager, 'delete_with_follow_up',
                            _raiser(ImpactCategoryManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(ImpactCategoryManager, 'insert_item', lambda *_a, **_k: CATEGORY_ID_FOR_GET)
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_category_payload(CATEGORY_ID_FOR_GET))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'insert_item', lambda *_a, **_k: CATEGORY_ID_FOR_GET)
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', _raiser(ImpactCategoryManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_category_payload(CATEGORY_ID_FOR_GET))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ImpactCategoryManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_category_payload(CATEGORY_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ImpactCategoryManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', _raiser(ImpactCategoryManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json=_category_payload(CATEGORY_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', lambda *_a, **_k: {'public_id': CATEGORY_ID_FOR_UPDATE})
        monkeypatch.setattr(ImpactCategoryManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json=_category_payload(CATEGORY_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', _raiser(ImpactCategoryManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(ImpactCategoryManager, 'get_item', lambda *_a, **_k: {'public_id': CATEGORY_ID_FOR_DELETE})
        monkeypatch.setattr(ImpactCategoryManager, 'delete_with_follow_up', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


    def test_update_multiple_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error in the bulk /multiple update surfaces as 500."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.isms_routes.impact_category_routes.update_multiple_items',
            _raiser(RuntimeError('boom')),
        )

        assert rest_api.put(f'{ROUTE_URL}/multiple', json=[]).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
