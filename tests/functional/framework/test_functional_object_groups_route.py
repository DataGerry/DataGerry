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
Functional smoke for the ``/object_groups`` REST routes.

Covers CRUD, the GET envelopes, the 404 guards, the manager-error -> 400 / -> 500 mappings, the
``public_id`` pinned from the URL on update (a forged body public_id cannot rewrite the document's
identity), the update answering the stored document, and the empty group: legal on POST and PUT, and
still editable after the object-delete or type-delete cascade removed its last member.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectGroupMode
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.object_groups_manager import (
    ObjectGroupsManagerInsertError,
    ObjectGroupsManagerGetError,
    ObjectGroupsManagerUpdateError,
    ObjectGroupsManagerDeleteError,
    ObjectGroupsManagerIterationError,
)
from tests.utils.update_response import put_and_read_back
from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 95701
OTHER_GROUP_ID: int = 95702
MISSING_GROUP_ID: int = 95799

ALL_GROUP_IDS: list[int] = [GROUP_ID, OTHER_GROUP_ID]

# The member a cascade test deletes out from under its group
MEMBER_TYPE_ID: int = 95711
MEMBER_OBJECT_ID: int = 95712

OBJECT_GROUPS_URL: str = '/object_groups'


def _payload(name: str = 'Servers', assigned_ids: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbObjectGroup body accepted by POST / PUT (all required schema fields present)."""
    return {
        'name': name,
        'group_type': ObjectGroupMode.STATIC,
        'assigned_ids': assigned_ids if assigned_ids is not None else [1, 2],
        'categories': [],
    }


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the ISMS-gated /object_groups routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any object groups seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})

    _purge()
    yield
    _purge()


def _create(rest_api, name: str = 'Servers') -> int:
    """Creates an object group via the API and returns its public_id."""
    response = rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload(name))
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    return response.get_json()['raw']['public_id']


class TestPostObjectGroup:
    """POST /object_groups/ creates an object group."""

    def test_creates_group(self, rest_api) -> None:
        """A POST with a valid body succeeds and the group becomes retrievable."""
        new_id = _create(rest_api)

        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{new_id}').status_code == HTTPStatus.OK

    def test_missing_required_field_returns_400(self, rest_api) -> None:
        """A POST missing the required name fails schema validation with 400."""
        payload = _payload()
        payload.pop('name')

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST


class TestGetObjectGroup:
    """GET single + GET list."""

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /object_groups/ returns a results envelope containing the created group."""
        _create(rest_api, name='Alpha')

        response = rest_api.get(f'{OBJECT_GROUPS_URL}/')

        assert response.status_code == HTTPStatus.OK
        names = [item['name'] for item in response.get_json()['results']]
        assert 'Alpha' in names

    def test_get_single_success(self, rest_api) -> None:
        """A GET for an existing group returns it in the result envelope."""
        new_id = _create(rest_api)

        response = rest_api.get(f'{OBJECT_GROUPS_URL}/{new_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == new_id

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing group returns 404."""
        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{MISSING_GROUP_ID}').status_code == HTTPStatus.NOT_FOUND


class TestPutObjectGroup:
    """PUT /object_groups/<public_id> updates a group."""

    def test_updates_group(self, rest_api) -> None:
        """A PUT on an existing group updates its name."""
        new_id = _create(rest_api, name='Before')

        response = rest_api.put(f'{OBJECT_GROUPS_URL}/{new_id}', json=_payload(name='After'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{new_id}').get_json()['result']['name'] == 'After'

    def test_missing_returns_404(self, rest_api) -> None:
        """A PUT on a non-existent group returns 404."""
        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{MISSING_GROUP_ID}', json=_payload()).status_code \
            == HTTPStatus.NOT_FOUND

    def test_pins_public_id_from_url(self, rest_api) -> None:
        """A body public_id different from the URL cannot rewrite the document's identity."""
        new_id = _create(rest_api)
        payload = _payload(name='Renamed')
        payload['public_id'] = OTHER_GROUP_ID  # forged id in the body ...

        response = rest_api.put(f'{OBJECT_GROUPS_URL}/{new_id}', json=payload)  # ... URL says new_id

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        stored = rest_api.get(f'{OBJECT_GROUPS_URL}/{new_id}').get_json()['result']
        assert stored['public_id'] == new_id
        # nothing was written under the forged body id
        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{OTHER_GROUP_ID}').status_code == HTTPStatus.NOT_FOUND


class TestDeleteObjectGroup:
    """DELETE /object_groups/<public_id>."""

    def test_delete_removes_group(self, rest_api) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        new_id = _create(rest_api)

        response = rest_api.delete(f'{OBJECT_GROUPS_URL}/{new_id}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{new_id}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent group returns 404."""
        assert rest_api.delete(f'{OBJECT_GROUPS_URL}/{MISSING_GROUP_ID}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _seed_group(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Seeds a minimal CmdbObjectGroup document so existence-checked routes reach the manager call."""
    database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name).insert_one({
        'public_id': public_id,
        'name': f'Group-{public_id}',
        'group_type': ObjectGroupMode.STATIC,
        'assigned_ids': [1],
        'categories': [],
    })


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'insert_item',
                            _raiser(ObjectGroupsManagerInsertError('boom')))

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created group cannot be re-read, the route returns 404."""
        monkeypatch.setattr(ObjectGroupsManager, 'insert_item', lambda *_a, **_k: GROUP_ID)
        monkeypatch.setattr(ObjectGroupsManager, 'get_item', lambda *_a, **_k: None)

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload()).status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerGetError during the create re-read surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'insert_item', lambda *_a, **_k: GROUP_ID)
        monkeypatch.setattr(ObjectGroupsManager, 'get_item',
                            _raiser(ObjectGroupsManagerGetError('boom')))

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(ObjectGroupsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'iterate_items',
                            _raiser(ObjectGroupsManagerIterationError('boom')))

        assert rest_api.get(f'{OBJECT_GROUPS_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(ObjectGroupsManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{OBJECT_GROUPS_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'get_item',
                            _raiser(ObjectGroupsManagerGetError('boom')))

        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(ObjectGroupsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ObjectGroupsManagerUpdateError (group present) surfaces as 400."""
        _seed_group(database_manager, database_name, GROUP_ID)
        monkeypatch.setattr(ObjectGroupsManager, 'update_item',
                            _raiser(ObjectGroupsManagerUpdateError('boom')))

        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{GROUP_ID}', json=_payload()).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerGetError on the update existence-check surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'get_item',
                            _raiser(ObjectGroupsManagerGetError('boom')))

        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{GROUP_ID}', json=_payload()).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on update surfaces as 500."""
        monkeypatch.setattr(ObjectGroupsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{GROUP_ID}', json=_payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ObjectGroupsManagerDeleteError (group present) surfaces as 400."""
        _seed_group(database_manager, database_name, GROUP_ID)
        monkeypatch.setattr(ObjectGroupsManager, 'delete_with_follow_up',
                            _raiser(ObjectGroupsManagerDeleteError('boom')))

        assert rest_api.delete(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectGroupsManagerGetError on the delete existence-check surfaces as 400."""
        monkeypatch.setattr(ObjectGroupsManager, 'get_item',
                            _raiser(ObjectGroupsManagerGetError('boom')))

        assert rest_api.delete(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """An unexpected error on delete surfaces as 500."""
        _seed_group(database_manager, database_name, GROUP_ID)
        monkeypatch.setattr(ObjectGroupsManager, 'delete_with_follow_up', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR


class TestGroupTypeIsConstrained:
    """The mode decides which cleanup maintains the group, so a third value is refused."""

    def test_a_third_group_type_is_refused_on_create(self, rest_api) -> None:
        """
        A group outside STATIC / DYNAMIC is maintained by neither cleanup path

        Deleting objects pulls their ids out of the STATIC groups and deleting a type out of the
        DYNAMIC ones, so such a group keeps ids pointing at documents that no longer exist, forever.
        """
        payload = _payload()
        payload['group_type'] = 'SOMETHING_ELSE'

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_a_third_group_type_is_refused_on_update(self, rest_api) -> None:
        """The same rule on the update path: an existing group cannot be moved out of the two modes."""
        new_id: int = _create(rest_api)
        payload = _payload(name='Renamed')
        payload['group_type'] = 'SOMETHING_ELSE'

        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{new_id}', json=payload).status_code \
            == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('mode', list(ObjectGroupMode), ids=lambda mode: mode.value)
    def test_both_modes_are_accepted(self, rest_api, mode: ObjectGroupMode) -> None:
        """Neither of the two real modes was caught by the new rule."""
        payload = _payload(name=f'Group {mode.value}')
        payload['group_type'] = mode.value

        assert rest_api.post(f'{OBJECT_GROUPS_URL}/', json=payload).status_code in (
            HTTPStatus.OK, HTTPStatus.CREATED,
        )


class TestTheDocumentTheApiHandsOutCanBeSentBack:
    """The GET-then-PUT round trip, over HTTP."""

    def test_a_group_created_without_categories_round_trips(self, rest_api) -> None:
        """
        Create without the optional key, read, put it straight back

        The client has no partial update, so the document the API hands out has to be one it accepts.
        """
        created = rest_api.post(f'{OBJECT_GROUPS_URL}/', json={
            'name': 'Round Trip',
            'group_type': ObjectGroupMode.STATIC,
            'assigned_ids': [1],
        })

        assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        public_id: int = created.get_json()['raw']['public_id']
        fetched = rest_api.get(f'{OBJECT_GROUPS_URL}/{public_id}').get_json()['result']

        assert fetched['categories'] == []
        assert rest_api.put(f'{OBJECT_GROUPS_URL}/{public_id}', json=fetched).status_code in (
            HTTPStatus.OK, HTTPStatus.ACCEPTED,
        )

    def test_an_empty_assigned_ids_list_is_accepted(self, rest_api) -> None:
        """A group with no members yet is a valid group - the cascades produce exactly that document."""
        response = rest_api.post(f'{OBJECT_GROUPS_URL}/', json=_payload(assigned_ids=[]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        rest_api.delete(f'{OBJECT_GROUPS_URL}/{response.get_json()["raw"]["public_id"]}')

    def test_a_missing_assigned_ids_is_still_refused_and_named(self, rest_api) -> None:
        """
        Empty is legal, absent is not: the key stays required, and the 400 says which key

        It is the one list key that is neither nullable nor defaulted, so a document that lost it is
        refused rather than read as an empty group.
        """
        payload = _payload()
        payload.pop('assigned_ids')

        response = rest_api.post(f'{OBJECT_GROUPS_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == 'Invalid data provided: assigned_ids: required field'


class TestTheUpdateAnswersTheStoredDocument:
    """PUT /object_groups/<id> answers the ObjectGroup as stored, not the request body."""

    def test_omitted_categories_come_back_as_stored(self, rest_api) -> None:
        """categories left out of the body is stored as [] - and answered as []."""
        new_id = _create(rest_api)
        payload = _payload(name='After')
        payload.pop('categories')

        result, stored = put_and_read_back(rest_api, f'{OBJECT_GROUPS_URL}/{new_id}', payload)

        assert result == stored
        assert result['categories'] == []

    def test_null_categories_come_back_as_stored(self, rest_api) -> None:
        """categories sent as null is stored as [], and the response says so."""
        new_id = _create(rest_api)

        result, stored = put_and_read_back(
            rest_api, f'{OBJECT_GROUPS_URL}/{new_id}', {**_payload(name='After'), 'categories': None},
        )

        assert result == stored
        assert result['categories'] == []


class TestAGroupEmptiedByACascadeStaysEditable:
    """
    Deleting a group's last member empties it without anyone editing it - and it must stay savable

    Deleting a CmdbObject pulls it out of every STATIC group, deleting a CmdbType out of every DYNAMIC
    one. The group keeps its name, categories and risk assessments, so a read followed by a save has to
    work on the empty document that is left.
    """

    @pytest.fixture(autouse=True)
    def _member(self, database_manager: MongoDatabaseManager, database_name: str):
        """A type and one object of it, removed again afterwards."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(make_type_doc(MEMBER_TYPE_ID, 'object-group-member-type', None))
        objects.insert_one(make_object_doc(MEMBER_OBJECT_ID, MEMBER_TYPE_ID, []))

        yield

        objects.delete_many({'public_id': MEMBER_OBJECT_ID})
        types.delete_many({'public_id': MEMBER_TYPE_ID})

    @staticmethod
    def _seed(database_manager: MongoDatabaseManager, database_name: str, mode: ObjectGroupMode, member: int) -> None:
        """A group whose only member is ``member``."""
        database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name).insert_one({
            'public_id': GROUP_ID, 'name': 'Before', 'group_type': mode.value, 'assigned_ids': [member],
            'categories': [],
        })

    @staticmethod
    def _assert_round_trips(rest_api) -> None:
        """The emptied group reads back empty and saves back with a new name."""
        fetched = rest_api.get(f'{OBJECT_GROUPS_URL}/{GROUP_ID}').get_json()['result']
        assert fetched['assigned_ids'] == []

        result, stored = put_and_read_back(rest_api, f'{OBJECT_GROUPS_URL}/{GROUP_ID}', {**fetched, 'name': 'After'})

        assert result == stored
        assert (stored['name'], stored['assigned_ids']) == ('After', [])

    def test_a_static_group_emptied_by_an_object_delete(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """DELETE /objects/<last member> leaves an empty STATIC group that can still be edited."""
        self._seed(database_manager, database_name, ObjectGroupMode.STATIC, MEMBER_OBJECT_ID)

        assert rest_api.delete(f'/objects/{MEMBER_OBJECT_ID}').status_code == HTTPStatus.OK

        self._assert_round_trips(rest_api)

    def test_a_dynamic_group_emptied_by_a_type_delete(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """DELETE /types/<last member> leaves an empty DYNAMIC group that can still be edited."""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
            {'public_id': MEMBER_OBJECT_ID},
        )
        self._seed(database_manager, database_name, ObjectGroupMode.DYNAMIC, MEMBER_TYPE_ID)

        assert rest_api.delete(f'/types/{MEMBER_TYPE_ID}').status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        self._assert_round_trips(rest_api)

    def test_saving_a_group_empty_is_accepted_directly(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A user may also empty a group by hand - the same document, reached through the route."""
        self._seed(database_manager, database_name, ObjectGroupMode.STATIC, MEMBER_OBJECT_ID)

        result, stored = put_and_read_back(
            rest_api, f'{OBJECT_GROUPS_URL}/{GROUP_ID}', _payload(name='Emptied', assigned_ids=[]),
        )

        assert result == stored
        assert stored['assigned_ids'] == []
