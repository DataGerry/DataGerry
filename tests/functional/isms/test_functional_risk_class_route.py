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

Covers CRUD (incl. the max-MAX_ISMS_RISK_CLASSES limit -> 400), the bulk ``PUT /multiple`` route with
its per-item success/failure results, the manager-error -> 400 mapping, and the DELETE side effect
that resets the deleted class out of the RiskMatrix singleton (public_id 1). The routes are
ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ISMS_CAP_REACHED_MSG,
    ISMS_RISK_CLASSES_LABEL,
    MAX_ISMS_RISK_CLASSES,
    RISK_CLASS_LABEL,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskClass, IsmsRiskMatrix
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.risk_class_manager import (
    RiskClassManagerInsertError,
    RiskClassManagerGetError,
    RiskClassManagerUpdateError,
    RiskClassManagerDeleteError,
    RiskClassManagerIterationError,
)

from tests.utils.update_response import assert_body_public_id_cannot_move
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_classes'
RISK_MATRIX_SINGLETON_ID: int = 1

RC_ID_FOR_GET: int = 97901
RC_ID_FOR_UPDATE: int = 97902
RC_ID_FOR_DELETE: int = 97903
RC_ID_FOR_BULK: int = 97904
RC_ID_FOR_MATRIX: int = 97905
RC_ID_FOR_BULK_2: int = 97906
MISSING_RC_ID: int = 97999

# A block of ids used to fill the collection up to the MAX_ISMS_RISK_CLASSES limit
LIMIT_RC_IDS: list[int] = [97911, 97912, 97913, 97914, 97915, 97916, 97917, 97918, 97919, 97920]
LIMIT_EXTRA_ID: int = 97921

ALL_RC_IDS: list[int] = [
    RC_ID_FOR_GET, RC_ID_FOR_UPDATE, RC_ID_FOR_DELETE, RC_ID_FOR_BULK, RC_ID_FOR_BULK_2, RC_ID_FOR_MATRIX,
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

    def test_limit_reached_returns_400(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Creating a RiskClass beyond the MAX_ISMS_RISK_CLASSES limit is refused with 400."""
        for risk_class_id in LIMIT_RC_IDS:
            _insert_risk_class(database_manager, database_name, risk_class_id)

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(LIMIT_EXTRA_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == ISMS_CAP_REACHED_MSG.format(cap=MAX_ISMS_RISK_CLASSES,
                                                                          entity_label=ISMS_RISK_CLASSES_LABEL)
        stored = database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name)
        assert stored.find_one({'public_id': LIMIT_EXTRA_ID}) is None


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

    def test_a_body_public_id_can_not_move_the_risk_class(self, rest_api,
            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT is addressed by the URL; a body naming another public_id leaves the stored risk class in place"""
        _insert_risk_class(database_manager, database_name, RC_ID_FOR_UPDATE)

        assert_body_public_id_cannot_move(
            rest_api, f'{ROUTE_URL}/{RC_ID_FOR_UPDATE}', _risk_class_payload(MISSING_RC_ID),
            database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name), RC_ID_FOR_UPDATE,
        )

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent risk class returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_RC_ID}',
                            json=_risk_class_payload(MISSING_RC_ID)).status_code == HTTPStatus.NOT_FOUND


