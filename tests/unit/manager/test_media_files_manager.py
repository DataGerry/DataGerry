# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.manager.media_files_manager

DB-free: the manager is driven unbound (`MediaFilesManager.method(mock_self, ...)`) with a MagicMock
standing in for the GridFS handle, so no MongoDB and no GridFS are involved. That is the pattern the
other manager unit suites use for a manager whose real work is delegation.

The error contract is what most of this pins, because it is what the routes translate into status
codes: a read answers None ONLY for a file that is absent and raises for anything else, so a storage
failure cannot reach the client as a 404; a delete distinguishes "there was nothing to delete" from
"the delete failed"; and a metadata update leaves GridFS's uploadDate alone.
"""
# GridFS exposes a stored file's document and id only as GridIn._file / GridOut._id, so a stand-in
# for one has to set the same protected members the manager reads
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest
from gridfs.errors import NoFile

from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import GRIDFS_FILES_SUFFIX, MediaFileKey
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerDeleteError,
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4
FILE_DOCUMENT: dict[str, Any] = {'public_id': PUBLIC_ID, 'filename': 'logo.png'}


def _manager(fs: MagicMock | None = None) -> MagicMock:
    """Builds a stand-in for `self` carrying only the GridFS handle the methods use."""
    mock_self = MagicMock()
    mock_self.fs = fs if fs is not None else MagicMock()

    return mock_self


def _stored_file(blob: bytes = b'png-bytes') -> MagicMock:
    """Builds a GridOut stand-in exposing the protected members GridFS makes callers use."""
    grid_out = MagicMock()
    grid_out._file = FILE_DOCUMENT
    grid_out._id = 'grid-object-id'
    grid_out.read.return_value = blob

    return grid_out


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     insert_file                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_insert_file_stores_the_public_id_and_metadata() -> None:
    """The new file carries a freshly allocated public_id and the serialised metadata"""
    mock_self = _manager()
    mock_self.get_new_media_file_id.return_value = PUBLIC_ID
    media_file = mock_self.fs.new_file.return_value.__enter__.return_value
    media_file._file = FILE_DOCUMENT
    data = MagicMock(filename='logo.png')

    result = MediaFilesManager.insert_file(mock_self, data, {'author_id': 1, 'mime_type': 'image/png'})

    mock_self.fs.new_file.assert_called_once_with(filename='logo.png')
    media_file.write.assert_called_once_with(data)
    assert media_file.public_id == PUBLIC_ID
    assert result is FILE_DOCUMENT


def test_insert_file_wraps_a_failure() -> None:
    """A GridFS write failure is reported as MediaFileManagerInsertError"""
    mock_self = _manager()
    mock_self.fs.new_file.side_effect = RuntimeError('gridfs down')

    with pytest.raises(MediaFileManagerInsertError):
        MediaFilesManager.insert_file(mock_self, MagicMock(filename='logo.png'), {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 get_new_media_file_id                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_new_media_file_id_increments_the_counter() -> None:
    """The id comes from the shared public_id counter, incremented"""
    mock_self = _manager()
    mock_self.get_next_public_id.return_value = 9

    assert MediaFilesManager.get_new_media_file_id(mock_self) == 9
    mock_self.get_next_public_id.assert_called_once_with(inc_id=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       get_file                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_file_returns_the_document() -> None:
    """Without the blob flag the stored file document comes back"""
    mock_self = _manager()
    mock_self.fs.get_last_version.return_value = _stored_file()

    assert MediaFilesManager.get_file(mock_self, {'filename': 'logo.png'}) is FILE_DOCUMENT


def test_get_file_returns_the_blob_when_asked() -> None:
    """With the blob flag the raw content comes back instead"""
    mock_self = _manager()
    mock_self.fs.get_last_version.return_value = _stored_file(b'png-bytes')

    assert MediaFilesManager.get_file(mock_self, {'filename': 'logo.png'}, blob=True) == b'png-bytes'


def test_get_file_returns_none_for_an_absent_file() -> None:
    """A file that does not exist is None - the routes turn that into a 404"""
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = NoFile('nope')

    assert MediaFilesManager.get_file(mock_self, {'filename': 'gone.png'}) is None


def test_get_file_raises_for_a_storage_failure() -> None:
    """
    Regression: every failure used to be swallowed into None

    A database outage then reached the client as "file not found", logged at DEBUG only. Only NoFile
    may answer None; anything else has to reach the route's 500.
    """
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = RuntimeError('gridfs down')

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.get_file(mock_self, {'filename': 'logo.png'})


def test_get_file_raises_when_reading_the_blob_fails() -> None:
    """A file that is found but cannot be read is a storage failure, not a missing file"""
    mock_self = _manager()
    grid_out = _stored_file()
    grid_out.read.side_effect = RuntimeError('corrupt chunk')
    mock_self.fs.get_last_version.return_value = grid_out

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.get_file(mock_self, {'filename': 'logo.png'}, blob=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_many_media_files                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_many_media_files_returns_every_match() -> None:
    """Each GridFS result becomes a serialised MediaFile, with the count of what was returned"""
    mock_self = _manager()
    grid = MagicMock()
    grid._file = {
        'public_id': PUBLIC_ID, 'filename': 'logo.png', 'metadata': {},
        'chunkSize': 261120, 'uploadDate': 'ORIGINAL', 'length': 12,
    }
    mock_self.fs.find.return_value = [grid]

    response = MediaFilesManager.get_many_media_files(mock_self, {'metadata.parent': 0})

    mock_self.fs.find.assert_called_once_with(filter={'metadata.parent': 0})
    assert response.count == 1
    assert response.result[0][MediaFileKey.PUBLIC_ID.value] == PUBLIC_ID


def test_get_many_media_files_ignores_the_paging_params() -> None:
    """Documented gap (discussion-backlog #48): limit / skip / sort never reach the GridFS query"""
    mock_self = _manager()
    mock_self.fs.find.return_value = []

    MediaFilesManager.get_many_media_files(mock_self, {'metadata.parent': 0}, limit=10, skip=5)

    assert mock_self.fs.find.call_args.kwargs == {'filter': {'metadata.parent': 0}}


def test_get_many_media_files_wraps_a_failure() -> None:
    """A GridFS query failure is reported as MediaFileManagerGetError"""
    mock_self = _manager()
    mock_self.fs.find.side_effect = RuntimeError('gridfs down')

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.get_many_media_files(mock_self, {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     file_exists                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('exists', [True, False])
def test_file_exists_reports_the_gridfs_answer(exists: bool) -> None:
    """The existence check is a straight delegation"""
    mock_self = _manager()
    mock_self.fs.exists.return_value = exists

    assert MediaFilesManager.file_exists(mock_self, {'filename': 'logo.png'}) is exists


def test_file_exists_wraps_a_failure() -> None:
    """Regression: this was the one method with no error handling, leaking a raw pymongo error"""
    mock_self = _manager()
    mock_self.fs.exists.side_effect = RuntimeError('gridfs down')

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.file_exists(mock_self, {'filename': 'logo.png'})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     update_file                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_file_targets_the_files_sub_collection() -> None:
    """GridFS file documents are only addressable in '<collection>.files'"""
    mock_self = _manager()

    MediaFilesManager.update_file(mock_self, {'public_id': PUBLIC_ID, 'filename': 'renamed.png'})

    assert mock_self.update.call_args.kwargs['collection'] == f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
    assert mock_self.update.call_args.kwargs['criteria'] == {MediaFileKey.PUBLIC_ID.value: PUBLIC_ID}


def test_update_file_does_not_touch_the_upload_date() -> None:
    """
    Regression: the update used to stamp uploadDate with 'now'

    uploadDate is GridFS's record of when the CONTENT was stored, so renaming a file or moving it to
    another folder must not make it look freshly uploaded.
    """
    mock_self = _manager()
    original = {'public_id': PUBLIC_ID, 'filename': 'renamed.png', 'uploadDate': 'ORIGINAL'}

    written = MediaFilesManager.update_file(mock_self, original)

    assert MediaFileKey.UPLOAD_DATE.value not in mock_self.update.call_args.kwargs['data']
    assert MediaFileKey.UPLOAD_DATE.value not in written


def test_update_file_does_not_mutate_the_callers_dict() -> None:
    """Regression: the caller's dict used to come back carrying our edits"""
    mock_self = _manager()
    original = {'public_id': PUBLIC_ID, 'filename': 'renamed.png', 'uploadDate': 'ORIGINAL'}

    MediaFilesManager.update_file(mock_self, original)

    assert original['uploadDate'] == 'ORIGINAL'


def test_update_file_wraps_a_failure() -> None:
    """A failed write is reported as MediaFileManagerUpdateError"""
    mock_self = _manager()
    mock_self.update.side_effect = RuntimeError('write failed')

    with pytest.raises(MediaFileManagerUpdateError):
        MediaFilesManager.update_file(mock_self, {'public_id': PUBLIC_ID})


def test_update_file_without_a_public_id_is_an_update_error() -> None:
    """The criteria cannot be built without it, and that is the caller's mistake"""
    mock_self = _manager()

    with pytest.raises(MediaFileManagerUpdateError):
        MediaFilesManager.update_file(mock_self, {'filename': 'renamed.png'})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     delete_file                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_file_deletes_the_resolved_grid_id() -> None:
    """The public_id is resolved to the GridFS object id, which is what delete takes"""
    mock_self = _manager()
    mock_self.fs.get_last_version.return_value = _stored_file()

    assert MediaFilesManager.delete_file(mock_self, PUBLIC_ID) is True
    mock_self.fs.delete.assert_called_once_with('grid-object-id')


def test_deleting_a_file_that_does_not_exist_reports_false() -> None:
    """
    Regression: a missing file and a failed delete used to raise the same error

    Nothing to delete is the state the caller wanted; it is not a storage failure.
    """
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = NoFile('nope')

    assert MediaFilesManager.delete_file(mock_self, PUBLIC_ID) is False
    mock_self.fs.delete.assert_not_called()


def test_delete_file_wraps_a_failing_lookup() -> None:
    """A storage failure while resolving the id is still an error"""
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = RuntimeError('gridfs down')

    with pytest.raises(MediaFileManagerDeleteError):
        MediaFilesManager.delete_file(mock_self, PUBLIC_ID)


def test_delete_file_wraps_a_failing_delete() -> None:
    """A file that was found but could not be removed is an error, not a False"""
    mock_self = _manager()
    mock_self.fs.get_last_version.return_value = _stored_file()
    mock_self.fs.delete.side_effect = RuntimeError('delete failed')

    with pytest.raises(MediaFileManagerDeleteError):
        MediaFilesManager.delete_file(mock_self, PUBLIC_ID)
