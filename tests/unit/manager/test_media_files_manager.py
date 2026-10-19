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

Only the errors the delegates really raise are caught: the driver's own for a GridFS call (a lost server or a lock
timeout becomes the transient error the app answers 503 / 423), the ``BaseManager*Error`` of a collection helper,
the model's declared errors. A programming error propagates as itself, which every method has a test for.
"""
# GridFS exposes a stored file's document only as GridIn._file / GridOut._file, so a stand-in
# for one has to set the same protected members the manager reads
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest
from gridfs.errors import FileExists, NoFile
from pymongo.errors import AutoReconnect, DuplicateKeyError, OperationFailure, PyMongoError

from cmdb.database.database_constants import MONGO_LOCK_TIMEOUT_ERROR_CODE
from cmdb.framework.results import IterationResult
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import GRIDFS_FILES_SUFFIX, MediaFileKey
from cmdb.manager.media_files_manager import (
    ANCESTOR_IDS_FIELD,
    MediaFilesManager,
    build_folder_ancestry_pipeline,
)
from cmdb.errors.database import (
    DocumentInsertDuplicateKeyError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerDeleteError,
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
)
from cmdb.errors.models.media_file import MediaFileInitFromDataError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 4
REPLACED_ID: int = 2
FILENAME: str = 'logo.png'
STAGED_FILENAME: str = f'replacing_({PUBLIC_ID})_{FILENAME}'
FILE_DOCUMENT: dict[str, Any] = {'public_id': PUBLIC_ID, 'filename': FILENAME}
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
GRID_ID: str = 'grid-object-id'
PAGE_TOTAL: int = 150
PARENT_ID: int = 7


def _manager(fs: MagicMock | None = None) -> MagicMock:
    """Builds a stand-in for `self` carrying only the GridFS handle the methods use."""
    mock_self = MagicMock()
    mock_self.fs = fs if fs is not None else MagicMock()

    return mock_self


def _stored_file(blob: bytes = b'png-bytes') -> MagicMock:
    """Builds a GridOut stand-in exposing the protected member GridFS makes callers use."""
    grid_out = MagicMock()
    grid_out._file = FILE_DOCUMENT
    grid_out.read.return_value = blob

    return grid_out


def _lock_timeout() -> OperationFailure:
    """The driver's lock timeout"""
    return OperationFailure('lock timeout', code=MONGO_LOCK_TIMEOUT_ERROR_CODE)


