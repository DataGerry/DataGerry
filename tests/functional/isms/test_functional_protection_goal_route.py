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
Functional smoke for the ``/isms/protection_goals`` REST routes

Covers CRUD, the predefined guards (predefined goals cannot be created / edited / deleted), the
name-uniqueness rules (duplicate insert / colliding update rejected, but an update that keeps the
goal's own name is allowed - the audit-item-12 regression), the delete-when-used 400, and the
manager-error -> 400 mapping. The routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsProtectionGoal, IsmsRisk
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerInsertError,
    ProtectionGoalManagerGetError,
    ProtectionGoalManagerUpdateError,
    ProtectionGoalManagerDeleteError,
    ProtectionGoalManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/protection_goals'

PG_ID_FOR_GET: int = 99601
PG_ID_FOR_UPDATE: int = 99602
PG_ID_FOR_DELETE: int = 99603
PG_ID_PREDEFINED: int = 99604
PG_ID_OTHER: int = 99605
PG_ID_FOR_BLOCKED_DELETE: int = 99606
MISSING_PG_ID: int = 99699

RISK_ID: int = 99650

EXISTING_NAME: str = 'ImportTest Existing Goal'
OTHER_NAME: str = 'ImportTest Other Goal'

ALL_PG_IDS: list[int] = [
    PG_ID_FOR_GET, PG_ID_FOR_UPDATE, PG_ID_FOR_DELETE, PG_ID_PREDEFINED,
    PG_ID_OTHER, PG_ID_FOR_BLOCKED_DELETE,
]
ALL_RISK_IDS: list[int] = [RISK_ID]


def _pg_payload(public_id: int, name: str = 'ImportTest Goal', predefined: bool = False) -> dict[str, Any]:
    """Builds an IsmsProtectionGoal body (name + predefined are required)."""
    return {'public_id': public_id, 'name': name, 'predefined': predefined}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated /isms/protection_goals routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any protection goals / risks seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_PG_IDS}})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_IDS}})

    _purge()
    yield
    _purge()


def _insert_goal(database_manager: MongoDatabaseManager, database_name: str,
                 public_id: int, name: str = 'ImportTest Goal', predefined: bool = False) -> None:
    """Inserts an IsmsProtectionGoal doc directly via the collection."""
    database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
        .insert_one({'public_id': public_id, 'name': name, 'predefined': predefined})


