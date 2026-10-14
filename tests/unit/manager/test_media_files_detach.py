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
Unit tests for MediaFilesManager.detach_objects and its two builders

Pinned: only files of reference kind 'object' naming one of the ids are matched; the update reads a reference as a
list whether it is one id or several and keeps every other entry; the write names the `.files` collection, not the
manager's bucket; nothing is written for no ids; a database failure is raised as the manager's update error carrying
it. What MongoDB makes of the pipeline is the integration test's
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.media_files_manager import (
    MEDIA_FILES_COLLECTION,
    MediaFilesManager,
    build_detach_objects_criteria,
    build_detach_objects_update,
)
from cmdb.errors.database import DocumentUpdateError
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_IDS: list[int] = [41, 42]
DATABASE_NAME: str = 'cmdb-unit'
MODIFIED: int = 3


def _manager() -> MagicMock:
    """A MediaFilesManager stand-in over a mocked database manager"""
    manager = MagicMock(spec=MediaFilesManager)
    manager.db_name = DATABASE_NAME
    manager.dbm = MagicMock()
    manager.dbm.update_many_raw.return_value = MagicMock(modified_count=MODIFIED)

    return manager


def test_the_criteria_match_object_attachments_naming_an_id() -> None:
    """The reference kind and the ids"""
    assert build_detach_objects_criteria(OBJECT_IDS) == {
        'metadata.reference_type': 'object',
        'metadata.reference': {'$in': OBJECT_IDS},
    }


def test_the_update_reads_the_reference_as_a_list_and_keeps_the_other_entries() -> None:
    """One $set stage filtering the reference"""
    assert build_detach_objects_update(OBJECT_IDS) == [{'$set': {
        'metadata.reference': {
            '$filter': {
                'input': {'$cond': [
                    {'$isArray': '$metadata.reference'}, '$metadata.reference', ['$metadata.reference'],
                ]},
                'as': 'reference',
                'cond': {'$not': [{'$in': ['$$reference', OBJECT_IDS]}]},
            },
        },
    }}]


def test_detach_writes_the_files_collection_once() -> None:
    """By name - the manager's own collection is the bucket"""
    manager = _manager()

    assert MediaFilesManager.detach_objects(manager, OBJECT_IDS) == MODIFIED

    manager.dbm.update_many_raw.assert_called_once_with(
        MEDIA_FILES_COLLECTION, DATABASE_NAME,
        build_detach_objects_criteria(OBJECT_IDS), build_detach_objects_update(OBJECT_IDS),
    )
    assert MEDIA_FILES_COLLECTION == 'media.libary.files'


def test_no_ids_write_nothing() -> None:
    """Nothing to detach"""
    manager = _manager()

    assert MediaFilesManager.detach_objects(manager, []) == 0
    manager.dbm.update_many_raw.assert_not_called()


def test_a_database_failure_is_the_managers_update_error_carrying_it() -> None:
    """The exception itself, not its text"""
    manager = _manager()
    failure = DocumentUpdateError('db')
    manager.dbm.update_many_raw.side_effect = failure

    with pytest.raises(MediaFileManagerUpdateError) as caught:
        MediaFilesManager.detach_objects(manager, OBJECT_IDS)

    assert caught.value.args[0] is failure
