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
Functional smoke for the ``/persons`` REST routes

Covers the route-layer concerns on top of the PersonsManager integration suite: HTTP status codes,
schema validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400 mapping, and
the reciprocal group-membership sync on update (including the remove-a-group regression that used to
crash with 'CmdbPerson not subscriptable').
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.errors.manager.persons_manager import (
    PersonsManagerInsertError,
    PersonsManagerGetError,
    PersonsManagerUpdateError,
    PersonsManagerDeleteError,
    PersonsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/persons'

PERSON_ID_FOR_GET: int = 96401
PERSON_ID_FOR_UPDATE: int = 96402
PERSON_ID_FOR_DELETE: int = 96403
MISSING_PERSON_ID: int = 96499

GROUP_ID_A: int = 96501
GROUP_ID_B: int = 96502

ALL_PERSON_IDS: list[int] = [PERSON_ID_FOR_GET, PERSON_ID_FOR_UPDATE, PERSON_ID_FOR_DELETE]
ALL_GROUP_IDS: list[int] = [GROUP_ID_A, GROUP_ID_B]


def _person_payload(public_id: int, groups: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbPerson body accepted by POST /persons/ and PUT /persons/<id>."""
    return {
        'public_id': public_id,
        'display_name': f'Person {public_id}',
        'first_name': 'First',
        'last_name': 'Last',
        'groups': groups if groups is not None else [],
    }


def _person_doc(public_id: int, groups: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbPerson doc for direct insertion, bypassing POST schema validation."""
    return _person_payload(public_id, groups)


def _group_doc(public_id: int, group_members: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbPersonGroup doc for direct insertion."""
    return {
        'public_id': public_id,
        'name': f'Group {public_id}',
        'email': '',
        'group_members': group_members if group_members is not None else [],
    }


@pytest.fixture(autouse=True)
def _enable_isms_feature(monkeypatch: pytest.MonkeyPatch):
    """Stubs the license check so the ISMS-gated /persons routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any persons / groups seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_PERSON_IDS}})
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})

    _purge()
    yield
    _purge()


def _insert_person(database_manager: MongoDatabaseManager, database_name: str,
                   public_id: int, groups: list[int] | None = None) -> None:
    """Inserts a CmdbPerson doc directly via the collection."""
    database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_one(_person_doc(public_id, groups))


def _insert_group(database_manager: MongoDatabaseManager, database_name: str,
                  public_id: int, group_members: list[int] | None = None) -> None:
    """Inserts a CmdbPersonGroup doc directly via the collection."""
    database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
        .insert_one(_group_doc(public_id, group_members))


