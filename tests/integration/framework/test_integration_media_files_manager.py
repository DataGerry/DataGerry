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
Integration tests for MediaFilesManager against a real MongoDB GridFS

Pins the GridFS-backed CRUD: insert_file stores the file + metadata and returns the document,
get_file / get_many_media_files resolve it, update_file persists a metadata change
(guarding the '<collection>.files' target), and delete_file removes it with its chunks. The list is paged and sorted
by GridFS itself with a real total, an unpaged read returns every match, and open_file streams a
multi-chunk file back byte for byte.

With the indexes a boot builds (``built_media_library_indexes``): replace_file swaps an entry under the unique
(filename, metadata.parent) index, a second entry of one name in one folder is refused as the typed duplicate, and a
refused or failing write leaves no chunk behind.

Also what the stored metadata sub-document looks like: every declared key present, the mime type
falling back to the default, and an undeclared key dropped instead of failing the insert.
"""
from io import BytesIO
from typing import Any

import pytest
from pymongo.errors import PyMongoError
from werkzeug.datastructures import FileStorage

from cmdb.database import MongoDatabaseManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.framework.media_library import DEFAULT_MIME_TYPE, MediaFile, MediaFileMetadataKey
from cmdb.framework.media_library.media_file_keys import MEDIA_FILE_PARENT_INDEX_NAME
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import stream_grid_file
from cmdb.errors.database import DocumentInsertDuplicateKeyError
from cmdb.errors.manager.media_files_manager import MediaFileManagerInsertError

from tests.utils.media_library_indexes import built_media_library_indexes
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 1
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'
CHUNKS_COLLECTION: str = f'{MediaFile.COLLECTION}.chunks'

FILE_NAME_A: str = 'dg-media-a.txt'
FILE_NAME_B: str = 'dg-media-b.txt'
UPDATED_NAME: str = 'dg-media-a-renamed.txt'


@pytest.fixture(name='media_files_manager')
def fixture_media_files_manager(database_manager: MongoDatabaseManager) -> MediaFilesManager:
    """Provides a MediaFilesManager wired to the test database."""
    return MediaFilesManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any media files this test module seeds (by author), before and after each test."""
    def _purge() -> None:
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        for doc in list(files.find({'metadata.author_id': AUTHOR_ID})):
            files.delete_one({'_id': doc['_id']})
            database_manager.get_collection(f'{MediaFile.COLLECTION}.chunks', database_name)\
                .delete_many({'files_id': doc['_id']})

    _purge()
    yield
    _purge()


def _upload(name: str, content: bytes = b'media-content') -> FileStorage:
    """Builds a FileStorage suitable for MediaFilesManager.insert_file."""
    return FileStorage(stream=BytesIO(content), filename=name, content_type='text/plain')


def _chunks_of(database_manager: MongoDatabaseManager, database_name: str, file_id: Any) -> list[dict[str, Any]]:
    """The stored chunks of one file"""
    return list(database_manager.get_collection(CHUNKS_COLLECTION, database_name).find({'files_id': file_id}))


def _chunk_count(database_manager: MongoDatabaseManager, database_name: str) -> int:
    """How many chunks the library stores"""
    return database_manager.get_collection(CHUNKS_COLLECTION, database_name).count_documents({})


