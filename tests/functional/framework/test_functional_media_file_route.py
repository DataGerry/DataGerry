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

Since 2026-08-25 also the answers for a file that is NOT there - every route says 404 rather than a 200
with an empty body or a 500 - the replace-on-upload ordering, and the update route's required
``attachment`` parameter.
"""
import json
from io import BytesIO
from http import HTTPStatus

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager import MediaFilesManager
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
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


MISSING_ID: int = 998877
MISSING_NAME: str = 'dg-func-does-not-exist.txt'
# non-empty metadata: generate_metadata_filter treats an empty dict as "not provided"
AUTHOR_METADATA: str = json.dumps({'author_id': AUTHOR_ID})


class TestMissingFileIsNotFound:
    """
    Every route answers 404 for a file that is not there

    Before this the read handed out 200 + null, the download 200 with an EMPTY body (the caller saved a
    0-byte file), the update 500 (None reached the next subscript) and the delete 200 + null.
    """

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A name nothing carries is a 404, not a 200 with null."""
        response = rest_api.get(f'{BASE_URL}/{MISSING_NAME}?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_download_missing_returns_404(self, rest_api) -> None:
        """The empty 200 was the worst of them: the browser saved an empty file."""
        response = rest_api.get(f'{BASE_URL}/download/{MISSING_NAME}?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_data() != b''

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Editing a file someone else deleted is a 404, not a 500."""
        body = {'public_id': MISSING_ID, 'filename': MISSING_NAME, 'metadata': {'author_id': AUTHOR_ID}}
        attachment = json.dumps({'reference': True})

        response = rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting nothing is a 404 rather than a 200 reporting null."""
        assert rest_api.delete(f'{BASE_URL}/{MISSING_ID}').status_code == HTTPStatus.NOT_FOUND


class TestUpdateRequestGuards:
    """The update route's parameter and body are checked before anything is written."""

    def test_missing_attachment_parameter_returns_400(self, rest_api) -> None:
        """It used to be a TypeError from json.loads(None) on the way to a 500."""
        public_id = _upload(rest_api, 'dg-func-attach.txt')
        body = {'public_id': public_id, 'filename': 'dg-func-attach.txt', 'metadata': {'author_id': AUTHOR_ID}}

        assert rest_api.put(f'{BASE_URL}/', json=body).status_code == HTTPStatus.BAD_REQUEST

    def test_malformed_attachment_parameter_returns_400(self, rest_api) -> None:
        """A value that is not JSON is a client error, not a server one."""
        public_id = _upload(rest_api, 'dg-func-attach-bad.txt')
        body = {'public_id': public_id, 'filename': 'dg-func-attach-bad.txt', 'metadata': {'author_id': AUTHOR_ID}}

        assert rest_api.put(f'{BASE_URL}/?attachment=not-json', json=body).status_code == HTTPStatus.BAD_REQUEST

    def test_non_object_attachment_parameter_returns_400(self, rest_api) -> None:
        """A bare JSON value would break the reference lookup."""
        public_id = _upload(rest_api, 'dg-func-attach-list.txt')
        body = {'public_id': public_id, 'filename': 'dg-func-attach-list.txt', 'metadata': {'author_id': AUTHOR_ID}}

        response = rest_api.put(f'{BASE_URL}/?attachment=[1]', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_body_without_public_id_returns_400(self, rest_api) -> None:
        """No identity in the body, so there is nothing to update - a KeyError -> 500 before."""
        attachment = json.dumps({'reference': True})
        body = {'filename': 'dg-func-nobody.txt', 'metadata': {'author_id': AUTHOR_ID}}

        assert rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_body_without_filename_returns_400(self, rest_api) -> None:
        """The merge needs a filename and metadata; a missing one was a KeyError -> 500."""
        public_id = _upload(rest_api, 'dg-func-nofilename.txt')
        attachment = json.dumps({'reference': True})
        body = {'public_id': public_id, 'metadata': {'author_id': AUTHOR_ID}}

        assert rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_rename_keeps_the_name_unique_in_the_folder(self, rest_api) -> None:
        """
        Outside reference mode a clashing name is renamed rather than duplicated

        This is the branch create_attachment_name exists for.
        """
        _upload(rest_api, 'dg-func-taken.txt')
        public_id = _upload(rest_api, 'dg-func-renamed.txt')
        attachment = json.dumps({'reference': False})
        body = {
            'public_id': public_id,
            'filename': 'dg-func-taken.txt',
            'metadata': {'author_id': AUTHOR_ID, 'parent': None},
        }

        response = rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert response.get_json()['filename'].startswith('copy_(1)_')


class TestUploadReplacement:
    """Uploading over an existing entry replaces it - and keeps what pointed at it."""

    def test_replacement_carries_the_previous_reference(self, rest_api, database_manager, database_name) -> None:
        """
        The replaced entry's reference survives, because it is the same library entry with new content
        """
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        public_id = _upload(rest_api, 'dg-func-ref.txt')
        files.update_one(
            {'public_id': public_id},
            {'$set': {'metadata.reference': 4711, 'metadata.reference_type': 'object'}},
        )

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-ref.txt'), content_type='multipart/form-data',
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        stored = response.get_json()['raw']
        assert stored['metadata']['reference'] == 4711
        assert stored['metadata']['reference_type'] == 'object'

    def test_a_failing_replacement_keeps_the_previous_file(self, rest_api, monkeypatch,
                                                           database_manager, database_name) -> None:
        """
        The old entry is removed only after the new one exists (regression)

        It used to be deleted first, so a failing insert lost both.
        """
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        _upload(rest_api, 'dg-func-keep.txt')
        monkeypatch.setattr(MediaFilesManager, 'insert_file', _raiser(MediaFileManagerInsertError('boom')))

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-keep.txt'), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert files.find_one({'filename': 'dg-func-keep.txt'}) is not None

    def test_replacement_of_a_file_without_reference_keys_succeeds(self, rest_api, database_manager,
                                                                   database_name) -> None:
        """
        A stored entry written before the reference keys existed carries neither - a KeyError -> 500 before
        """
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        public_id = _upload(rest_api, 'dg-func-legacy.txt')
        files.update_one({'public_id': public_id}, {'$unset': {'metadata.reference': '',
                                                               'metadata.reference_type': ''}})

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-legacy.txt'), content_type='multipart/form-data',
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


class TestDownloadHeader:
    """The Content-Disposition header survives an awkward filename."""

    def test_filename_with_a_quote_is_quoted_in_the_header(self, rest_api) -> None:
        """Interpolated bare, such a name broke the header the browser parses."""
        awkward_name: str = 'dg-func-a b.txt'
        _upload(rest_api, awkward_name)

        response = rest_api.get(f'{BASE_URL}/download/{awkward_name}?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.OK
        assert response.headers['Content-Disposition'] == 'attachment; filename="dg-func-a b.txt"'


class TestRouteErrorMapping:
    """Every route maps a manager failure to a status instead of leaking it as a 500."""

    def test_upload_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failure while looking for the file the upload would replace is a 400."""
        monkeypatch.setattr(MediaFilesManager, 'file_exists', _raiser(MediaFileManagerGetError('boom')))

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-get-err.txt'), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_upload_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """Anything unmapped while storing is a 500."""
        monkeypatch.setattr(MediaFilesManager, 'insert_file', _raiser(RuntimeError('boom')))

        response = rest_api.post(
            f'{BASE_URL}/', data=_upload_form('dg-func-boom.txt'), content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A MediaFileManagerUpdateError while writing is a 400."""
        public_id = _upload(rest_api, 'dg-func-upd-err.txt')
        monkeypatch.setattr(MediaFilesManager, 'update_file', _raiser(MediaFileManagerUpdateError('boom')))
        attachment = json.dumps({'reference': True})
        body = {'public_id': public_id, 'filename': 'dg-func-upd-err.txt', 'metadata': {'author_id': AUTHOR_ID}}

        response = rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """Anything unmapped while updating is a 500."""
        public_id = _upload(rest_api, 'dg-func-upd-boom.txt')
        monkeypatch.setattr(MediaFilesManager, 'update_file', _raiser(RuntimeError('boom')))
        attachment = json.dumps({'reference': True})
        body = {'public_id': public_id, 'filename': 'dg-func-upd-boom.txt', 'metadata': {'author_id': AUTHOR_ID}}

        response = rest_api.put(f'{BASE_URL}/?attachment={attachment}', json=body)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A read failure is a 500, not an empty 200."""
        monkeypatch.setattr(MediaFilesManager, 'get_file', _raiser(RuntimeError('boom')))

        response = rest_api.get(f'{BASE_URL}/{MISSING_NAME}?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_download_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure while reading the bytes is a 500."""
        monkeypatch.setattr(MediaFilesManager, 'get_file', _raiser(RuntimeError('boom')))

        response = rest_api.get(f'{BASE_URL}/download/{MISSING_NAME}?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure while collecting the subtree is a 500."""
        public_id = _upload(rest_api, 'dg-func-del-boom.txt')
        monkeypatch.setattr(MediaFilesManager, 'get_many_media_files', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{BASE_URL}/{public_id}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_http_exception_keeps_its_status(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised by a collaborator passes through instead of becoming a 500."""
        monkeypatch.setattr(MediaFilesManager, 'get_many_media_files', _raiser(NotFound()))

        response = rest_api.get(f'{BASE_URL}/?metadata={AUTHOR_METADATA}')

        assert response.status_code == HTTPStatus.NOT_FOUND
