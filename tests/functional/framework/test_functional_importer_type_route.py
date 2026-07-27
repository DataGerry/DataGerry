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
Functional coverage for the /import/type routes

Both verbs share a partial-report contract: every uploaded entry is processed independently and the
response body maps the failed entries to a diagnostic message, so one bad entry never discards the
rest of the batch. Covers create (add_type): types are inserted with server-assigned public_ids;
update (update_type): existing types are updated, an unknown public_id is reported instead of silently
succeeding, and an entry without a public_id is keyed by its position rather than raising; plus the
missing-upload and non-list-payload -> 400 guards on both verbs.
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

CREATE_URL: str = '/import/type/create/'
UPDATE_URL: str = '/import/type/update/'

ADMIN_PUBLIC_ID: int = 1  # the user the rest_api fixture authenticates as
FOREIGN_AUTHOR_ID: int = 777  # a user id from the system the type was exported from
FOREIGN_EDITOR_ID: int = 888
LOCAL_AUTHOR_ID: int = 5  # the author already stored on this system before an import update
CURRENT_YEAR: int = 2026

NEW_TYPE_NAME: str = 'imported-type-new'
SECOND_TYPE_NAME: str = 'imported-type-second'
UPDATE_TYPE_ID: int = 47411
MISSING_TYPE_ID: int = 47412
UPDATED_LABEL: str = 'imported-type-updated-label'

ALL_TYPE_IDS: list[int] = [UPDATE_TYPE_ID, MISSING_TYPE_ID]
ALL_TYPE_NAMES: list[str] = [NEW_TYPE_NAME, SECOND_TYPE_NAME]


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any types created / updated by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
            {'$or': [{'public_id': {'$in': ALL_TYPE_IDS}}, {'name': {'$in': ALL_TYPE_NAMES}}]}
        )

    _purge()
    yield
    _purge()


def _upload_form(types: list[Any]) -> dict[str, Any]:
    """Builds the form payload the import routes expect (a JSON list under 'uploadFile')."""
    return {'uploadFile': json.dumps(types, default=str)}


def _raw_upload_form(payload: Any) -> dict[str, Any]:
    """Builds an upload form around any payload, so a non-list body can be sent."""
    return {'uploadFile': json.dumps(payload, default=str)}