class TestUpdateMultipleRiskClasses:
    """
    PUT /isms/risk_classes/multiple - the wizard's drag reorder, all or nothing

    Every item is judged by the single update's write schema before anything is written; any refusal is one
    400 naming every reason, and the stored classes are left exactly as they were
    """

    def _stored(self, database_manager: MongoDatabaseManager, database_name: str) -> dict[int, dict[str, Any]]:
        """The two bulk classes as stored"""
        collection = database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name)

        return {doc['public_id']: doc for doc in collection.find(
            {'public_id': {'$in': [RC_ID_FOR_BULK, RC_ID_FOR_BULK_2]}}, {'_id': 0},
        )}

    @pytest.fixture(name='listed')
    def fixture_listed(self, rest_api, database_manager: MongoDatabaseManager,
                       database_name: str) -> list[dict[str, Any]]:
        """Two stored classes, read back the way the wizard reads them: from the list"""
        for public_id in (RC_ID_FOR_BULK, RC_ID_FOR_BULK_2):
            _insert_risk_class(database_manager, database_name, public_id)

        rows = rest_api.get(f'{ROUTE_URL}/', query_string={'limit': 0}).get_json()['results']

        return [row for row in rows if row['public_id'] in (RC_ID_FOR_BULK, RC_ID_FOR_BULK_2)]

    def test_the_wizards_reorder_round_trip_is_written(self, rest_api, listed, database_manager,
                                                       database_name: str) -> None:
        """The list rows carry null description and sort; renumbered and sent back whole, they are stored"""
        assert {row['description'] for row in listed} == {None}
        reordered = [{**row, 'sort': index} for index, row in enumerate(reversed(listed))]

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=reordered)

        assert response.status_code == HTTPStatus.OK, response.get_json()
        assert response.get_json() == [{'public_id': row['public_id'], 'status': 'success'} for row in reordered]
        stored = self._stored(database_manager, database_name)
        assert {public_id: doc['sort'] for public_id, doc in stored.items()} == {
            row['public_id']: row['sort'] for row in reordered
        }

    def test_one_invalid_item_refuses_the_whole_list(self, rest_api, listed, database_manager,
                                                    database_name: str) -> None:
        """The valid item is not written either, and the refusal names the bad one"""
        before = self._stored(database_manager, database_name)
        payload = [{**listed[0], 'name': 'Renamed'}, {**listed[1], 'name': 123, 'color': ['x']}]

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        message = response.get_json()['message']
        assert message.startswith('No RiskClasses were updated, because some items are invalid: item #2')
        assert 'name: must be of string type' in message and 'color: must be of string type' in message
        assert self._stored(database_manager, database_name) == before

    def test_an_empty_name_is_refused(self, rest_api, listed) -> None:
        """The single update's rule, not a looser bulk one"""
        response = rest_api.put(f'{ROUTE_URL}/multiple', json=[{**listed[0], 'name': ''}])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'name: empty values not allowed' in response.get_json()['message']

    def test_an_unknown_id_refuses_the_whole_list(self, rest_api, listed, database_manager,
                                                 database_name: str) -> None:
        """It used to be a 'failed' entry inside a 200 the wizard never looked at"""
        before = self._stored(database_manager, database_name)

        response = rest_api.put(f'{ROUTE_URL}/multiple',
                                json=[{**listed[0], 'sort': 5}, _risk_class_payload(MISSING_RC_ID)])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == (
            f'No RiskClasses were updated, because these ids do not exist: [{MISSING_RC_ID}]'
        )
        assert self._stored(database_manager, database_name) == before

    def test_an_id_sent_twice_is_refused(self, rest_api, listed) -> None:
        """Last-one-wins is no order anybody chose"""
        response = rest_api.put(f'{ROUTE_URL}/multiple', json=[listed[0], listed[1], listed[0]])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str([RC_ID_FOR_BULK]) in response.get_json()['message']

    def test_a_bool_public_id_is_refused_and_writes_nothing(self, rest_api, listed, database_manager,
                                                            database_name: str) -> None:
        """True equals the id 1 in Python but not in MongoDB - refused, not a silent no-op success"""
        before = self._stored(database_manager, database_name)

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=[listed[0], {**listed[1], 'public_id': True}])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'].endswith('item #2 has no integer public_id')
        assert self._stored(database_manager, database_name) == before

    def test_more_items_than_there_can_be_classes_are_refused(self, rest_api) -> None:
        """A list longer than MAX_ISMS_RISK_CLASSES cannot be a reorder"""
        payload = [_risk_class_payload(public_id) for public_id in [*LIMIT_RC_IDS, LIMIT_EXTRA_ID]]

        response = rest_api.put(f'{ROUTE_URL}/multiple', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == (
            f'At most {MAX_ISMS_RISK_CLASSES} RiskClasses can be updated at once, but {len(payload)} were sent!'
        )

    def test_a_body_that_is_not_a_list_is_refused(self, rest_api) -> None:
        """Named with the real plural"""
        response = rest_api.put(f'{ROUTE_URL}/multiple', json={'public_id': RC_ID_FOR_BULK})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == 'The request body must be a list of RiskClasses!'


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


    def test_insert_created_not_retrievable_returns_500(self, rest_api, monkeypatch) -> None:
        """A created item the server cannot read back is its own fault: 500, not a 404."""
        monkeypatch.setattr(RiskClassManager, 'insert_item', lambda *_a, **_k: RC_ID_FOR_GET)
        monkeypatch.setattr(RiskClassManager, 'get_item', lambda *_a, **_k: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_risk_class_payload(RC_ID_FOR_GET))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == manager_error_message(
            RISK_CLASS_LABEL, IsmsManagerErrorMessage.GET_CREATED,
        )

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
