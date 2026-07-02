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
Functional smoke for the ``/person_groups`` REST routes

Covers the route-layer concerns on top of the PersonGroupsManager integration suite: HTTP status
codes, schema validation, the GET envelopes, the 404 on a missing id, the manager-error -> 400
mapping, and the reciprocal member sync on update (including the remove-a-member regression that
used to crash with 'CmdbPersonGroup not subscriptable'). The routes are ISMS-license gated, so the
license check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.errors.manager.person_groups_manager import (
    PersonGroupsManagerInsertError,
    PersonGroupsManagerGetError,
    PersonGroupsManagerUpdateError,
    PersonGroupsManagerDeleteError,
    PersonGroupsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/person_groups'

GROUP_ID_FOR_GET: int = 96601
GROUP_ID_FOR_UPDATE: int = 96602
GROUP_ID_FOR_DELETE: int = 96603
MISSING_GROUP_ID: int = 96699

PERSON_ID_A: int = 96701
PERSON_ID_B: int = 96702

ALL_GROUP_IDS: list[int] = [GROUP_ID_FOR_GET, GROUP_ID_FOR_UPDATE, GROUP_ID_FOR_DELETE]
ALL_PERSON_IDS: list[int] = [PERSON_ID_A, PERSON_ID_B]


def _group_payload(public_id: int, group_members: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbPersonGroup body accepted by POST /person_groups/ and PUT /person_groups/<id>."""
    return {
        'public_id': public_id,
        'name': f'Group {public_id}',
        'email': '',
        'group_members': group_members if group_members is not None else [],
    }


def _group_doc(public_id: int, group_members: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbPersonGroup doc for direct insertion, bypassing POST schema validation."""
    return _group_payload(public_id, group_members)


def _person_doc(public_id: int, groups: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbPerson doc for direct insertion."""
    return {
        'public_id': public_id,
        'display_name': f'Person {public_id}',
        'first_name': 'First',
        'last_name': 'Last',
        'groups': groups if groups is not None else [],
    }


@pytest.fixture(autouse=True)
def _enable_isms_feature(monkeypatch: pytest.MonkeyPatch):
    """Stubs the license check so the ISMS-gated /person_groups routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any groups / persons seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_PERSON_IDS}})

    _purge()
    yield
    _purge()


def _insert_group(database_manager: MongoDatabaseManager, database_name: str,
                  public_id: int, group_members: list[int] | None = None) -> None:
    """Inserts a CmdbPersonGroup doc directly via the collection."""
    database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
        .insert_one(_group_doc(public_id, group_members))


def _insert_person(database_manager: MongoDatabaseManager, database_name: str,
                   public_id: int, groups: list[int] | None = None) -> None:
    """Inserts a CmdbPerson doc directly via the collection."""
    database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_one(_person_doc(public_id, groups))


def _person_groups(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[int]:
    """Returns the stored 'groups' of a CmdbPerson."""
    return database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
        .find_one({'public_id': public_id})['groups']


class TestPostPersonGroup:
    """POST /person_groups/ creates a CmdbPersonGroup."""

    def test_creates_group(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with a fresh id succeeds and the group becomes retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_group_payload(GROUP_ID_FOR_GET))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created_id = response.get_json()['raw']['public_id']
        assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK

    def test_invalid_payload_returns_400(self, rest_api) -> None:
        """A POST missing the required name fails schema validation with 400."""
        response = rest_api.post(f'{ROUTE_URL}/', json={'email': ''})

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGetPersonGroup:
    """GET /person_groups/<id> and GET /person_groups/ return the expected envelopes."""

    def test_get_single_returns_group(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching group."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == GROUP_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_GROUP_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /person_groups/ returns a results envelope whose length matches X-Total-Count."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestPutPersonGroup:
    """PUT /person_groups/<id> writes the new payload and syncs reciprocal person membership."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, GET reflects the updated name."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_UPDATE)
        payload = _group_payload(GROUP_ID_FOR_UPDATE)
        payload['name'] = 'Renamed'

        response = rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}').get_json()['result']['name'] == 'Renamed'

    def test_removing_a_member_syncs_membership(self, rest_api,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Dropping a member on update pulls the group out of that person (regression: used to 500)."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_UPDATE,
                      group_members=[PERSON_ID_A, PERSON_ID_B])
        _insert_person(database_manager, database_name, PERSON_ID_A, groups=[GROUP_ID_FOR_UPDATE])
        _insert_person(database_manager, database_name, PERSON_ID_B, groups=[GROUP_ID_FOR_UPDATE])

        response = rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                                json=_group_payload(GROUP_ID_FOR_UPDATE, group_members=[PERSON_ID_A]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _person_groups(database_manager, database_name, PERSON_ID_A) == [GROUP_ID_FOR_UPDATE]
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == []

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent group returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_GROUP_ID}', json=_group_payload(MISSING_GROUP_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestDeletePersonGroup:
    """DELETE /person_groups/<id> removes the group."""

    def test_delete_removes_group(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent group returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_GROUP_ID}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonGroupsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(PersonGroupsManager, 'insert_item', _raiser(PersonGroupsManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_group_payload(GROUP_ID_FOR_GET))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonGroupsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(PersonGroupsManager, 'iterate_items', _raiser(PersonGroupsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A PersonGroupsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(PersonGroupsManager, 'get_item', _raiser(PersonGroupsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PersonGroupsManagerUpdateError (group found) surfaces as 400."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_UPDATE)
        monkeypatch.setattr(PersonGroupsManager, 'update_item', _raiser(PersonGroupsManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}', json=_group_payload(GROUP_ID_FOR_UPDATE))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PersonGroupsManagerDeleteError (group found) surfaces as 400."""
        _insert_group(database_manager, database_name, GROUP_ID_FOR_DELETE)
        monkeypatch.setattr(PersonGroupsManager, 'delete_with_follow_up',
                            _raiser(PersonGroupsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
