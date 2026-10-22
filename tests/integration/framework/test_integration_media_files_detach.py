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
Integration tests for MediaFilesManager.detach_objects and gridfs_helper.delete_gridfs_files against a real MongoDB

What MongoDB makes of the detach pipeline: a reference stored as one id and one stored as a list both lose exactly the
detached ids and become lists; a list keeps its other entries, in order, and anything that is no id; another reference
kind and an unrelated file are not matched. And the batch delete really removes the files and their chunks
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import MediaFilesManager
from cmdb.manager.gridfs_helper import delete_gridfs_files
from cmdb.manager.media_files_manager import MEDIA_FILES_COLLECTION
from cmdb.framework.media_library.media_file import MediaFile
# -------------------------------------------------------------------------------------------------------------------- #

DETACHED_ID: int = 88801
SECOND_DETACHED_ID: int = 88802
KEPT_ID: int = 88803

SCALAR_FILE_ID: int = 88811
LIST_FILE_ID: int = 88812
MIXED_FILE_ID: int = 88813
OTHER_KIND_FILE_ID: int = 88814
UNRELATED_FILE_ID: int = 88815
DELETED_FILE_ID: int = 88816
FILE_IDS: list[int] = [SCALAR_FILE_ID, LIST_FILE_ID, MIXED_FILE_ID, OTHER_KIND_FILE_ID, UNRELATED_FILE_ID,
                       DELETED_FILE_ID]
LEGACY_ENTRY: str = 'not-an-id'
CHUNKS_PER_FILE: int = 3


def _file(public_id: int, reference: Any, reference_type: str = 'object') -> dict[str, Any]:
    """A stored media file document"""
    return {'public_id': public_id, 'filename': f'detach-{public_id}.txt',
            'metadata': {'reference': reference, 'reference_type': reference_type}}


@pytest.fixture(name='files')
def fixture_files(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded file documents, purged before and after"""
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    files.delete_many({'public_id': {'$in': FILE_IDS}})
    files.insert_many([
        _file(SCALAR_FILE_ID, DETACHED_ID),
        _file(LIST_FILE_ID, [KEPT_ID, DETACHED_ID, SECOND_DETACHED_ID]),
        _file(MIXED_FILE_ID, [DETACHED_ID, LEGACY_ENTRY]),
        _file(OTHER_KIND_FILE_ID, DETACHED_ID, 'report'),
        _file(UNRELATED_FILE_ID, KEPT_ID),
    ])

    yield files

    files.delete_many({'public_id': {'$in': FILE_IDS}})


def _references(files: Any) -> dict[int, Any]:
    """file id -> its stored reference"""
    return {document['public_id']: document['metadata']['reference']
            for document in files.find({'public_id': {'$in': FILE_IDS}})}


def test_detach_takes_exactly_the_ids_out(files, database_manager: MongoDatabaseManager) -> None:
    """Both shapes become lists; the rest is untouched"""
    changed = MediaFilesManager(database_manager).detach_objects([DETACHED_ID, SECOND_DETACHED_ID])

    assert changed == 3
    assert _references(files) == {
        SCALAR_FILE_ID: [],
        LIST_FILE_ID: [KEPT_ID],
        MIXED_FILE_ID: [LEGACY_ENTRY],
        OTHER_KIND_FILE_ID: DETACHED_ID,
        UNRELATED_FILE_ID: KEPT_ID,
    }


def test_a_second_detach_changes_nothing(files, database_manager: MongoDatabaseManager) -> None:
    """Re-run safe: no file names the ids any more"""
    manager = MediaFilesManager(database_manager)
    manager.detach_objects([DETACHED_ID])
    first = _references(files)

    assert manager.detach_objects([DETACHED_ID]) == 0
    assert _references(files) == first


def test_the_batch_delete_removes_the_files_and_their_chunks(database_manager: MongoDatabaseManager,
                                                             database_name: str) -> None:
    """Through any manager of the database"""
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    chunks = database_manager.get_collection(f'{MediaFile.COLLECTION}.chunks', database_name)
    document_id = files.insert_one(_file(DELETED_FILE_ID, None)).inserted_id
    chunks.insert_many([{'files_id': document_id, 'n': index} for index in range(CHUNKS_PER_FILE)])

    try:
        assert delete_gridfs_files(MediaFilesManager(database_manager), MediaFile.COLLECTION, [document_id]) == 1
        assert files.count_documents({'_id': document_id}) == 0
        assert chunks.count_documents({'files_id': document_id}) == 0
    finally:
        files.delete_many({'_id': document_id})
        chunks.delete_many({'files_id': document_id})
