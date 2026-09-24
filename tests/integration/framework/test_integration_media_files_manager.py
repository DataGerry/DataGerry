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
get_file / file_exists / get_many_media_files resolve it, update_file persists a metadata change
(guarding the '<collection>.files' target), and delete_file removes it. The list is paged and sorted by
GridFS itself with a real total, an unpaged read returns every match, and open_file streams a
multi-chunk file back byte for byte.

Also what the stored metadata sub-document looks like: every declared key present, the mime type
falling back to the default, and an undeclared key dropped instead of failing the insert.
"""
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from cmdb.database import MongoDatabaseManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.framework.media_library import DEFAULT_MIME_TYPE, MediaFile, MediaFileMetadataKey
from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    recursive_delete_filter,
    stream_grid_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

AUTHOR_ID: int = 1
FILES_COLLECTION: str = f'{MediaFile.COLLECTION}.files'

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


def _upload(name: str) -> FileStorage:
    """Builds a FileStorage suitable for MediaFilesManager.insert_file."""
    return FileStorage(stream=BytesIO(b'media-content'), filename=name, content_type='text/plain')


class TestInsertAndRead:
    """insert_file persists a file that get_file / file_exists / get_many resolve."""

    def test_insert_returns_document_with_public_id(self, media_files_manager: MediaFilesManager) -> None:
        """insert_file returns the stored document carrying a public_id and the filename."""
        result = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert result['public_id'] > 0
        assert result['filename'] == FILE_NAME_A

    def test_get_file_and_exists(self, media_files_manager: MediaFilesManager) -> None:
        """A stored file is resolvable by public_id and reports as existing."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        public_id = inserted['public_id']

        assert media_files_manager.file_exists({'public_id': public_id})
        assert media_files_manager.get_file({'public_id': public_id})['filename'] == FILE_NAME_A

    def test_get_file_missing_returns_none(self, media_files_manager: MediaFilesManager) -> None:
        """A missing file resolves to None rather than raising."""
        assert media_files_manager.get_file({'public_id': 987654}) is None

    def test_get_many_returns_all_matching(self, media_files_manager: MediaFilesManager) -> None:
        """get_many_media_files returns every file matching the metadata filter."""
        media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})
        media_files_manager.insert_file(_upload(FILE_NAME_B), {'author_id': AUTHOR_ID})

        response = media_files_manager.get_many_media_files({'metadata.author_id': AUTHOR_ID})

        names = {item['filename'] for item in response.result}
        assert {FILE_NAME_A, FILE_NAME_B} <= names


class TestInsertedMetadata:
    """insert_file stores the metadata sub-document the media library declares, and only that."""

    def test_every_declared_key_is_stored(self, media_files_manager: MediaFilesManager) -> None:
        """A file inserted with only an author still carries the whole sub-document."""
        inserted = media_files_manager.insert_file(_upload(FILE_NAME_A), {'author_id': AUTHOR_ID})

        assert set(inserted['metadata']) == {key.value for key in MediaFileMetadataKey}

    def test_an_undeclared_key_is_not_stored(self, media_files_manager: MediaFilesManager) -> None:
        """An undeclared key used to raise a TypeError that failed the insert."""
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
        assert not media_files_manager.file_exists({'public_id': inserted['public_id']})


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
    """The filenames of a GridFsResponse, in order."""
    return [row['filename'] for row in response.result]


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
        """The subtree walk reads unpaged, so a folder with many children is emptied completely"""
        folder = media_files_manager.insert_file(_upload('dg-page-folder'), {'author_id': AUTHOR_ID, 'folder': True})
        for index in range(PAGED_FILE_COUNT):
            media_files_manager.insert_file(
                _upload(f'dg-child-{index:02}.txt'), {'author_id': AUTHOR_ID, 'parent': folder['public_id']},
            )

        collected = recursive_delete_filter(folder['public_id'], media_files_manager)

        assert len(collected) == PAGED_FILE_COUNT + 1


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
