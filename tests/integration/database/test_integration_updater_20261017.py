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
Integration tests for updater_20261017 against a real MongoDB

An attachment loses the ids of objects that no longer exist and keeps the ones of objects that do, whether its
reference is one id or a list; another reference kind is not read; no file is deleted; a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261017 import Update20261017
from cmdb.manager.media_files_manager import MEDIA_FILES_COLLECTION
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

LIVING_OBJECT_ID: int = 88901
DELETED_OBJECT_ID: int = 88902
SECOND_DELETED_OBJECT_ID: int = 88903

SCALAR_ORPHAN_FILE_ID: int = 88911
MIXED_LIST_FILE_ID: int = 88912
LIVING_FILE_ID: int = 88913
OTHER_KIND_FILE_ID: int = 88914
FILE_IDS: list[int] = [SCALAR_ORPHAN_FILE_ID, MIXED_LIST_FILE_ID, LIVING_FILE_ID, OTHER_KIND_FILE_ID]


def _file(public_id: int, reference: Any, reference_type: str = 'object') -> dict[str, Any]:
    """A stored media file document"""
    return {'public_id': public_id, 'filename': f'orphan-{public_id}.txt',
            'metadata': {'reference': reference, 'reference_type': reference_type}}


@pytest.fixture(name='files')
def fixture_files(database_manager: MongoDatabaseManager, database_name: str):
    """One living object and four files referencing it and two deleted ones; purged before and after"""
    files = database_manager.get_collection(MEDIA_FILES_COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        files.delete_many({'public_id': {'$in': FILE_IDS}})
        objects.delete_many({'public_id': {'$in': [LIVING_OBJECT_ID, DELETED_OBJECT_ID, SECOND_DELETED_OBJECT_ID]}})

    _purge()
    objects.insert_one({'public_id': LIVING_OBJECT_ID, 'type_id': 1, 'fields': []})
    files.insert_many([
        _file(SCALAR_ORPHAN_FILE_ID, DELETED_OBJECT_ID),
        _file(MIXED_LIST_FILE_ID, [LIVING_OBJECT_ID, DELETED_OBJECT_ID, SECOND_DELETED_OBJECT_ID]),
        _file(LIVING_FILE_ID, LIVING_OBJECT_ID),
        _file(OTHER_KIND_FILE_ID, DELETED_OBJECT_ID, 'report'),
    ])

    yield files

    _purge()


def _references(files: Any) -> dict[int, Any]:
    """file id -> its stored reference"""
    return {document['public_id']: document['metadata']['reference']
            for document in files.find({'public_id': {'$in': FILE_IDS}})}


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261017(database_manager, database_name).start_update()


def test_the_deleted_objects_leave_the_references(files, database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
    """The living object's id stays; every file stays"""
    _run(database_manager, database_name)

    assert _references(files) == {
        SCALAR_ORPHAN_FILE_ID: [],
        MIXED_LIST_FILE_ID: [LIVING_OBJECT_ID],
        LIVING_FILE_ID: LIVING_OBJECT_ID,
        OTHER_KIND_FILE_ID: DELETED_OBJECT_ID,
    }


def test_a_second_run_changes_nothing(files, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    first = _references(files)

    _run(database_manager, database_name)

    assert _references(files) == first
