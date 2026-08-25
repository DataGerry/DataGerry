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
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from gridfs.grid_file import GridOutCursor
from gridfs.errors import NoFile

from cmdb.database import DatabaseGridFS, MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager

from cmdb.interface.rest_api.responses import GridFsResponse
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file import FileMetadata

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
    Manager class for handling MediaFile objects in a MongoDB GridFS.

    Provides CRUD operations (Create, Read, Update, Delete)
    for managing media files and their metadata.
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

        Args:
            metadata (dict): Filter criteria for locating the file
            blob (bool, optional): If True, returns the raw binary content instead of metadata

        Returns:
            dict | bytes | None: The file's metadata, raw content, or None if not found
        """
        try:
            result = self.fs.get_last_version(**metadata)

            return result.read() if blob else result._file
        except NoFile:
            return None
        except Exception as err:
            LOGGER.debug("[get_file] Exception: %s, ErrorType: %s",err, type(err))
            return None


    # params (limit/skip/sort) are not yet applied to the GridFS query - see discussion backlog #1
    def get_many_media_files(self, metadata: dict, **params: dict) -> GridFsResponse:  # pylint: disable=unused-argument
        """
        Retrieves multiple media files matching the given metadata

        Args:
            metadata (dict): Filter criteria
            **params (dict): Additional query parameters (e.g., sort, limit)

        Returns:
            GridFsResponse: Object containing list of MediaFiles and the total record count

        Raises:
            MediaFileManagerGetError: If retrieval fails
        """
        try:
            results: list[dict[str, Any]] = []

            iterator: GridOutCursor = self.fs.find(filter=metadata)#**params)
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

        Returns:
            bool: True if file exists, otherwise False
        """
        return self.fs.exists(**filter_metadata)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_file(self, data: dict) -> dict:
        """
        Updates metadata for an existing media file

        Args:
            data (dict): Updated data dictionary, must include 'public_id'

        Returns:
            dict: The updated file data

        Raises:
            MediaFileManagerUpdateError: If the update fails
        """
        try:
            data['uploadDate'] = datetime.now(timezone.utc)
            # GridFS stores file documents in the '<collection>.files' collection
            self.update(criteria={'public_id': data['public_id']}, data=data,
                        collection=f"{MediaFile.COLLECTION}.files")

            return data
        except Exception as err:
            raise MediaFileManagerUpdateError(f"Could not update file. Error: {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_file(self, public_id: int) -> bool:
        """
        Deletes a media file by its public ID

        Args:
            public_id (int): The public ID of the media file

        Raises:
            MediaFileManagerDeleteError: If deletion fails

        Returns:
            bool: True if successfully deleted
        """
        try:
            file_id = self.fs.get_last_version(**{'public_id': public_id})._id
            self.fs.delete(file_id)

            return True
        except Exception as err:
            # reference public_id (always bound) - file_id may be unset if get_last_version failed
            raise MediaFileManagerDeleteError(f'Could not delete file with ID: {public_id}') from err
