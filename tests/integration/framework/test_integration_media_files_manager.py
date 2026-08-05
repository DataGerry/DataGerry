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
(guarding the '<collection>.files' target), and delete_file removes it.
"""
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from cmdb.database import MongoDatabaseManager
from cmdb.manager.media_files_manager import MediaFilesManager
from cmdb.framework.media_library.media_file import MediaFile
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
