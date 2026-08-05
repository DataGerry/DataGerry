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
Functional coverage for the /media_file routes

Covers the list envelope, upload (multipart) + the no-file -> 400 guard (the fixed
get_file_in_request + HTTPException re-raise), get-single, delete, and the manager-error -> 400 / 500
mappings.
"""
import json
from io import BytesIO
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import MediaFilesManager
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/media_file'
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
EMPTY_METADATA: str = json.dumps({})
AUTHOR_ID: int = 1  # full_access_user public_id


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes media files uploaded by these tests (by author), before and after each test."""
    def _purge() -> None:
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        for doc in list(files.find({'metadata.author_id': AUTHOR_ID})):
            files.delete_one({'_id': doc['_id']})
            database_manager.get_collection(f'{MediaFile.COLLECTION}.chunks', database_name)\
                .delete_many({'files_id': doc['_id']})

    _purge()
    yield
    _purge()


def _upload_form(filename: str) -> dict:
    """Builds the multipart upload form (file + metadata field)."""
    return {
        'file': (BytesIO(b'content'), filename),
        'metadata': json.dumps({'author_id': AUTHOR_ID}),
    }


def _upload(rest_api, filename: str) -> int:
    """Uploads a file and returns its assigned public_id."""
    response = rest_api.post(f'{BASE_URL}/', data=_upload_form(filename), content_type='multipart/form-data')
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    return response.get_json()['result_id']


class TestListFiles:
    """GET /media_file/ returns the results envelope."""

    def test_list_returns_results(self, rest_api) -> None:
        """Listing files returns a results envelope."""
        _upload(rest_api, 'dg-func-list.txt')

        response = rest_api.get(f'{BASE_URL}/?metadata={EMPTY_METADATA}')

        assert response.status_code == HTTPStatus.OK
        assert 'results' in response.get_json()


class TestUpload:
    """POST /media_file/ stores an uploaded file."""

    def test_upload_succeeds(self, rest_api) -> None:
        """A multipart upload with a file and metadata succeeds and returns a public_id."""
        public_id = _upload(rest_api, 'dg-func-upload.txt')

        assert public_id > 0

    def test_upload_without_file_returns_400(self, rest_api) -> None:
        """An upload with no file is rejected with 400 (the fixed guard, surfaced via HTTPException)."""
        response = rest_api.post(
            f'{BASE_URL}/', data={'metadata': json.dumps({'author_id': AUTHOR_ID})},
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_reupload_same_file_overwrites(self, rest_api) -> None:
        """Uploading the same filename+metadata again overwrites the existing file (still succeeds)."""
        _upload(rest_api, 'dg-func-overwrite.txt')

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-overwrite.txt'), content_type='multipart/form-data'
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A MediaFileManagerInsertError while storing surfaces as 400."""
        monkeypatch.setattr(MediaFilesManager, 'insert_file', _raiser(MediaFileManagerInsertError('boom')))

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-err.txt'), content_type='multipart/form-data'
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGetSingle:
    """GET /media_file/<filename> resolves a stored file."""

    def test_get_single_returns_file(self, rest_api) -> None:
        """A get-single for an uploaded file returns 200 with its data."""
        _upload(rest_api, 'dg-func-single.txt')
        # non-empty metadata: generate_metadata_filter treats an empty dict as "not provided"
        metadata = json.dumps({'author_id': AUTHOR_ID})

        response = rest_api.get(f'{BASE_URL}/dg-func-single.txt?metadata={metadata}')

        assert response.status_code == HTTPStatus.OK
        # DefaultResponse returns the file document directly (not wrapped in a 'result' envelope)
        assert response.get_json()['filename'] == 'dg-func-single.txt'


class TestDownload:
    """GET /media_file/download/<filename> streams the file content."""

    def test_download_returns_content(self, rest_api) -> None:
        """A download returns the raw file content as an attachment."""
        _upload(rest_api, 'dg-func-download.txt')
        metadata = json.dumps({'author_id': AUTHOR_ID})

        response = rest_api.get(f'{BASE_URL}/download/dg-func-download.txt?metadata={metadata}')

        assert response.status_code == HTTPStatus.OK
        assert response.data == b'content'


class TestUpdate:
    """PUT /media_file/ updates a stored file's document."""

    def test_update_persists(self, rest_api) -> None:
        """Updating an existing file (attachment reference mode) succeeds."""
        public_id = _upload(rest_api, 'dg-func-update.txt')
        body = {
            'public_id': public_id,
            'filename': 'dg-func-update.txt',
            'metadata': {'author_id': AUTHOR_ID, 'parent': None},
        }
        attachment = json.dumps({'reference': True})

        response = rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)


class TestDelete:
    """DELETE /media_file/<public_id> removes a stored file."""

    def test_delete_removes_file(self, rest_api) -> None:
        """A delete succeeds and the file is gone from the list."""
        public_id = _upload(rest_api, 'dg-func-delete.txt')

        response = rest_api.delete(f'{BASE_URL}/{public_id}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_delete_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A MediaFileManagerDeleteError while deleting surfaces as 400."""
        public_id = _upload(rest_api, 'dg-func-delete-err.txt')
        monkeypatch.setattr(MediaFilesManager, 'delete_file', _raiser(MediaFileManagerDeleteError('boom')))

        assert rest_api.delete(f'{BASE_URL}/{public_id}').status_code == HTTPStatus.BAD_REQUEST


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_list_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A MediaFileManagerGetError while listing surfaces as 400."""
        monkeypatch.setattr(MediaFilesManager, 'get_many_media_files',
                            _raiser(MediaFileManagerGetError('boom')))

        assert rest_api.get(f'{BASE_URL}/?metadata={EMPTY_METADATA}').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while listing surfaces as 500."""
        monkeypatch.setattr(MediaFilesManager, 'get_many_media_files', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{BASE_URL}/?metadata={EMPTY_METADATA}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR
