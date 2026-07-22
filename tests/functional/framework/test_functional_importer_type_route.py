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

Covers create (add_type): a JSON upload of new types is inserted (public_ids assigned server-side) and
an invalid entry is collected as an error rather than aborting the batch; update (update_type): an
existing type is updated from the upload; and the missing-upload -> 400 guard on both verbs.
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

NEW_TYPE_NAME: str = 'imported-type-new'
UPDATE_TYPE_ID: int = 47411
UPDATED_LABEL: str = 'imported-type-updated-label'

ALL_TYPE_IDS: list[int] = [UPDATE_TYPE_ID]
ALL_TYPE_NAMES: list[str] = [NEW_TYPE_NAME]


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


def _upload_form(types: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds the form payload the import routes expect (a JSON list under 'uploadFile')."""
    return {'uploadFile': json.dumps(types, default=str)}


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

    def test_invalid_entry_is_collected_not_aborted(self, rest_api) -> None:
        """An invalid type entry is recorded in the error collection instead of failing the request."""
        response = rest_api.post(CREATE_URL, data=_upload_form([{}]), content_type='multipart/form-data')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 1

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """A create with no uploadFile is rejected with 400."""
        assert rest_api.post(CREATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST


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

    def test_invalid_entry_returns_400(self, rest_api) -> None:
        """An update whose entry cannot be built into a type is rejected with 400."""
        assert rest_api.post(UPDATE_URL, data=_upload_form([{}]), content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_missing_upload_returns_400(self, rest_api) -> None:
        """An update with no uploadFile is rejected with 400."""
        assert rest_api.post(UPDATE_URL, data={}, content_type='multipart/form-data').status_code \
            == HTTPStatus.BAD_REQUEST
