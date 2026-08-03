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
Functional smoke for the ``/isms/control_measures`` REST routes

Covers CRUD, the control_measure_type enum validation (invalid type -> 400 on insert and update),
the manager-error -> 400 mapping, and the 400 when deleting a ControlMeasure still referenced by a
ControlMeasureAssignment. The routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment, ControlMeasureType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.control_measure_manager import (
    ControlMeasureManagerInsertError,
    ControlMeasureManagerGetError,
    ControlMeasureManagerUpdateError,
    ControlMeasureManagerDeleteError,
    ControlMeasureManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/control_measures'

CM_ID_FOR_GET: int = 98301
CM_ID_FOR_UPDATE: int = 98302
CM_ID_FOR_DELETE: int = 98303
CM_ID_FOR_BLOCKED_DELETE: int = 98304
MISSING_CM_ID: int = 98399

# bulk-delete fixtures: two unused controls, one still referenced by an assignment
CM_BULK_UNUSED_A: int = 98311
CM_BULK_UNUSED_B: int = 98312
CM_BULK_USED: int = 98313

CONTROL_ASSIGNMENT_ID: int = 98350
BULK_ASSIGNMENT_ID: int = 98351

ALL_CM_IDS: list[int] = [
    CM_ID_FOR_GET, CM_ID_FOR_UPDATE, CM_ID_FOR_DELETE, CM_ID_FOR_BLOCKED_DELETE,
    CM_BULK_UNUSED_A, CM_BULK_UNUSED_B, CM_BULK_USED,
]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CONTROL_ASSIGNMENT_ID, BULK_ASSIGNMENT_ID]


def _control_measure_payload(public_id: int, control_measure_type: str = ControlMeasureType.CONTROL,
                             title: str = 'Control') -> dict[str, Any]:
    """Builds a valid IsmsControlMeasure body (all schema-required fields present)."""
    return {
        'public_id': public_id,
        'title': title,
        'control_measure_type': control_measure_type,
        'source': 1,
        'implementation_state': 1,
        'identifier': 'CM-1',
        'chapter': 'A.1',
        'description': 'A description',
        'is_applicable': True,
        'reason': 'A reason',
    }


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/control_measures routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any control measures / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CM_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_control_measure(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts an IsmsControlMeasure doc directly via the collection."""
    database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
        .insert_one(_control_measure_payload(public_id))


def _insert_assignment_using(database_manager: MongoDatabaseManager, database_name: str,
                             control_measure_id: int) -> None:
    """Inserts an IsmsControlMeasureAssignment referencing the control measure, for the delete guard."""
    database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
        .insert_one({'public_id': CONTROL_ASSIGNMENT_ID, 'control_measure_id': control_measure_id})


class TestPostControlMeasure:
    """POST /isms/control_measures/ creates an IsmsControlMeasure with its type validation."""

    def test_creates_control_measure(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a valid body succeeds and the control measure becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_title_returns_400(self, rest_api) -> None:
        """A POST without the required title fails schema validation with 400."""
        payload = _control_measure_payload(CM_ID_FOR_GET)
        payload.pop('title')

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_type_returns_400(self, rest_api) -> None:
        """A POST with an unknown control_measure_type is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET, 'NOT_A_TYPE'))\
            .status_code == HTTPStatus.BAD_REQUEST