class TestAddType:
    """POST /import/type/create/ inserts uploaded types and collects per-type failures."""

    def test_creates_type(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid type upload is inserted and no errors are collected."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')  # the route assigns a fresh public_id

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored is not None

    def test_authorship_is_rewritten_onto_the_importer(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The importing user becomes the author; the source system's user ids are not carried over."""
        payload = make_type_doc(0, NEW_TYPE_NAME)
        payload.pop('public_id')
        payload['author_id'] = FOREIGN_AUTHOR_ID
        payload['editor_id'] = FOREIGN_EDITOR_ID
        payload['last_edit_time'] = '2020-01-01T00:00:00'

        response = rest_api.post(CREATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': NEW_TYPE_NAME})
        assert stored['author_id'] == ADMIN_PUBLIC_ID
        assert stored['editor_id'] is None
        assert stored['last_edit_time'] is None

    def test_invalid_entry_is_collected_not_aborted(self, rest_api) -> None:
        """An invalid type entry is recorded in the error collection instead of failing the request."""
        response = rest_api.post(CREATE_URL, data=_upload_form([{}]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1

    def test_error_message_carries_detail(self, rest_api) -> None:
        """A collected create failure names the reason, not just a generic sentence."""
        response = rest_api.post(CREATE_URL, data=_upload_form([{}]), content_type='multipart/form-data')

        (message,) = response.get_json().values()
        assert message.startswith('Failed to import this Type:')
        assert len(message) > len('Failed to import this Type:')

    def test_valid_entry_survives_an_invalid_sibling(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """One unusable entry does not stop the remaining entries of the batch from being inserted."""
        valid = make_type_doc(0, SECOND_TYPE_NAME)
        valid.pop('public_id')

        response = rest_api.post(
            CREATE_URL, data=_upload_form([{}, valid]), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'name': SECOND_TYPE_NAME})
        assert stored is not None

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """A create with no uploadFile is rejected with 400."""
        assert rest_api.post(CREATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_non_list_upload_returns_400(self, rest_api) -> None:
        """A single type object instead of a list is rejected with 400 rather than iterated by key."""
        assert rest_api.post(
            CREATE_URL, data=_raw_upload_form(make_type_doc(0, NEW_TYPE_NAME)), content_type='multipart/form-data'
        ).status_code == HTTPStatus.BAD_REQUEST


class TestUpdateType:
    """POST /import/type/update/ updates existing types from the upload."""

    def test_updates_existing_type(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An upload for an existing type applies the update."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['label'] == UPDATED_LABEL

    def test_importer_is_recorded_as_the_editor(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An update records the importer as the editor rather than re-attributing authorship."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['editor_id'] = FOREIGN_EDITOR_ID
        updated['last_edit_time'] = '2020-01-01T00:00:00'

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {}
        stored = types.find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['editor_id'] == ADMIN_PUBLIC_ID
        assert stored['last_edit_time'] is not None
        assert stored['last_edit_time'].year >= CURRENT_YEAR  # server-stamped, not the uploaded 2020

    def test_stored_author_and_creation_time_survive_the_update(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The uploaded author_id / creation_time never overwrite how the type came to exist here."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        seed = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        seed['author_id'] = LOCAL_AUTHOR_ID
        types.insert_one(seed)
        original_creation_time = types.find_one({'public_id': UPDATE_TYPE_ID})['creation_time']

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['author_id'] = FOREIGN_AUTHOR_ID
        updated['creation_time'] = '2020-01-01T00:00:00'
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(UPDATE_URL, data=_upload_form([updated]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        stored = types.find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['author_id'] == LOCAL_AUTHOR_ID          # not the uploaded FOREIGN_AUTHOR_ID
        assert stored['creation_time'] == original_creation_time
        assert stored['label'] == UPDATED_LABEL                # the rest of the type still replaced

    def test_unknown_public_id_is_reported(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Updating a type that does not exist is reported instead of silently succeeding."""
        payload = make_type_doc(MISSING_TYPE_ID, 'imported-type-missing')

        response = rest_api.post(UPDATE_URL, data=_upload_form([payload]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {
            str(MISSING_TYPE_ID): f'No Type with public_id {MISSING_TYPE_ID} exists, it can not be updated!'
        }
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': MISSING_TYPE_ID})
        assert stored is None  # the failed update must not have upserted the type

    def test_invalid_entry_is_collected_not_aborted(self, rest_api) -> None:
        """An entry that cannot be built into a type is collected, keyed by its position."""
        response = rest_api.post(UPDATE_URL, data=_upload_form([{}]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        (key, message), = response.get_json().items()
        assert key == 'entry_0'  # no public_id to key on - the position is used instead of raising
        assert message.startswith('Failed to create a Type instance from the provided data:')

    def test_valid_entry_survives_an_invalid_sibling(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """One unusable entry does not stop the remaining entries of the batch from being updated."""
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .insert_one(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update'))

        updated = make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')
        updated['label'] = UPDATED_LABEL

        response = rest_api.post(
            UPDATE_URL, data=_upload_form([{}, updated]), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.OK
        assert list(response.get_json()) == ['entry_0']
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': UPDATE_TYPE_ID})
        assert stored['label'] == UPDATED_LABEL

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """An update with no uploadFile is rejected with 400."""
        assert rest_api.post(UPDATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_non_list_upload_returns_400(self, rest_api) -> None:
        """A single type object instead of a list is rejected with 400 rather than iterated by key."""
        assert rest_api.post(
            UPDATE_URL,
            data=_raw_upload_form(make_type_doc(UPDATE_TYPE_ID, 'imported-type-update')),
            content_type='multipart/form-data',
        ).status_code == HTTPStatus.BAD_REQUEST
