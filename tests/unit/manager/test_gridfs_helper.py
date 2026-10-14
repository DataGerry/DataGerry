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
Unit tests for cmdb.manager.gridfs_helper.delete_gridfs_files

Pinned: the chunks of the batch go first, then the file documents, both by `_id` in one delete each; the answer is the
file documents' count; an empty batch deletes nothing; a failure on the file documents comes after the chunks went
"""
from unittest.mock import MagicMock, call

import pytest

from cmdb.manager.gridfs_helper import delete_gridfs_files
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

BUCKET: str = 'test.bucket'
FILE_IDS: list[str] = ['oid-1', 'oid-2']
DELETED_DOCUMENTS: int = 2
DELETED_CHUNKS: int = 7


def _manager() -> MagicMock:
    """A manager whose chunk delete and document delete answer different counts"""
    manager = MagicMock()
    manager.delete_many_from_other_collection.side_effect = [
        MagicMock(deleted_count=DELETED_CHUNKS), MagicMock(deleted_count=DELETED_DOCUMENTS),
    ]

    return manager


def test_the_chunks_go_before_the_file_documents() -> None:
    """One delete each, by the file ids"""
    manager = _manager()

    delete_gridfs_files(manager, BUCKET, FILE_IDS)

    assert manager.delete_many_from_other_collection.call_args_list == [
        call(f'{BUCKET}.chunks', {'files_id': {'$in': FILE_IDS}}),
        call(f'{BUCKET}.files', {'_id': {'$in': FILE_IDS}}),
    ]


def test_the_answer_counts_the_file_documents() -> None:
    """Not the chunks"""
    assert delete_gridfs_files(_manager(), BUCKET, FILE_IDS) == DELETED_DOCUMENTS


def test_an_empty_batch_deletes_nothing() -> None:
    """No call at all"""
    manager = _manager()

    assert delete_gridfs_files(manager, BUCKET, []) == 0
    manager.delete_many_from_other_collection.assert_not_called()


def test_a_failed_document_delete_comes_after_the_chunks() -> None:
    """The documents stay to be found again by a repeated delete"""
    manager = MagicMock()
    failure = BaseManagerDeleteError('db')
    manager.delete_many_from_other_collection.side_effect = [MagicMock(deleted_count=DELETED_CHUNKS), failure]

    with pytest.raises(BaseManagerDeleteError) as caught:
        delete_gridfs_files(manager, BUCKET, FILE_IDS)

    assert caught.value is failure
    assert manager.delete_many_from_other_collection.call_count == len(FILE_IDS)