class TestInsertAndRead:
    """insert_file persists a file that get_file / get_many resolve."""

    def test_insert_returns_document_with_public_id(self, media_files_manager: MediaFilesManager) -> None:
        """insert_file returns the stored document carrying a public_id and the filename."""
        result = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert result['public_id'] > 0
        assert result['filename'] == FILE_NAME_A

    def test_get_file_and_exists(self, media_files_manager: MediaFilesManager) -> None:
        """A stored file is resolvable by public_id and reports as existing."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        public_id = inserted['public_id']

        assert media_files_manager.get_file({'public_id': public_id})['filename'] == FILE_NAME_A

    def test_get_file_missing_returns_none(self, media_files_manager: MediaFilesManager) -> None:
        """A missing file resolves to None rather than raising."""
        assert media_files_manager.get_file({'public_id': 987654}) is None

    def test_get_many_returns_all_matching(self, media_files_manager: MediaFilesManager) -> None:
        """get_many_media_files returns every file matching the metadata filter."""
        media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        media_files_manager.insert_file(_upload(FILE_NAME_B), {'author_id': AUTHOR_ID})

        response = media_files_manager.get_many_media_files({'metadata.author_id': AUTHOR_ID})

        names = {item['filename'] for item in response.results}
        assert {FILE_NAME_A, FILE_NAME_B} <= names


class TestInsertedMetadata:
    """insert_file stores the metadata sub-document the media library declares, and only that."""

    def test_every_declared_key_is_stored(self, media_files_manager: MediaFilesManager) -> None:
        """A file inserted with only an author still carries the whole sub-document."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert set(inserted['metadata']) == {key.value for key in MediaFileMetadataKey}

    def test_an_undeclared_key_is_not_stored(self, media_files_manager: MediaFilesManager) -> None:
        """An undeclared key is dropped rather than failing the insert."""
        inserted = media_files_manager.insert_file(
            _upload(FILE_NAME_A), {'author_id': AUTHOR_ID, 'bogus': 'value'},
        )

        assert 'bogus' not in inserted['metadata']

    def test_a_missing_mime_type_falls_back_to_the_default(
            self, media_files_manager: MediaFilesManager) -> None:
        """The route stamps the upload's mime type; without one the default is stored, never ''."""
        inserted = media_files_manager.insert_file(
            _upload(FILE_NAME_A), {'author_id': AUTHOR_ID, 'mime_type': ''},
        )

        assert inserted['metadata']['mime_type'] == DEFAULT_MIME_TYPE