class TestPostProtectionGoal:
    """POST /isms/protection_goals/ creates a goal with its guards."""

    def test_creates_goal(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid POST succeeds and the goal becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_missing_name_returns_400(self, rest_api) -> None:
        """A POST without the required name fails schema validation with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json={'predefined': False}).status_code == HTTPStatus.BAD_REQUEST

    def test_predefined_create_returns_400(self, rest_api) -> None:
        """Creating a predefined goal via the API is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET, predefined=True))\
            .status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_name_returns_400(self, rest_api,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST reusing an existing name is rejected with 400."""
        _insert_goal(database_manager, database_name, PG_ID_OTHER, name=EXISTING_NAME)

        assert rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET, name=EXISTING_NAME))\
            .status_code == HTTPStatus.BAD_REQUEST


class TestGetProtectionGoal:
    """GET /isms/protection_goals/<id> and GET /isms/protection_goals/ envelopes."""

    def test_get_single_returns_goal(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching goal."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{PG_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == PG_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_PG_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /isms/protection_goals/ returns a results envelope matching X-Total-Count."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutProtectionGoal:
    """PUT /isms/protection_goals/<id> and its name / predefined guards."""

    def test_update_keeping_own_name_succeeds(self, rest_api,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Updating a goal while keeping its own name is allowed (audit item 12 regression)."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_UPDATE, name=EXISTING_NAME)

        response = rest_api.put(f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}',
                                json=_pg_payload(PG_ID_FOR_UPDATE, name=EXISTING_NAME))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_update_to_other_goals_name_returns_400(self, rest_api,
                                                   database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """Updating a goal to a name held by a different goal is rejected with 400."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_UPDATE, name=EXISTING_NAME)
        _insert_goal(database_manager, database_name, PG_ID_OTHER, name=OTHER_NAME)

        response = rest_api.put(f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}', json=_pg_payload(PG_ID_FOR_UPDATE, name=OTHER_NAME))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent goal returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_PG_ID}',
                            json=_pg_payload(MISSING_PG_ID)).status_code == HTTPStatus.NOT_FOUND

    def test_changing_predefined_flag_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Flipping the predefined flag on update is rejected with 400."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_UPDATE, predefined=False)

        response = rest_api.put(f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}',
                                json=_pg_payload(PG_ID_FOR_UPDATE, predefined=True))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_editing_predefined_goal_returns_400(self, rest_api,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """A predefined goal cannot be edited (400)."""
        _insert_goal(database_manager, database_name, PG_ID_PREDEFINED, predefined=True)

        response = rest_api.put(f'{ROUTE_URL}/{PG_ID_PREDEFINED}',
                                json=_pg_payload(PG_ID_PREDEFINED, predefined=True))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteProtectionGoal:
    """DELETE /isms/protection_goals/<id> and its guards."""

    def test_delete_removes_goal(self, rest_api,
                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{PG_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{PG_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent goal returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_PG_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_predefined_returns_400(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A predefined goal cannot be deleted (400)."""
        _insert_goal(database_manager, database_name, PG_ID_PREDEFINED, predefined=True)

        assert rest_api.delete(f'{ROUTE_URL}/{PG_ID_PREDEFINED}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_blocked_when_used_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """Deleting a goal referenced by a Risk returns 400 and preserves it."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_BLOCKED_DELETE)
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .insert_one({'public_id': RISK_ID, 'protection_goals': [PG_ID_FOR_BLOCKED_DELETE]})

        response = rest_api.delete(f'{ROUTE_URL}/{PG_ID_FOR_BLOCKED_DELETE}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{PG_ID_FOR_BLOCKED_DELETE}').status_code == HTTPStatus.OK


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ProtectionGoalManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'insert_item', _raiser(ProtectionGoalManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET)).status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ProtectionGoalManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'iterate_items',
                            _raiser(ProtectionGoalManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ProtectionGoalManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', _raiser(ProtectionGoalManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{PG_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ProtectionGoalManagerUpdateError (goal found) surfaces as 400."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_UPDATE)
        monkeypatch.setattr(ProtectionGoalManager, 'update_item', _raiser(ProtectionGoalManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}', json=_pg_payload(PG_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A ProtectionGoalManagerDeleteError (goal found) surfaces as 400."""
        _insert_goal(database_manager, database_name, PG_ID_FOR_DELETE)
        monkeypatch.setattr(ProtectionGoalManager, 'delete_with_follow_up',
                            _raiser(ProtectionGoalManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PG_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created item cannot be re-read after insert, the route returns 404."""
        monkeypatch.setattr(ProtectionGoalManager, 'insert_item', lambda *_a, **_k: PG_ID_FOR_GET)
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', lambda *_a, **_k: None)

        assert rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET)).status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError while re-reading the created item surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'insert_item', lambda *_a, **_k: PG_ID_FOR_GET)
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', _raiser(ProtectionGoalManagerGetError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET)).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ProtectionGoalManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{ROUTE_URL}/', json=_pg_payload(PG_ID_FOR_GET),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ProtectionGoalManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{PG_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the update existence check surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', _raiser(ProtectionGoalManagerGetError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}', json=_pg_payload(PG_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating surfaces as 500."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', lambda *_a, **_k: {'public_id': PG_ID_FOR_UPDATE})
        monkeypatch.setattr(ProtectionGoalManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{ROUTE_URL}/{PG_ID_FOR_UPDATE}', json=_pg_payload(PG_ID_FOR_UPDATE),
        )
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A ManagerGetError during the delete existence check surfaces as 400."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', _raiser(ProtectionGoalManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PG_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while deleting surfaces as 500."""
        monkeypatch.setattr(ProtectionGoalManager, 'get_item', lambda *_a, **_k: {'public_id': PG_ID_FOR_DELETE})
        monkeypatch.setattr(ProtectionGoalManager, 'delete_with_follow_up', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PG_ID_FOR_DELETE}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
