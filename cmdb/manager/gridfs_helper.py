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
Batch deletion of GridFS files, shared by every caller that removes more than one file at a time

GridFS itself deletes one file per call. A batch is two deletes instead: the chunks of every file first, then the
file documents. The order decides what a failure between the two leaves behind: file documents whose content is
gone, which every caller finds again by reading the file documents and deletes on a repeated run - never chunks
without a file document, which nothing would ever find again
"""
from typing import Any

from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_CHUNK_FILE_KEY,
    GRIDFS_CHUNKS_SUFFIX,
    GRIDFS_FILES_SUFFIX,
)
# -------------------------------------------------------------------------------------------------------------------- #

def delete_gridfs_files(manager: BaseManager, bucket: str, file_ids: list[Any]) -> int:
    """
    Deletes a batch of GridFS files of one bucket, their chunks first

    Args:
        manager (BaseManager): Any manager of the database holding the bucket
        bucket (str): The GridFS bucket name, without the '.files' / '.chunks' suffix
        file_ids (list[Any]): The `_id`s of the file documents to delete

    Raises:
        BaseManagerDeleteError: When the chunks or the file documents could not be deleted - after a failure on
            the file documents, the chunks are already gone

    Returns:
        int: How many file documents were deleted
    """
    if not file_ids:
        return 0

    manager.delete_many_from_other_collection(
        f'{bucket}{GRIDFS_CHUNKS_SUFFIX}', {GRIDFS_CHUNK_FILE_KEY: {'$in': file_ids}},
    )

    return manager.delete_many_from_other_collection(
        f'{bucket}{GRIDFS_FILES_SUFFIX}', {MONGO_ID_FIELD: {'$in': file_ids}},
    ).deleted_count
