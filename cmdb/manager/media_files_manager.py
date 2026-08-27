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
Implementation of MediaFilesManager

The one manager that does NOT store its documents the way the rest of the codebase does. A MediaFile is
a GridFS file, so this manager keeps its own `DatabaseGridFS` handle beside the `BaseManager` one and
three consequences follow from that:

* the file DOCUMENTS live in a `.files` sub-collection (`GRIDFS_FILES_SUFFIX`) - `MediaFile.COLLECTION`
  on its own is not an addressable collection, so a metadata update has to target the sub-collection
  explicitly while everything else goes through the GridFS handle
* GridFS exposes the stored document and its id only as `GridIn._file` / `GridOut._id`, which is why
  the class carries a `protected-access` suppression
* `uploadDate` belongs to GridFS and records when the CONTENT was stored. It is not a "last modified"
  stamp, and a metadata-only edit deliberately leaves it untouched

Reads answer `None` only for a file that is genuinely absent; every other failure is raised as a
`MediaFileManager*Error` so a storage problem cannot be mistaken for "not found"
"""
from logging import Logger, getLogger
from typing import Any

from gridfs.grid_file import GridOutCursor
from gridfs.errors import NoFile

from cmdb.database import DatabaseGridFS, MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager

from cmdb.interface.rest_api.responses import GridFsResponse
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file import FileMetadata
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MediaFileKey,
)

from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
    MediaFileManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               MediaFilesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #


class MediaFilesManager(BaseManager):
    """
    Manager for MediaFiles, stored as GridFS files rather than plain documents

    Extends BaseManager, but only the public_id counter is inherited behaviour: every read and write
    below goes through the GridFS handle (`self.fs`) instead of the collection helpers, and the one
    exception - the metadata update - has to name the `.files` sub-collection itself. See the module
    docstring for why

    Extends: BaseManager
    """
    # GridFS exposes the underlying file document / id only via GridIn/GridOut ._file / ._id
    # pylint: disable=protected-access

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None):
        """
        Initializes the MediaFilesManager with a database manager

        Args:
            dbm (MongoDatabaseManager): The database manager instance
            database (str | None): Specific database name to switch to
        """
        target_db = database if database else dbm.db_name
        self.fs = DatabaseGridFS(dbm.connector.get_database(target_db), MediaFile.COLLECTION)
        super().__init__(MediaFile.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_file(self, data: Any, metadata: dict) -> dict:
        """
        Inserts a new media file into GridFS

        Args:
            data (Any): The file-like object containing the media data
            metadata (dict): Metadata describing the media file

        Returns:
            dict: The inserted MediaFile document

        Raises:
            MediaFileManagerInsertError: If the file could not be inserted
        """
        try:
            with self.fs.new_file(filename=data.filename) as media_file:
                media_file.write(data)
                media_file.public_id = self.get_new_media_file_id()
                media_file.metadata = FileMetadata.to_json(FileMetadata(**metadata))

            return media_file._file
        except Exception as err:
            raise MediaFileManagerInsertError(str(err)) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_media_file_id(self) -> int:
        """
        Generates a new public ID for a MediaFile

        Returns:
            int: A new unique public_id
        """
        return self.get_next_public_id(inc_id=True)


    def get_file(self, metadata: dict, blob: bool = False) -> dict | bytes | None:
        """
        Retrieves a media file by its metadata

        `None` means the file is genuinely ABSENT and nothing else: a storage failure is raised, so a
        caller that maps None onto a 404 cannot turn a database outage into "not found"

        Args:
            metadata (dict): Filter criteria for locating the file
            blob (bool, optional): If True, returns the raw binary content instead of the document

        Raises:
            MediaFileManagerGetError: If the lookup or the read failed

        Returns:
            dict | bytes | None: The file's document, its raw content, or None when no such file exists
        """
        try:
            result = self.fs.get_last_version(**metadata)

            return result.read() if blob else result._file
        except NoFile:
            return None
        except Exception as err:
            LOGGER.error("[get_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
            raise MediaFileManagerGetError(str(err)) from err


    def get_many_media_files(  # pylint: disable=unused-argument
            self, metadata: dict, **params: dict,
    ) -> GridFsResponse:
        """
        Retrieves every media file matching the given metadata

        **`params` is accepted and ignored.** The route's `limit` / `skip` / `sort` are not applied to
        the GridFS query, so this always loads every matching file and reports `total` as the number
        returned rather than a real count - recorded as discussion-backlog #48, which also covers why
        re-enabling it needs `GridFsResponse.total` to change

        Args:
            metadata (dict): Filter criteria
            **params (dict): Additional query parameters (sort, limit, skip) - currently ignored

        Raises:
            MediaFileManagerGetError: If retrieval fails

        Returns:
            GridFsResponse: The matching MediaFiles and how many were returned
        """
        try:
            results: list[dict[str, Any]] = []

            iterator: GridOutCursor = self.fs.find(filter=metadata)
            for grid in iterator:
                results.append(MediaFile.to_json(MediaFile(**grid._file)))

            return GridFsResponse(results, len(results))
        except Exception as err:
            raise MediaFileManagerGetError(str(err)) from err


    def file_exists(self, filter_metadata: dict) -> bool:
        """
        Checks whether a media file exists with the given metadata

        Args:
            filter_metadata (dict): Metadata to filter files

        Raises:
            MediaFileManagerGetError: If the existence check failed

        Returns:
            bool: True if file exists, otherwise False
        """
        try:
            return self.fs.exists(**filter_metadata)
        except Exception as err:
            raise MediaFileManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_file(self, data: dict) -> dict:
        """
        Updates the stored document of an existing media file

        Writes the given data onto the file document addressed by its `public_id`. `uploadDate` is
        NOT touched: it is GridFS's record of when the content was stored, so renaming a file or moving
        it to another folder must not make it look freshly uploaded. The caller's dict is left alone -
        the write goes through a copy

        Args:
            data (dict): Updated data dictionary, must include 'public_id'

        Raises:
            MediaFileManagerUpdateError: If the update fails or `public_id` is missing

        Returns:
            dict: The data that was written
        """
        try:
            # A copy, so a caller that reuses its dict does not receive our edits back
            update_data: dict = dict(data)
            update_data.pop(MediaFileKey.UPLOAD_DATE.value, None)

            # GridFS keeps the addressable file documents in the '.files' sub-collection
            self.update(
                criteria={MediaFileKey.PUBLIC_ID.value: update_data[MediaFileKey.PUBLIC_ID.value]},
                data=update_data,
                collection=f"{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}",
            )

            return update_data
        except Exception as err:
            raise MediaFileManagerUpdateError(f"Could not update file. Error: {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_file(self, public_id: int) -> bool:
        """
        Deletes a media file by its public ID

        A file that does not exist is reported as False rather than raised: it is the state the caller
        wanted, and it is not a storage failure. Anything that actually goes wrong is raised, so the
        two are distinguishable - which they were not while `NoFile` and a failed delete produced the
        same error

        Args:
            public_id (int): The public ID of the media file

        Raises:
            MediaFileManagerDeleteError: If the deletion failed

        Returns:
            bool: True when a file was deleted, False when no file carries that public_id
        """
        try:
            file_id = self.fs.get_last_version(**{MediaFileKey.PUBLIC_ID.value: public_id})._id
        except NoFile:
            return False
        except Exception as err:
            # reference public_id (always bound) - file_id is unset when get_last_version failed
            raise MediaFileManagerDeleteError(f'Could not delete file with ID: {public_id}') from err

        try:
            self.fs.delete(file_id)

            return True
        except Exception as err:
            raise MediaFileManagerDeleteError(f'Could not delete file with ID: {public_id}') from err