# The driver errors a GridFS call can raise, and what the manager raises for each beside its own error
TRANSIENT_CASES: list[tuple[Exception, type[Exception]]] = [
    (AutoReconnect('server gone'), DocumentNetworkError),
    (_lock_timeout(), DocumentLockTimeoutError),
]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               insert_file / _write_file                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertFile:
    """A file is written with its public_id and metadata from the start, and a failed write is aborted"""

    @staticmethod
    def _writing_manager() -> tuple[MagicMock, MagicMock]:
        """A manager whose _write_file is the real one, and the GridIn it writes"""
        mock_self = _manager()
        mock_self.get_new_media_file_id.return_value = PUBLIC_ID
        mock_self._draw_public_id.side_effect = lambda: MediaFilesManager._draw_public_id(mock_self)
        mock_self._write_file.side_effect = (
            lambda *args: MediaFilesManager._write_file(mock_self, *args)
        )
        grid_in = mock_self.fs.new_file.return_value
        grid_in._file = FILE_DOCUMENT

        return mock_self, grid_in

    def test_the_public_id_and_metadata_are_on_the_file_from_the_start(self) -> None:
        """Both go into new_file, so they are part of the document GridFS writes on close"""
        mock_self, grid_in = self._writing_manager()
        data = MagicMock(filename=FILENAME)

        result = MediaFilesManager.insert_file(mock_self, data, {'author_id': 1, 'mime_type': 'image/png'})

        kwargs = mock_self.fs.new_file.call_args.kwargs
        assert kwargs['filename'] == FILENAME
        assert kwargs['public_id'] == PUBLIC_ID
        assert kwargs['metadata']['author_id'] == 1
        grid_in.write.assert_called_once_with(data)
        grid_in.close.assert_called_once_with()
        assert result is FILE_DOCUMENT

    def test_a_failed_counter_read_writes_nothing(self) -> None:
        """The id is drawn before any chunk is written - no content can be left without a document"""
        mock_self, _ = self._writing_manager()
        failure = BaseManagerGetError('counter')
        mock_self.get_new_media_file_id.side_effect = failure

        with pytest.raises(MediaFileManagerInsertError) as caught:
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})

        assert caught.value.args[0] is failure
        mock_self.fs.new_file.assert_not_called()

    def test_a_failed_write_is_aborted(self) -> None:
        """The chunks written so far are removed, and the failure is the insert error"""
        mock_self, grid_in = self._writing_manager()
        grid_in.write.side_effect = PyMongoError('chunk refused')

        with pytest.raises(MediaFileManagerInsertError):
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})

        grid_in.abort.assert_called_once_with()

    def test_a_failing_abort_still_raises_the_write_failure(self) -> None:
        """The abort is best effort: its own failure is logged, the write's is raised"""
        mock_self, grid_in = self._writing_manager()
        grid_in.close.side_effect = PyMongoError('file document refused')
        grid_in.abort.side_effect = PyMongoError('abort refused')

        with pytest.raises(MediaFileManagerInsertError, match='file document refused'):
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})

    def test_a_duplicate_name_carries_the_typed_duplicate(self) -> None:
        """GridFS's FileExists is read through to the DuplicateKeyError it was raised for"""
        mock_self, grid_in = self._writing_manager()

        def _close() -> None:
            try:
                raise DuplicateKeyError('dup', details={'keyPattern': {'filename': 1}, 'keyValue': {}})
            except DuplicateKeyError as err:
                raise FileExists('file exists') from err

        grid_in.close.side_effect = _close

        with pytest.raises(MediaFileManagerInsertError) as caught:
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})

        assert isinstance(caught.value.__cause__, DocumentInsertDuplicateKeyError)
        assert caught.value.__cause__.key_pattern == {'filename': 1}

    @pytest.mark.parametrize('failure, expected', TRANSIENT_CASES)
    def test_a_transient_failure_is_raised_unwrapped(self, failure: Exception, expected: type[Exception]) -> None:
        """A lost server or a lock timeout is the app's 503 / 423, not the insert's 400"""
        mock_self, grid_in = self._writing_manager()
        grid_in.close.side_effect = failure

        with pytest.raises(expected):
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error is not reported as a failed insert"""
        mock_self, grid_in = self._writing_manager()
        grid_in.write.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError, match='bug'):
            MediaFilesManager.insert_file(mock_self, MagicMock(filename=FILENAME), {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     replace_file                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReplaceFile:
    """Staged write, old entry deleted, the replacement takes the name - each failure leaves the content findable"""

    @staticmethod
    def _replacing_manager() -> MagicMock:
        """A manager whose writes are stand-ins, recording the order of the steps"""
        mock_self = _manager()
        mock_self._draw_public_id.return_value = PUBLIC_ID
        mock_self._write_file.return_value = {'public_id': PUBLIC_ID, 'filename': STAGED_FILENAME}
        mock_self._discard_staged_replacement.side_effect = (
            lambda public_id: MediaFilesManager._discard_staged_replacement(mock_self, public_id)
        )

        return mock_self

    def test_the_steps_run_in_order(self) -> None:
        """Written under the staging name, the old entry deleted, then renamed"""
        mock_self = self._replacing_manager()

        result = MediaFilesManager.replace_file(mock_self, MagicMock(filename=FILENAME), {}, REPLACED_ID)

        assert mock_self._write_file.call_args.args[1] == STAGED_FILENAME
        mock_self.delete_file.assert_called_once_with(REPLACED_ID)
        mock_self.rename_file.assert_called_once_with(PUBLIC_ID, FILENAME)
        assert [step[0] for step in mock_self.method_calls if step[0] in {
            '_write_file', 'delete_file', 'rename_file'}] == ['_write_file', 'delete_file', 'rename_file']
        assert result['filename'] == FILENAME

    def test_a_failed_write_leaves_the_old_entry(self) -> None:
        """Nothing is deleted when the replacement could not be stored"""
        mock_self = self._replacing_manager()
        mock_self._write_file.side_effect = MediaFileManagerInsertError('write')

        with pytest.raises(MediaFileManagerInsertError):
            MediaFilesManager.replace_file(mock_self, MagicMock(filename=FILENAME), {}, REPLACED_ID)

        mock_self.delete_file.assert_not_called()

    def test_a_failed_delete_removes_the_replacement_again(self) -> None:
        """Only the old entry stays, and the delete's failure is raised"""
        mock_self = self._replacing_manager()
        failure = MediaFileManagerDeleteError('delete')
        mock_self.delete_file.side_effect = [failure, True]

        with pytest.raises(MediaFileManagerDeleteError) as caught:
            MediaFilesManager.replace_file(mock_self, MagicMock(filename=FILENAME), {}, REPLACED_ID)

        assert caught.value is failure
        assert [call.args[0] for call in mock_self.delete_file.call_args_list] == [REPLACED_ID, PUBLIC_ID]
        mock_self.rename_file.assert_not_called()

    def test_a_failed_clean_up_still_raises_the_delete_failure(self) -> None:
        """Removing the replacement is best effort"""
        mock_self = self._replacing_manager()
        failure = MediaFileManagerDeleteError('delete')
        mock_self.delete_file.side_effect = [failure, MediaFileManagerDeleteError('clean-up')]

        with pytest.raises(MediaFileManagerDeleteError) as caught:
            MediaFilesManager.replace_file(mock_self, MagicMock(filename=FILENAME), {}, REPLACED_ID)

        assert caught.value is failure

    def test_a_failed_rename_is_the_update_error(self) -> None:
        """The replacement is kept under the staging name"""
        mock_self = self._replacing_manager()
        mock_self.rename_file.side_effect = MediaFileManagerUpdateError('rename')

        with pytest.raises(MediaFileManagerUpdateError):
            MediaFilesManager.replace_file(mock_self, MagicMock(filename=FILENAME), {}, REPLACED_ID)

        assert mock_self.delete_file.call_count == 1


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
def test_open_file_returns_the_open_file() -> None:
    """The GridOut itself comes back, unread - reading is the caller's, chunk by chunk"""
    mock_self = _manager()
    grid_out = _stored_file()
    mock_self.fs.get_last_version.return_value = grid_out

    assert MediaFilesManager.open_file(mock_self, {'filename': FILENAME}) is grid_out
    grid_out.read.assert_not_called()


def test_open_file_returns_none_for_an_absent_file() -> None:
    """A file that does not exist is None - the routes turn that into a 404"""
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = NoFile('nope')

    assert MediaFilesManager.open_file(mock_self, {'filename': 'gone.png'}) is None


def test_open_file_raises_for_a_storage_failure() -> None:
    """
    A failure must not be swallowed into None

    Only NoFile may answer None; anything else has to reach the route, or a database outage would
    reach the client as "file not found".
    """
    mock_self = _manager()
    failure = PyMongoError('gridfs down')
    mock_self.fs.get_last_version.side_effect = failure

    with pytest.raises(MediaFileManagerGetError) as caught:
        MediaFilesManager.open_file(mock_self, {'filename': FILENAME})

    assert caught.value.__cause__ is failure


@pytest.mark.parametrize('failure, expected', TRANSIENT_CASES)
def test_open_file_raises_a_transient_failure_unwrapped(failure: Exception, expected: type[Exception]) -> None:
    """A lost server is the app's 503, a lock timeout its 423"""
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = failure

    with pytest.raises(expected):
        MediaFilesManager.open_file(mock_self, {'filename': FILENAME})


def test_open_file_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed read"""
    mock_self = _manager()
    mock_self.fs.get_last_version.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError, match='bug'):
        MediaFilesManager.open_file(mock_self, {'filename': FILENAME})


def test_get_file_returns_the_document() -> None:
    """The stored file document of the opened file comes back"""
    mock_self = _manager()
    mock_self.open_file.return_value = _stored_file()

    assert MediaFilesManager.get_file(mock_self, {'filename': FILENAME}) is FILE_DOCUMENT
    mock_self.open_file.assert_called_once_with({'filename': FILENAME})


def test_get_file_returns_none_for_an_absent_file() -> None:
    """An absent file stays None"""
    mock_self = _manager()
    mock_self.open_file.return_value = None

    assert MediaFilesManager.get_file(mock_self, {'filename': 'gone.png'}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                         get_folder_ancestry / get_folder_filenames                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_ancestry_pipeline_follows_the_parent_chain_to_public_ids() -> None:
    """One $graphLookup from metadata.parent to public_id, the ancestors' public_ids projected"""
    pipeline = build_folder_ancestry_pipeline(PARENT_ID)

    assert pipeline[0] == {'$match': {'public_id': PARENT_ID}}
    graph = pipeline[1]['$graphLookup']
    assert graph['from'] == FILES_COLLECTION
    assert graph['startWith'] == '$metadata.parent'
    assert (graph['connectFromField'], graph['connectToField']) == ('metadata.parent', 'public_id')
    assert pipeline[2]['$project'][ANCESTOR_IDS_FIELD] == f"${graph['as']}.public_id"


def test_get_folder_ancestry_answers_the_one_result() -> None:
    """The aggregation runs on the files collection; its one result comes back"""
    mock_self = _manager()
    row = {'public_id': PARENT_ID, ANCESTOR_IDS_FIELD: [1]}
    mock_self.aggregate_all.return_value = [row]

    assert MediaFilesManager.get_folder_ancestry(mock_self, PARENT_ID) is row
    assert mock_self.aggregate_all.call_args.kwargs['collection'] == FILES_COLLECTION


def test_get_folder_ancestry_answers_none_for_an_absent_entry() -> None:
    """No entry carries the public_id"""
    mock_self = _manager()
    mock_self.aggregate_all.return_value = []

    assert MediaFilesManager.get_folder_ancestry(mock_self, PARENT_ID) is None


def test_get_folder_ancestry_wraps_a_failed_read() -> None:
    """The aggregation's typed error becomes the manager's read error"""
    mock_self = _manager()
    failure = BaseManagerIterationError('db')
    mock_self.aggregate_all.side_effect = failure

    with pytest.raises(MediaFileManagerGetError) as caught:
        MediaFilesManager.get_folder_ancestry(mock_self, PARENT_ID)

    assert caught.value.args[0] is failure


def test_get_folder_ancestry_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed read"""
    mock_self = _manager()
    mock_self.aggregate_all.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError):
        MediaFilesManager.get_folder_ancestry(mock_self, PARENT_ID)


def test_get_folder_filenames_reads_the_other_entries_names_only() -> None:
    """One read of the folder, the entry itself excluded, the names projected"""
    mock_self = _manager()
    mock_self.get_many_from_other_collection.return_value = [{'filename': 'a.png'}, {'filename': 'b.png'}, {}]

    assert MediaFilesManager.get_folder_filenames(mock_self, PARENT_ID, PUBLIC_ID) == {'a.png', 'b.png'}
    call = mock_self.get_many_from_other_collection.call_args
    assert call.args[0] == FILES_COLLECTION
    assert call.kwargs['criteria'] == {'metadata.parent': PARENT_ID, 'public_id': {'$ne': PUBLIC_ID}}
    assert call.kwargs['projection'] == {'_id': 0, 'filename': 1}


def test_get_folder_filenames_wraps_a_failed_read() -> None:
    """The helper's typed error becomes the manager's read error"""
    mock_self = _manager()
    mock_self.get_many_from_other_collection.side_effect = BaseManagerGetError('db')

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.get_folder_filenames(mock_self, None, PUBLIC_ID)


def test_get_folder_filenames_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed read"""
    mock_self = _manager()
    mock_self.get_many_from_other_collection.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError):
        MediaFilesManager.get_folder_filenames(mock_self, None, PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_many_media_files                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def _grid_row(**overrides: Any) -> MagicMock:
    """One GridFS result as `fs.find` yields it."""
    grid = MagicMock()
    grid._file = {
        'public_id': PUBLIC_ID, 'filename': FILENAME, 'metadata': {},
        'chunkSize': 261120, 'uploadDate': 'ORIGINAL', 'length': 12, **overrides,
    }

    return grid


def test_get_many_media_files_returns_every_match_without_a_limit() -> None:
    """Each GridFS result becomes a serialised MediaFile; an unpaged read counts what it read"""
    mock_self = _manager()
    mock_self.fs.find.return_value = [_grid_row()]

    response = MediaFilesManager.get_many_media_files(mock_self, {'metadata.parent': 0})

    mock_self.fs.find.assert_called_once_with(filter={'metadata.parent': 0}, skip=0, limit=0, sort=None)
    mock_self.count_from_other_collection.assert_not_called()
    assert isinstance(response, IterationResult)
    assert response.count == 1
    assert response.total == 1
    assert response.results[0][MediaFileKey.PUBLIC_ID.value] == PUBLIC_ID


def test_get_many_media_files_applies_the_paging_in_the_query() -> None:
    """limit / skip / sort reach GridFS, so only the page is read"""
    mock_self = _manager()
    mock_self.fs.find.return_value = []
    sort = [('filename', -1)]

    MediaFilesManager.get_many_media_files(mock_self, {'metadata.parent': 0}, limit=10, skip=5, sort=sort)

    assert mock_self.fs.find.call_args.kwargs == {
        'filter': {'metadata.parent': 0}, 'skip': 5, 'limit': 10, 'sort': sort,
    }


def test_a_page_reports_the_total_of_every_match() -> None:
    """The total is counted on the file documents with the same filter, not taken from the page"""
    mock_self = _manager()
    mock_self.fs.find.return_value = [_grid_row()]
    mock_self.count_from_other_collection.return_value = PAGE_TOTAL

    response = MediaFilesManager.get_many_media_files(mock_self, {'metadata.parent': 0}, limit=1)

    mock_self.count_from_other_collection.assert_called_once_with(FILES_COLLECTION, {'metadata.parent': 0})
    assert response.count == 1
    assert response.total == PAGE_TOTAL


def test_a_failed_count_is_the_read_error() -> None:
    """The count helper's typed error becomes the manager's read error"""
    mock_self = _manager()
    mock_self.fs.find.return_value = []
    failure = BaseManagerGetError('count')
    mock_self.count_from_other_collection.side_effect = failure

    with pytest.raises(MediaFileManagerGetError) as caught:
        MediaFilesManager.get_many_media_files(mock_self, {}, limit=1)

    assert caught.value.args[0] is failure


def test_get_many_media_files_wraps_a_failure() -> None:
    """A GridFS query failure is reported as MediaFileManagerGetError"""
    mock_self = _manager()
    mock_self.fs.find.side_effect = PyMongoError('gridfs down')

    with pytest.raises(MediaFileManagerGetError):
        MediaFilesManager.get_many_media_files(mock_self, {})


@pytest.mark.parametrize('failure, expected', TRANSIENT_CASES)
def test_get_many_media_files_raises_a_transient_failure_unwrapped(
        failure: Exception, expected: type[Exception]) -> None:
    """A lost server is the app's 503, a lock timeout its 423"""
    mock_self = _manager()
    mock_self.fs.find.side_effect = failure

    with pytest.raises(expected):
        MediaFilesManager.get_many_media_files(mock_self, {})


def test_an_unreadable_stored_file_is_the_read_error() -> None:
    """A stored document lacking a key GridFS writes is the model's declared error, wrapped as the read error"""
    mock_self = _manager()
    unreadable = _grid_row()
    del unreadable._file['length']
    mock_self.fs.find.return_value = [unreadable]

    with pytest.raises(MediaFileManagerGetError) as caught:
        MediaFilesManager.get_many_media_files(mock_self, {})

    assert isinstance(caught.value.args[0], MediaFileInitFromDataError)


def test_get_many_media_files_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed read"""
    mock_self = _manager()
    mock_self.fs.find.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError, match='bug'):
        MediaFilesManager.get_many_media_files(mock_self, {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                               update_file / rename_file                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_file_targets_the_files_sub_collection() -> None:
    """GridFS file documents are only addressable in '<collection>.files'"""
    mock_self = _manager()

    MediaFilesManager.update_file(mock_self, {'public_id': PUBLIC_ID, 'filename': 'renamed.png'})

    assert mock_self.update.call_args.kwargs['collection'] == FILES_COLLECTION
    assert mock_self.update.call_args.kwargs['criteria'] == {MediaFileKey.PUBLIC_ID.value: PUBLIC_ID}


def test_update_file_does_not_touch_the_upload_date() -> None:
    """
    Regression: the update must not stamp uploadDate with 'now'

    uploadDate is GridFS's record of when the CONTENT was stored, so renaming a file or moving it to
    another folder must not make it look freshly uploaded.
    """
    mock_self = _manager()
    original = {'public_id': PUBLIC_ID, 'filename': 'renamed.png', 'uploadDate': 'ORIGINAL'}

    written = MediaFilesManager.update_file(mock_self, original)

    assert MediaFileKey.UPLOAD_DATE.value not in mock_self.update.call_args.kwargs['data']
    assert MediaFileKey.UPLOAD_DATE.value not in written


def test_update_file_does_not_mutate_the_callers_dict() -> None:
    """Regression: the caller's dict must not come back carrying our edits"""
    mock_self = _manager()
    original = {'public_id': PUBLIC_ID, 'filename': 'renamed.png', 'uploadDate': 'ORIGINAL'}

    MediaFilesManager.update_file(mock_self, original)

    assert original['uploadDate'] == 'ORIGINAL'


def test_update_file_wraps_a_failure() -> None:
    """A failed write is reported as MediaFileManagerUpdateError, carrying the helper's error"""
    mock_self = _manager()
    failure = BaseManagerUpdateError('write failed')
    mock_self.update.side_effect = failure

    with pytest.raises(MediaFileManagerUpdateError) as caught:
        MediaFilesManager.update_file(mock_self, {'public_id': PUBLIC_ID})

    assert caught.value.args[0] is failure


def test_update_file_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed update"""
    mock_self = _manager()
    mock_self.update.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError, match='bug'):
        MediaFilesManager.update_file(mock_self, {'public_id': PUBLIC_ID})


def test_update_file_without_a_public_id_is_an_update_error() -> None:
    """The criteria cannot be built without it, and that is the caller's mistake - checked before any write"""
    mock_self = _manager()

    with pytest.raises(MediaFileManagerUpdateError):
        MediaFilesManager.update_file(mock_self, {'filename': 'renamed.png'})

    mock_self.update.assert_not_called()


def test_rename_file_sets_the_name_alone() -> None:
    """Only the filename is written, on the files collection"""
    mock_self = _manager()

    MediaFilesManager.rename_file(mock_self, PUBLIC_ID, FILENAME)

    assert mock_self.update.call_args.kwargs == {
        'criteria': {'public_id': PUBLIC_ID}, 'data': {'filename': FILENAME}, 'collection': FILES_COLLECTION,
    }


def test_rename_file_wraps_a_failure() -> None:
    """The helper's typed error becomes the manager's update error"""
    mock_self = _manager()
    mock_self.update.side_effect = BaseManagerUpdateError('write failed')

    with pytest.raises(MediaFileManagerUpdateError):
        MediaFilesManager.rename_file(mock_self, PUBLIC_ID, FILENAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     delete_file                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _deleting_manager(documents: list[dict[str, Any]]) -> MagicMock:
    """A manager whose files collection answers the given documents to the _id read"""
    mock_self = _manager()
    mock_self.get_many_from_other_collection.return_value = documents
    mock_self.delete_many_from_other_collection.return_value = MagicMock(deleted_count=1)

    return mock_self


def test_delete_file_reads_only_the_grid_id() -> None:
    """The file document is read for its _id alone - no GridOut is opened"""
    mock_self = _deleting_manager([{'_id': GRID_ID}])

    MediaFilesManager.delete_file(mock_self, PUBLIC_ID)

    call = mock_self.get_many_from_other_collection.call_args
    assert call.args[0] == FILES_COLLECTION
    assert call.kwargs['projection'] == {'_id': 1}
    assert call.kwargs['criteria'] == {'public_id': PUBLIC_ID}
    mock_self.fs.get_last_version.assert_not_called()


def test_delete_file_deletes_the_chunks_first() -> None:
    """The chunks, then the file document - a failure between leaves a document a repeated delete finds"""
    mock_self = _deleting_manager([{'_id': GRID_ID}])

    assert MediaFilesManager.delete_file(mock_self, PUBLIC_ID) is True
    calls = [(call.args[0].rsplit('.', 1)[-1], call.args[1]) for call in
             mock_self.delete_many_from_other_collection.call_args_list]
    assert calls == [('chunks', {'files_id': {'$in': [GRID_ID]}}), ('files', {'_id': {'$in': [GRID_ID]}})]
    mock_self.fs.delete.assert_not_called()


def test_deleting_a_file_that_does_not_exist_reports_false() -> None:
    """
    Regression: a missing file and a failed delete must not raise the same error

    Nothing to delete is the state the caller wanted; it is not a storage failure.
    """
    mock_self = _deleting_manager([])

    assert MediaFilesManager.delete_file(mock_self, PUBLIC_ID) is False
    mock_self.delete_many_from_other_collection.assert_not_called()


def test_delete_file_wraps_a_failing_lookup() -> None:
    """A storage failure while resolving the id is still an error"""
    mock_self = _manager()
    mock_self.get_many_from_other_collection.side_effect = BaseManagerGetError('db down')

    with pytest.raises(MediaFileManagerDeleteError):
        MediaFilesManager.delete_file(mock_self, PUBLIC_ID)


def test_delete_file_names_the_failure_in_its_message() -> None:
    """The wrapper's message carries the storage error, not only the id - the caller sees what failed"""
    mock_self = _deleting_manager([{'_id': GRID_ID}])
    failure = BaseManagerDeleteError('chunks unreachable')
    mock_self.delete_many_from_other_collection.side_effect = failure

    with pytest.raises(MediaFileManagerDeleteError, match='chunks unreachable') as caught:
        MediaFilesManager.delete_file(mock_self, PUBLIC_ID)

    assert caught.value.__cause__ is failure


def test_delete_file_lets_a_bug_propagate() -> None:
    """A programming error is not reported as a failed delete"""
    mock_self = _deleting_manager([{'_id': GRID_ID}])
    mock_self.delete_many_from_other_collection.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError, match='bug'):
        MediaFilesManager.delete_file(mock_self, PUBLIC_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       collect_subtree / delete_subtree (T325)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
ROOT_ID: int = 1


def _entry(public_id: int) -> dict[str, Any]:
    """A walked entry: its GridFS id and its public_id"""
    return {'_id': f'oid-{public_id}', 'public_id': public_id}


def _tree_reader(children_by_parent: dict[int, list[int]]) -> MagicMock:
    """A get_many_from_other_collection stand-in answering one level of a stored tree per call"""
    def _read(_collection: str, projection: dict[str, int], criteria: dict[str, Any]) -> list[dict[str, Any]]:
        del projection
        parents: list[int] = criteria['metadata.parent']['$in']
        return [_entry(child) for parent in parents for child in children_by_parent.get(parent, [])]

    return MagicMock(side_effect=_read)


class TestCollectSubtree:
    """The walk reads one level per query and ends on a stored loop"""

    def test_the_levels_come_back_root_first(self) -> None:
        """root -> (2 -> 4, 3): three levels"""
        mock_self = _manager()
        mock_self.get_many_from_other_collection = _tree_reader({ROOT_ID: [2, 3], 2: [4]})

        levels = MediaFilesManager.collect_subtree(mock_self, _entry(ROOT_ID))

        assert [[entry['public_id'] for entry in level] for level in levels] == [[ROOT_ID], [2, 3], [4]]

    def test_one_query_per_level_not_per_entry(self) -> None:
        """Four entries over three levels: three reads (the last finds nothing) - it used to be one per entry"""
        mock_self = _manager()
        mock_self.get_many_from_other_collection = _tree_reader({ROOT_ID: [2, 3], 2: [4]})

        MediaFilesManager.collect_subtree(mock_self, _entry(ROOT_ID))

        calls = mock_self.get_many_from_other_collection.call_args_list
        assert [call.kwargs['criteria']['metadata.parent']['$in'] for call in calls] == [[ROOT_ID], [2, 3], [4]]

    def test_only_the_two_keys_the_delete_needs_are_read(self) -> None:
        """The walk projects _id and public_id - no metadata, no content"""
        mock_self = _manager()
        mock_self.get_many_from_other_collection = _tree_reader({})

        MediaFilesManager.collect_subtree(mock_self, _entry(ROOT_ID))

        call = mock_self.get_many_from_other_collection.call_args
        assert call.args[0] == f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'
        assert call.kwargs['projection'] == {'_id': 1, 'public_id': 1}

    def test_a_stored_loop_ends_the_walk(self) -> None:
        """root -> 2 -> root: the root is not collected twice and the walk stops - it used to recurse forever"""
        mock_self = _manager()
        mock_self.get_many_from_other_collection = _tree_reader({ROOT_ID: [2], 2: [ROOT_ID]})

        levels = MediaFilesManager.collect_subtree(mock_self, _entry(ROOT_ID))

        assert [[entry['public_id'] for entry in level] for level in levels] == [[ROOT_ID], [2]]

    def test_a_failed_level_read_is_the_get_error(self) -> None:
        """The manager's own error, carrying the failure"""
        mock_self = _manager()
        failure = BaseManagerGetError('db')
        mock_self.get_many_from_other_collection.side_effect = failure

        with pytest.raises(MediaFileManagerGetError) as caught:
            MediaFilesManager.collect_subtree(mock_self, _entry(ROOT_ID))

        assert caught.value.args[0] is failure


class TestDeleteSubtree:
    """The levels go deepest first, each in one batch on the documents and one on the chunks"""

    @staticmethod
    def _levels() -> list[list[dict[str, Any]]]:
        """root -> (2 -> 4, 3)"""
        return [[_entry(ROOT_ID)], [_entry(2), _entry(3)], [_entry(4)]]

    def test_deepest_level_first_chunks_before_documents(self) -> None:
        """Six deletes for three levels, leaves first; within a level the chunks, then their documents"""
        mock_self = _manager()
        mock_self.delete_many_from_other_collection.return_value = MagicMock(deleted_count=1)

        MediaFilesManager.delete_subtree(mock_self, self._levels())

        calls = [(call.args[0].rsplit('.', 1)[-1], call.args[1]) for call in
                 mock_self.delete_many_from_other_collection.call_args_list]
        assert calls == [
            ('chunks', {'files_id': {'$in': ['oid-4']}}), ('files', {'_id': {'$in': ['oid-4']}}),
            ('chunks', {'files_id': {'$in': ['oid-2', 'oid-3']}}), ('files', {'_id': {'$in': ['oid-2', 'oid-3']}}),
            ('chunks', {'files_id': {'$in': ['oid-1']}}), ('files', {'_id': {'$in': ['oid-1']}}),
        ]

    def test_answers_how_many_documents_went(self) -> None:
        """The documents' deleted counts summed"""
        mock_self = _manager()
        mock_self.delete_many_from_other_collection.return_value = MagicMock(deleted_count=2)

        assert MediaFilesManager.delete_subtree(mock_self, self._levels()) == 2 * len(self._levels())

    def test_a_failure_stops_before_the_levels_above(self) -> None:
        """The deepest level is gone, the failing one and the root are not touched - the rest stays connected"""
        mock_self = _manager()
        failure = BaseManagerDeleteError('db')
        mock_self.delete_many_from_other_collection.side_effect = [
            MagicMock(deleted_count=1), MagicMock(deleted_count=0), failure,
        ]

        with pytest.raises(MediaFileManagerDeleteError) as caught:
            MediaFilesManager.delete_subtree(mock_self, self._levels())

        assert caught.value.args[0] is failure
        assert mock_self.delete_many_from_other_collection.call_count == 3
