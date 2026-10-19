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
Builds the media library's indexes for the duration of one test

The test session never runs the collection validator, so the media library's file collection carries none of the
indexes a real database has - the unique one over (filename, metadata.parent) among them, and a write that only fails
against it passes unnoticed. ``built_media_library_indexes`` builds them the way a boot does
(``CollectionValidator.init_media_library_indexes``) and drops the ones it built afterwards, because other suites seed
duplicate names on purpose (the de-duplicating updater's)
"""
from collections.abc import Iterator
from contextlib import contextmanager

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.framework.media_library import GRIDFS_FILES_SUFFIX, MediaFile
from cmdb.framework.media_library.media_file_keys import MEDIA_FILE_FILENAME_PARENT_INDEX_NAME
# -------------------------------------------------------------------------------------------------------------------- #

FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'


@contextmanager
def built_media_library_indexes(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """
    Builds the media library's indexes as a boot does, and drops the ones it built when the block ends

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database

    Raises:
        AssertionError: When the unique (filename, metadata.parent) index could not be built - files colliding on
            it are stored, which a test of the index must not run against

    Yields:
        None: Inside the block the indexes exist
    """
    collection = database_manager.get_collection(FILES_COLLECTION, database_name)
    existing: set[str] = set(collection.index_information())

    CollectionValidator(database_name, database_manager).init_media_library_indexes()

    built: set[str] = set(collection.index_information()) - existing
    assert MEDIA_FILE_FILENAME_PARENT_INDEX_NAME in set(collection.index_information())

    try:
        yield
    finally:
        for index_name in built:
            collection.drop_index(index_name)