class TestUpdate:
    """update_file persists a change to the file document."""

    def test_update_persists_filename(self, media_files_manager: MediaFilesManager) -> None:
        """Updating the filename is persisted to the GridFS files collection and re-read."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        stored = media_files_manager.get_file({'public_id': inserted['public_id']})
        stored['filename'] = UPDATED_NAME

        media_files_manager.update_file(stored)

        reread = media_files_manager.get_file({'public_id': inserted['public_id']})
        assert reread['filename'] == UPDATED_NAME


class TestDelete:
    """delete_file removes the stored file."""

    def test_delete_removes_file(self, media_files_manager: MediaFilesManager) -> None:
        """After delete_file the file no longer exists."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert media_files_manager.delete_file(inserted['public_id']) is True
        assert media_files_manager.get_file({'public_id': inserted['public_id']}) is None

    def test_delete_removes_the_chunks_too(self, media_files_manager: MediaFilesManager,
                                           database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Through the batch delete, chunks first - none of the file's chunks is left"""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        media_files_manager.delete_file(inserted['public_id'])

        assert not _chunks_of(database_manager, database_name, inserted['_id'])

    def test_deleting_an_absent_file_answers_false(self, media_files_manager: MediaFilesManager) -> None:
        """Nothing to delete is no failure"""
        assert media_files_manager.delete_file(987654) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                         paging, the real total, streaming                                            #
# -------------------------------------------------------------------------------------------------------------------- #
PAGED_PARENT: int = 990001
PAGED_FILE_COUNT: int = 12
LARGE_FILE_SIZE: int = 600 * 1024  # more than two GridFS chunks


def _seed_folder(media_files_manager: MediaFilesManager, count: int = PAGED_FILE_COUNT) -> list[str]:
    """Stores `count` files in PAGED_PARENT and returns their names, ascending."""
    names: list[str] = [f'dg-page-{index:02}.txt' for index in range(count)]

    for name in names:
        media_files_manager.insert_file(_upload(name), {'author_id': AUTHOR_ID, 'parent': PAGED_PARENT})

    return names


def _names(response) -> list[str]:
    """The filenames of one page of the manager's IterationResult, in order."""
    return [row['filename'] for row in response.results]


class TestPagingInTheQuery:
    """limit / skip / sort are applied by GridFS, and the total is the real count."""

    FOLDER: dict = {'metadata.parent': PAGED_PARENT}

    def test_a_page_is_cut_and_sorted_in_the_query(self, media_files_manager: MediaFilesManager) -> None:
        """The second page of five, by name"""
        names = _seed_folder(media_files_manager)

        response = media_files_manager.get_many_media_files(self.FOLDER, limit=5, skip=5, sort=[('filename', 1)])

        assert _names(response) == names[5:10]
        assert response.total == PAGED_FILE_COUNT

    def test_a_descending_sort_is_applied(self, media_files_manager: MediaFilesManager) -> None:
        """What the file explorer asks for"""
        names = _seed_folder(media_files_manager)

        response = media_files_manager.get_many_media_files(self.FOLDER, limit=3, sort=[('filename', -1)])

        assert _names(response) == list(reversed(names))[:3]

    def test_the_last_page_is_short_and_the_total_unchanged(self, media_files_manager: MediaFilesManager) -> None:
        """A page past the middle returns the rest"""
        _seed_folder(media_files_manager)

        response = media_files_manager.get_many_media_files(self.FOLDER, limit=5, skip=10)

        assert response.count == 2
        assert response.total == PAGED_FILE_COUNT

    def test_no_limit_returns_every_match(self, media_files_manager: MediaFilesManager) -> None:
        """What the unpaged callers and the recursive delete rely on"""
        _seed_folder(media_files_manager)

        response = media_files_manager.get_many_media_files(self.FOLDER)

        assert response.count == PAGED_FILE_COUNT
        assert response.total == PAGED_FILE_COUNT

    def test_a_folder_delete_collects_every_child_beyond_any_page(
            self, media_files_manager: MediaFilesManager,
    ) -> None:
        """The subtree walk reads each level whole, so a folder with many children is emptied completely"""
        folder = media_files_manager.insert_file(_upload('dg-page-folder'), {'author_id': AUTHOR_ID, 'folder': True})
        for index in range(PAGED_FILE_COUNT):
            media_files_manager.insert_file(
                _upload(f'dg-child-{index:02}.txt'), {'author_id': AUTHOR_ID, 'parent': folder['public_id']},
            )

        levels = media_files_manager.collect_subtree(folder)

        assert sum(len(level) for level in levels) == PAGED_FILE_COUNT + 1


class TestOpenFile:
    """open_file hands out the stored file for chunked reading."""

    def test_the_content_streams_back_in_chunks(self, media_files_manager: MediaFilesManager) -> None:
        """A multi-chunk file arrives in more than one piece and byte-identical"""
        content = bytes(range(256)) * (LARGE_FILE_SIZE // 256)
        media_files_manager.insert_file(
            FileStorage(stream=BytesIO(content), filename='dg-large.bin', content_type='application/octet-stream'),
            {'author_id': AUTHOR_ID},
        )

        chunks = list(stream_grid_file(media_files_manager.open_file({'filename': 'dg-large.bin'})))

        assert len(chunks) > 1
        assert b''.join(chunks) == content

    def test_an_absent_file_is_none(self, media_files_manager: MediaFilesManager) -> None:
        """The download route turns this into its 404"""
        assert media_files_manager.open_file({'filename': 'dg-not-there.bin'}) is None


class TestFolderSubtree:
    """collect_subtree + delete_subtree against real GridFS: the whole subtree goes, content included"""

    CHUNKS: str = f'{MediaFile.COLLECTION}.chunks'

    def _tree(self, media_files_manager: MediaFilesManager) -> tuple[dict, list[int]]:
        """root -> (sub -> deep, flat); the root document and every public_id"""
        root = media_files_manager.insert_file(_upload('dg-tree-root'), {'author_id': AUTHOR_ID, 'folder': True})
        sub = media_files_manager.insert_file(
            _upload('dg-tree-sub'), {'author_id': AUTHOR_ID, 'folder': True, 'parent': root['public_id']},
        )
        deep = media_files_manager.insert_file(
            _upload('dg-tree-deep.txt'), {'author_id': AUTHOR_ID, 'parent': sub['public_id']},
        )
        flat = media_files_manager.insert_file(
            _upload('dg-tree-flat.txt'), {'author_id': AUTHOR_ID, 'parent': root['public_id']},
        )

        return root, [root['public_id'], sub['public_id'], deep['public_id'], flat['public_id']]

    def test_the_walk_answers_three_levels(self, media_files_manager: MediaFilesManager) -> None:
        """The root, its two children, the grandchild"""
        root, _ = self._tree(media_files_manager)

        levels = media_files_manager.collect_subtree(root)

        assert [len(level) for level in levels] == [1, 2, 1]

    def test_no_document_and_no_chunk_is_left(
            self, media_files_manager: MediaFilesManager, database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """The batch delete removes the documents and their chunks - GridFS's own per-file delete is not used"""
        root, public_ids = self._tree(media_files_manager)
        files = database_manager.get_collection(FILES_COLLECTION, database_name)
        file_ids = [doc['_id'] for doc in files.find({'public_id': {'$in': public_ids}})]

        deleted = media_files_manager.delete_subtree(media_files_manager.collect_subtree(root))

        assert deleted == len(public_ids)
        assert not files.count_documents({'public_id': {'$in': public_ids}})
        assert not database_manager.get_collection(self.CHUNKS, database_name).count_documents(
            {'files_id': {'$in': file_ids}},
        )

    def test_the_parent_read_uses_the_parent_index(
            self, media_files_manager: MediaFilesManager, database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """
        The walk's per-level read is served by the parent index, not a collection scan

        The (filename, metadata.parent) index leads with filename and cannot serve a read by parent alone. The
        boot builds the declared indexes (``init_media_library_indexes``); the test database is built here
        """
        parent_index = next(
            index for index in MediaFile.get_index_keys() if index.document['name'] == MEDIA_FILE_PARENT_INDEX_NAME
        )
        database_manager.create_indexes(FILES_COLLECTION, database_name, [parent_index])
        root, _ = self._tree(media_files_manager)

        plan = database_manager.get_collection(FILES_COLLECTION, database_name).find(
            {'metadata.parent': {'$in': [root['public_id']]}},
        ).explain()

        assert MEDIA_FILE_PARENT_INDEX_NAME in str(plan['queryPlanner']['winningPlan'])
        assert 'COLLSCAN' not in str(plan['queryPlanner']['winningPlan'])


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the unique (filename, metadata.parent) index                                    #
# -------------------------------------------------------------------------------------------------------------------- #
REPLACED_CONTENT: bytes = b'old content'
REPLACEMENT_CONTENT: bytes = b'new content'


class _FailingStream:
    """An upload whose content can not be read to the end - the write fails part-way"""

    filename: str = FILE_NAME_A

    def __init__(self) -> None:
        self.reads: int = 0

    def read(self, size: int = -1) -> bytes:
        """One chunk of content, then a failure"""
        self.reads += 1

        if self.reads > 1:
            raise PyMongoError('connection reset while streaming')

        return b'x' * max(size, 1)


@pytest.fixture(name='media_indexes')
def fixture_media_indexes(database_manager: MongoDatabaseManager, database_name: str):
    """The media library's indexes, for one test"""
    with built_media_library_indexes(database_manager, database_name):
        yield


@pytest.mark.usefixtures('media_indexes')
class TestUnderTheUniqueIndex:
    """What a real database with its indexes answers"""

    def test_a_second_entry_of_one_name_is_the_typed_duplicate(
            self, media_files_manager: MediaFilesManager, database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """Refused by the index, reported as the duplicate it is, and no chunk of it left behind"""
        media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        chunks_before: int = _chunk_count(database_manager, database_name)

        with pytest.raises(MediaFileManagerInsertError) as caught:
            media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert isinstance(caught.value.__cause__, DocumentInsertDuplicateKeyError)
        assert _chunk_count(database_manager, database_name) == chunks_before

    def test_the_same_name_in_another_folder_is_legal(self, media_files_manager: MediaFilesManager) -> None:
        """Only a clash inside one folder is refused"""
        media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID, 'parent': 990202})

    def test_replace_file_swaps_the_entry(self, media_files_manager: MediaFilesManager,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """One entry of the name, carrying the new content; the old one and its chunks are gone"""
        old = media_files_manager.insert_file(_upload(FILE_NAME_A, REPLACED_CONTENT), {'author_id': AUTHOR_ID})

        new = media_files_manager.replace_file(
            _upload(FILE_NAME_A, REPLACEMENT_CONTENT), {'author_id': AUTHOR_ID}, old['public_id'],
        )

        stored = list(database_manager.get_collection(FILES_COLLECTION, database_name).find(
            {'filename': FILE_NAME_A, 'metadata.author_id': AUTHOR_ID},
        ))
        assert [entry['public_id'] for entry in stored] == [new['public_id']]
        assert new['filename'] == FILE_NAME_A
        assert b''.join(stream_grid_file(media_files_manager.open_file({'public_id': new['public_id']}))) \
            == REPLACEMENT_CONTENT
        assert not _chunks_of(database_manager, database_name, old['_id'])

    def test_a_write_failing_part_way_leaves_nothing(self, media_files_manager: MediaFilesManager,
                                                     database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """The aborted write removes what it wrote: no file document, no chunk"""
        chunks_before: int = _chunk_count(database_manager, database_name)

        with pytest.raises(MediaFileManagerInsertError):
            media_files_manager.insert_file(_FailingStream(), {'author_id': AUTHOR_ID})

        assert media_files_manager.get_file({'filename': FILE_NAME_A}) is None
        assert _chunk_count(database_manager, database_name) == chunks_before