class TestGetControlMeasure:
    """GET /isms/control_measures/<id> and GET /isms/control_measures/ return the expected envelopes."""

    def test_get_single_returns_control_measure(self, rest_api,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching control measure."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == CM_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_CM_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/control_measures/ returns a results envelope whose length matches X-Total-Count."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutControlMeasure:
    """PUT /isms/control_measures/<id> updates a single IsmsControlMeasure."""

    def test_update_persists_title(self, rest_api,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated title."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}',
                                json=_control_measure_payload(CM_ID_FOR_UPDATE, title='Renamed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}').get_json()['result']['title'] == 'Renamed'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent control measure returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_CM_ID}',
                            json=_control_measure_payload(MISSING_CM_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_update_invalid_type_returns_400(self, rest_api,
                                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Updating with an unknown control_measure_type is rejected with 400."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}',
                                json=_control_measure_payload(CM_ID_FOR_UPDATE, 'NOT_A_TYPE'))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteControlMeasure:
    """DELETE /isms/control_measures/<id> removes the class unless an assignment references it."""

    def test_delete_removes_control_measure(self, rest_api,
                                           database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{CM_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent control measure returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CM_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_blocked_when_used_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Deleting a control measure referenced by an assignment returns 400 and preserves it."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_BLOCKED_DELETE)
        _insert_assignment_using(database_manager, database_name, CM_ID_FOR_BLOCKED_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{CM_ID_FOR_BLOCKED_DELETE}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_BLOCKED_DELETE}').status_code == HTTPStatus.OK


class TestDeleteManyControlMeasures:
    """DELETE /isms/control_measures/delete/<ids> removes unused controls and reports the still-used ones."""

    def test_bulk_delete_removes_unused_and_reports_in_use(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Unused controls are deleted; the one referenced by an assignment is kept and reported in_use."""
        _insert_control_measure(database_manager, database_name, CM_BULK_UNUSED_A)
        _insert_control_measure(database_manager, database_name, CM_BULK_UNUSED_B)
        _insert_control_measure(database_manager, database_name, CM_BULK_USED)
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .insert_one({'public_id': BULK_ASSIGNMENT_ID, 'control_measure_id': CM_BULK_USED})

        response = rest_api.delete(f'{ROUTE_URL}/delete/{CM_BULK_UNUSED_A},{CM_BULK_UNUSED_B},{CM_BULK_USED}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        body = response.get_json()
        assert body['successfully'] == sorted([CM_BULK_UNUSED_A, CM_BULK_UNUSED_B])
        assert body['in_use'] == [CM_BULK_USED]
        # the unused ones are gone, the in-use one is preserved
        assert rest_api.get(f'{ROUTE_URL}/{CM_BULK_UNUSED_A}').status_code == HTTPStatus.NOT_FOUND
        assert rest_api.get(f'{ROUTE_URL}/{CM_BULK_USED}').status_code == HTTPStatus.OK

    def test_bulk_delete_ignores_non_existent_ids(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A non-existent id is neither deleted-reported nor errored; only real deletions are listed."""
        _insert_control_measure(database_manager, database_name, CM_BULK_UNUSED_A)

        response = rest_api.delete(f'{ROUTE_URL}/delete/{CM_BULK_UNUSED_A},{MISSING_CM_ID}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        body = response.get_json()
        assert body['successfully'] == [CM_BULK_UNUSED_A]
        assert body['in_use'] == []

    def test_bulk_delete_invalid_id_returns_400(self, rest_api) -> None:
        """A non-integer id in the list is rejected with 400."""
        assert rest_api.delete(f'{ROUTE_URL}/delete/{CM_BULK_UNUSED_A},not-an-int')\
            .status_code == HTTPStatus.BAD_REQUEST


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'insert_item', _raiser(ControlMeasureManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'iterate_items',
                            _raiser(ControlMeasureManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ControlMeasureManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', _raiser(ControlMeasureManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ControlMeasureManagerUpdateError (measure found, valid type) surfaces as 400."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_UPDATE)
        monkeypatch.setattr(ControlMeasureManager, 'update_item', _raiser(ControlMeasureManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}', json=_control_measure_payload(CM_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ControlMeasureManagerDeleteError (measure found, unused) surfaces as 400."""
        _insert_control_measure(database_manager, database_name, CM_ID_FOR_DELETE)
        monkeypatch.setattr(ControlMeasureManager, 'delete_item', _raiser(ControlMeasureManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CM_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(ControlMeasureManager, 'insert_item', lambda *_a, **_k: CM_ID_FOR_GET)
        monkeypatch.setattr(ControlMeasureManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET))
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'insert_item', lambda *_a, **_k: CM_ID_FOR_GET)
        monkeypatch.setattr(ControlMeasureManager, 'get_item', _raiser(ControlMeasureManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ControlMeasureManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_control_measure_payload(CM_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ControlMeasureManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{CM_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', _raiser(ControlMeasureManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}', json=_control_measure_payload(CM_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', lambda *_a, **_k: {'public_id': CM_ID_FOR_UPDATE})
        monkeypatch.setattr(ControlMeasureManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{CM_ID_FOR_UPDATE}', json=_control_measure_payload(CM_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', _raiser(ControlMeasureManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CM_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(ControlMeasureManager, 'get_item', lambda *_a, **_k: {'public_id': CM_ID_FOR_DELETE})
        monkeypatch.setattr(ControlMeasureManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{CM_ID_FOR_DELETE}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