def _group_members(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[int]:
    """Returns the stored 'group_members' of a CmdbPersonGroup."""
    return database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
        .find_one({'public_id': public_id})['group_members']


class TestPostPerson:
    """POST /persons/ creates a CmdbPerson."""

    def test_creates_person(self, rest_api) -> None:
        """A POST with a fresh id succeeds and the person becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_invalid_payload_returns_400(self, rest_api) -> None:
        """A POST missing required fields fails schema validation with 400."""
        response = rest_api.post(f'{ROUTE_URL}/', json={'first_name': 'NoDisplayName'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_with_groups_syncs_membership(self, rest_api,
                                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Creating a person with groups adds the person to those groups (reciprocal sync)."""
        _insert_group(database_manager, database_name, GROUP_ID_A)

        response = rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET, groups=[GROUP_ID_A]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert _group_members(database_manager, database_name, GROUP_ID_A) == [PERSON_ID_FOR_GET]

    def test_created_retrieval_missing_returns_404(self, rest_api, monkeypatch) -> None:
        """If the created person cannot be retrieved afterwards, the route returns 404."""
        monkeypatch.setattr(PersonsManager, 'get_item', lambda *_args, **_kwargs: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_insert_internal_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(PersonsManager, 'insert_item', _raiser(RuntimeError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestGetPerson:
    """GET /persons/<id> and GET /persons/ return the expected envelopes."""

    def test_get_single_returns_person(self, rest_api,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching person."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == PERSON_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_PERSON_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /persons/ returns a results envelope whose length matches X-Total-Count."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutPerson:
    """PUT /persons/<id> writes the new payload and syncs reciprocal group membership."""

    def test_update_persists_display_name(self, rest_api,
                                         database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated display_name."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_UPDATE)
        payload = _person_payload(PERSON_ID_FOR_UPDATE)
        payload['display_name'] = 'Renamed'

        response = rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}').get_json()['result']['display_name'] == 'Renamed'

    def test_removing_a_group_syncs_membership(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Dropping a group on update pulls the person out of that group (regression: used to 500)."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_UPDATE, groups=[GROUP_ID_A, GROUP_ID_B])
        _insert_group(database_manager, database_name, GROUP_ID_A, group_members=[PERSON_ID_FOR_UPDATE])
        _insert_group(database_manager, database_name, GROUP_ID_B, group_members=[PERSON_ID_FOR_UPDATE])

        response = rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}',
                                json=_person_payload(PERSON_ID_FOR_UPDATE, groups=[GROUP_ID_A]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _group_members(database_manager, database_name, GROUP_ID_A) == [PERSON_ID_FOR_UPDATE]
        assert _group_members(database_manager, database_name, GROUP_ID_B) == []

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent person returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_PERSON_ID}', json=_person_payload(MISSING_PERSON_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_public_id_pinned_to_url(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A body public_id different from the URL cannot rewrite the document identity."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_UPDATE)
        payload = _person_payload(PERSON_ID_FOR_UPDATE)
        payload['public_id'] = PERSON_ID_FOR_GET  # forged, different from the URL id

        response = rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        # the document keeps its URL id; nothing was written under the forged id
        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}').status_code == HTTPStatus.OK
        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_GET}').status_code == HTTPStatus.NOT_FOUND


class TestDeletePerson:
    """DELETE /persons/<id> removes the person."""

    def test_delete_removes_person(self, rest_api,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent person returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_PERSON_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_returns_deleted_person(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The delete response carries the deleted person (retrieved as a dict via as_dict=True)."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['raw']['public_id'] == PERSON_ID_FOR_DELETE


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'insert_item', _raiser(PersonsManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'iterate_items', _raiser(PersonsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'get_item', _raiser(PersonsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PersonsManagerUpdateError (person found) surfaces as 400."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_UPDATE)
        monkeypatch.setattr(PersonsManager, 'update_item', _raiser(PersonsManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}', json=_person_payload(PERSON_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PersonsManagerDeleteError (person found) surfaces as 400."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_DELETE)
        monkeypatch.setattr(PersonsManager, 'delete_with_follow_up', _raiser(PersonsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerGetError while retrieving the created person surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'get_item', _raiser(PersonsManagerGetError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_person_payload(PERSON_ID_FOR_GET)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerGetError while loading the person to update surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'get_item', _raiser(PersonsManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}',
                            json=_person_payload(PERSON_ID_FOR_UPDATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonsManagerGetError while loading the person to delete surfaces as 400."""
        monkeypatch.setattr(PersonsManager, 'get_item', _raiser(PersonsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_list_internal_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(PersonsManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_internal_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(PersonsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{PERSON_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_internal_error_returns_500(self, rest_api, monkeypatch,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An unexpected error on update surfaces as 500."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_UPDATE)
        monkeypatch.setattr(PersonsManager, 'update_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{PERSON_ID_FOR_UPDATE}',
                            json=_person_payload(PERSON_ID_FOR_UPDATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_internal_error_returns_500(self, rest_api, monkeypatch,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An unexpected error on delete surfaces as 500."""
        _insert_person(database_manager, database_name, PERSON_ID_FOR_DELETE)
        monkeypatch.setattr(PersonsManager, 'delete_with_follow_up', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{PERSON_ID_FOR_DELETE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR
