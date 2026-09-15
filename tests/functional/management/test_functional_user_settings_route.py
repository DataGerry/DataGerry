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
Functional smoke for the ``/users/<user_id>/settings`` REST routes

Covers CRUD, the GET envelopes, the 404s, the manager-error -> 400 / -> 500 mappings, and the
route-layer fixes: the owning user_id is pinned from the URL on create/update (a mismatched body
cannot store under another user), the update existence-check + resource are keyed on the URL, the
PUT upsert (create-if-absent), and the duplicate-create -> 400 mapping. UserSettings are keyed by a
unique (resource, user_id) pair (no public_id).
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerInsertError,
    UserSettingsManagerGetError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
    UserSettingsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 96601
OTHER_USER_ID: int = 96602

RESOURCE_A: str = 'dashboard'
RESOURCE_B: str = 'sidebar'
MISSING_RESOURCE: str = 'does-not-exist'

ALL_USER_IDS: list[int] = [USER_ID, OTHER_USER_ID]


def _settings_url(user_id: int = USER_ID) -> str:
    """Base URL for a user's settings collection."""
    return f'/users/{user_id}/settings'


def _setting_payload(
        resource: str,
        user_id: int = USER_ID,
        setting_type: str = 'GLOBAL',
        payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a CmdbUserSetting body accepted by POST / PUT (all required schema fields present)."""
    return {
        'resource': resource,
        'user_id': user_id,
        'payloads': [] if payloads is None else payloads,
        'setting_type': setting_type,
    }


# What the Angular table service really stores under a resource
TABLE_PAYLOADS: list[dict[str, Any]] = [
    {'id': 'objects-table', 'columns': ['public_id', 'name'], 'page_size': 25},
]


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any user settings seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    yield
    _purge()


class TestPostUserSetting:
    """POST /users/<user_id>/settings/ creates a setting."""

    def test_creates_setting(self, rest_api) -> None:
        """A POST with a valid body succeeds and the setting becomes retrievable."""
        response = rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK

    def test_missing_required_field_returns_400(self, rest_api) -> None:
        """A POST missing the required setting_type fails schema validation with 400."""
        payload = _setting_payload(RESOURCE_A)
        payload.pop('setting_type')

        assert rest_api.post(f'{_settings_url()}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_returns_400(self, rest_api) -> None:
        """Creating a second setting for the same (resource, user_id) is rejected with 400."""
        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_pins_user_id_from_url(self, rest_api) -> None:
        """A body user_id different from the URL is overridden by the URL user_id."""
        payload = _setting_payload(RESOURCE_A, user_id=OTHER_USER_ID)

        assert rest_api.post(f'{_settings_url(USER_ID)}/', json=payload).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = rest_api.get(f'{_settings_url(USER_ID)}/{RESOURCE_A}').get_json()['result']
        assert stored['user_id'] == USER_ID
        # the setting is not visible under the body's user_id
        assert rest_api.get(f'{_settings_url(OTHER_USER_ID)}/{RESOURCE_A}').status_code == HTTPStatus.NOT_FOUND


class TestGetUserSetting:
    """GET single + GET list."""

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /users/<id>/settings/ returns a results envelope containing the created settings."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        response = rest_api.get(f'{_settings_url()}/')

        assert response.status_code == HTTPStatus.OK
        resources = [item['resource'] for item in response.get_json()['results']]
        assert RESOURCE_A in resources

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing resource returns 404."""
        assert rest_api.get(f'{_settings_url()}/{MISSING_RESOURCE}').status_code == HTTPStatus.NOT_FOUND


class TestPutUserSetting:
    """PUT /users/<user_id>/settings/<resource> upserts a setting."""

    def test_creates_when_absent(self, rest_api) -> None:
        """PUT on a non-existent resource creates it."""
        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK

    def test_updates_when_present(self, rest_api) -> None:
        """PUT on an existing resource updates it (setting_type GLOBAL -> SERVER)."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, setting_type='GLOBAL'))

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}',
                                json=_setting_payload(RESOURCE_A, setting_type='SERVER'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').get_json()['result']['setting_type'] == 'SERVER'

    def test_pins_resource_from_url(self, rest_api) -> None:
        """A body resource different from the URL is overridden by the URL resource."""
        payload = _setting_payload(RESOURCE_B)  # body says RESOURCE_B ...

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=payload)  # ... URL says RESOURCE_A

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_B}').status_code == HTTPStatus.NOT_FOUND


class TestDeleteUserSetting:
    """DELETE /users/<user_id>/settings/<resource>."""

    def test_delete_removes_setting(self, rest_api) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        response = rest_api.delete(f'{_settings_url()}/{RESOURCE_A}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent resource returns 404."""
        assert rest_api.delete(f'{_settings_url()}/{MISSING_RESOURCE}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'insert_item',
                            _raiser(UserSettingsManagerInsertError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    # The "created setting could not be re-read -> 404" case is gone with the read itself: the create
    # route answers the body it just wrote plus the public_id the insert returned, so there is no
    # second query that could come back empty (2026-09-09)

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_settings',
                            _raiser(UserSettingsManagerIterationError('boom')))

        assert rest_api.get(f'{_settings_url()}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_settings', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{_settings_url()}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A UserSettingsManagerUpdateError (setting present) surfaces as 400."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'update_user_setting',
                            _raiser(UserSettingsManagerUpdateError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on update surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_keeps_a_nested_refusal_as_it_is(self, rest_api, monkeypatch) -> None:
        """
        An HTTPException raised underneath the update route is re-raised, not turned into a 500

        The route has no `abort()` of its own left, so this arm is only reachable when something it
        calls refuses - and a refusal must keep its status and its message. FORBIDDEN because
        `init_rest_api` registers a JSON handler for it; a status it does not register answers Flask's
        HTML page instead of the API error envelope - discussion-backlog #155.
        """
        def _refuse(*_args: Any, **_kwargs: Any) -> None:
            abort(HTTPStatus.FORBIDDEN, 'nested refusal')

        monkeypatch.setattr(UserSettingsManager, 'insert_item', _refuse)

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A))

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert 'nested refusal' in response.get_json()['message']

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A UserSettingsManagerDeleteError (setting present) surfaces as 400."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'delete_user_setting',
                            _raiser(UserSettingsManagerDeleteError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An unexpected error on delete surfaces as 500."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'delete_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError during the create's duplicate/re-read check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on the update existence-check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerInsertError on the update create-path surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', lambda *_a, **_k: None)
        monkeypatch.setattr(UserSettingsManager, 'insert_item',
                            _raiser(UserSettingsManagerInsertError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on the delete existence-check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                            what a setting stores                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPayloadContent:
    """The payload entries are the client's own structures and travel unchanged.

    Every fixture in this suite used to send `payloads: []`, so nothing ever asserted what a setting
    actually stores - which is how the wrapper class that used to sit in the model (a dict in, the same
    dict out) reached 2026-09-09 without a single line of it ever executing.
    """

    def test_a_stored_payload_comes_back_verbatim_from_the_single_read(self, rest_api) -> None:
        """Nested lists and ints included - the backend attaches no meaning to any of it"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, payloads=TABLE_PAYLOADS))

        answered = rest_api.get(f'{_settings_url()}/{RESOURCE_A}').get_json()['result']

        assert answered['payloads'] == TABLE_PAYLOADS

    def test_a_stored_payload_comes_back_verbatim_from_the_list_read(self, rest_api) -> None:
        """The read the frontend syncs from on login"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, payloads=TABLE_PAYLOADS))

        results = rest_api.get(f'{_settings_url()}/').get_json()['results']

        assert results[0]['payloads'] == TABLE_PAYLOADS

    def test_a_payload_list_of_scalars_is_refused(self, rest_api) -> None:
        """Each entry is an object; a list of scalars is a client bug, not a stored setting"""
        response = rest_api.post(f'{_settings_url()}/',
                                 json=_setting_payload(RESOURCE_A, payloads=['nope']))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_updated_payload_replaces_the_stored_one(self, rest_api) -> None:
        """The write path is a full document (DataGerry has no partial update here)"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, payloads=TABLE_PAYLOADS))
        rest_api.put(f'{_settings_url()}/{RESOURCE_A}',
                     json=_setting_payload(RESOURCE_A, payloads=[{'id': 'other'}]))

        answered = rest_api.get(f'{_settings_url()}/{RESOURCE_A}').get_json()['result']

        assert answered['payloads'] == [{'id': 'other'}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the scope, and an unreadable record                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSettingTypeGuard:
    """A scope outside UserSettingType is refused on write and skipped on read.

    Before 2026-09-09 it was accepted on write (the schema typed it as a plain string) and then made
    the WHOLE settings list of that user unreadable, because the read resolved every document's scope
    and one failure failed the call. The frontend syncs that read on login and only logs a failure, so
    the symptom was table and dashboard state silently never being restored.
    """

    @pytest.mark.parametrize('setting_type', ['NOT_A_TYPE', 'global', ''],
                             ids=['unknown', 'wrong-case', 'empty'])
    def test_a_scope_outside_the_enum_is_refused_on_create(self, rest_api, setting_type: str) -> None:
        """The door: only the three UserSettingType values are accepted"""
        response = rest_api.post(f'{_settings_url()}/',
                                 json=_setting_payload(RESOURCE_A, setting_type=setting_type))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_scope_outside_the_enum_is_refused_on_update(self, rest_api) -> None:
        """Both write routes run the same schema"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}',
                                json=_setting_payload(RESOURCE_A, setting_type='NOT_A_TYPE'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('setting_type', ['GLOBAL', 'APPLICATION', 'SERVER'])
    def test_each_valid_scope_is_accepted(self, rest_api, setting_type: str) -> None:
        """The guard may not narrow what the product actually uses"""
        response = rest_api.post(f'{_settings_url()}/',
                                 json=_setting_payload(RESOURCE_A, setting_type=setting_type))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_an_already_stored_bad_record_no_longer_breaks_the_list(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The rescue half: an installation that already holds such a document keeps its other settings

        The bad record is written straight into the collection, because the API refuses it now.
        """
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, payloads=TABLE_PAYLOADS))
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_B, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'NOT_A_TYPE',
             'public_id': 9001},
        )

        response = rest_api.get(f'{_settings_url()}/')

        assert response.status_code == HTTPStatus.OK
        results = response.get_json()['results']
        assert [setting['resource'] for setting in results] == [RESOURCE_A]
        assert results[0]['payloads'] == TABLE_PAYLOADS

    def test_the_bad_record_itself_is_still_addressable(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The single read answers the stored document, so the record can be inspected and repaired"""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_B, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'NOT_A_TYPE',
             'public_id': 9002},
        )

        answered = rest_api.get(f'{_settings_url()}/{RESOURCE_B}')

        assert answered.status_code == HTTPStatus.OK
        assert answered.get_json()['result']['setting_type'] == 'NOT_A_TYPE'

    def test_a_repaired_record_appears_in_the_list_again(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The way out: overwrite the record through the API, which now validates the scope"""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_B, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'NOT_A_TYPE',
             'public_id': 9003},
        )

        rest_api.put(f'{_settings_url()}/{RESOURCE_B}', json=_setting_payload(RESOURCE_B))

        results = rest_api.get(f'{_settings_url()}/').get_json()['results']

        assert [setting['resource'] for setting in results] == [RESOURCE_B]


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the two reads, as they answer today                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadShapes:
    """The single read answers the stored document, the list read the four normalised keys.

    Pinned as it is, NOT as it should be: which shape both reads should answer - and whether a user
    setting has a public_id in its API shape at all - is discussion-backlog #218. These tests are what
    makes that decision visible when it is taken.
    """

    def test_the_single_read_carries_the_stamped_public_id(self, rest_api) -> None:
        """The manager stamps one on insert although the model does not declare it"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        assert 'public_id' in rest_api.get(f'{_settings_url()}/{RESOURCE_A}').get_json()['result']

    def test_the_list_read_does_not(self, rest_api) -> None:
        """The four normalised keys only - which is what the Angular UserSetting model declares"""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        listed = rest_api.get(f'{_settings_url()}/').get_json()['results'][0]

        assert set(listed) == {'resource', 'user_id', 'payloads', 'setting_type'}

    def test_the_create_answers_the_stored_document_with_its_new_id(self, rest_api) -> None:
        """Answered from the body that was just written plus the insert's id - no second read"""
        created = rest_api.post(f'{_settings_url()}/',
                                json=_setting_payload(RESOURCE_A, payloads=TABLE_PAYLOADS)).get_json()

        assert created['raw']['payloads'] == TABLE_PAYLOADS
        assert created['raw']['public_id'] == created['result_id']

    def test_a_setting_without_payloads_is_listed_with_an_empty_list(self, rest_api) -> None:
        """The key is optional on write; a client reads `payloads` unconditionally"""
        body = _setting_payload(RESOURCE_A)
        del body['payloads']
        rest_api.post(f'{_settings_url()}/', json=body)

        assert rest_api.get(f'{_settings_url()}/').get_json()['results'][0]['payloads'] == []
