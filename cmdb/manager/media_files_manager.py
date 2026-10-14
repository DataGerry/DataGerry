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

A folder is deleted with its whole subtree in two steps: `collect_subtree` reads it one level per query, and
`delete_subtree` removes it level by level, deepest first, a batch per level through the shared
``gridfs_helper.delete_gridfs_files`` - GridFS itself only deletes one file at a time

A deleted CmdbObject is detached from its attachments by `detach_objects`: its id leaves every file's
`metadata.reference`, and the files stay in the library - what the attachment dialog's own "remove" does
"""
from logging import Logger, getLogger
from typing import Any

from gridfs.grid_file import GridOut, GridOutCursor
from gridfs.errors import NoFile

from cmdb.database import DatabaseGridFS, MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.gridfs_helper import delete_gridfs_files
from cmdb.utils import Builder

from cmdb.framework.results import IterationResult
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library import build_media_file_metadata
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_REFERENCE_PATH,
    MEDIA_FILE_REFERENCE_TYPE_PATH,
    OBJECT_REFERENCE_TYPE,
    MediaFileKey,
)

from cmdb.errors.database import DocumentUpdateError
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.media_files_manager import (
    MediaFileManagerGetError,
    MediaFileManagerInsertError,
    MediaFileManagerUpdateError,
    MediaFileManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The GridFS collection of the media library's file documents; their chunks are deleted through
# ``gridfs_helper.delete_gridfs_files``, which names the chunk collection itself
MEDIA_FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'

# What a subtree walk reads of each entry: its GridFS _id (what the delete removes) and its public_id (what its
# children name as their parent)
SUBTREE_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 1, MediaFileKey.PUBLIC_ID.value: 1}

# The name each entry of a file's reference list goes by inside the detach update's $filter
REFERENCE_ENTRY_VARIABLE: str = 'reference'


def build_detach_objects_criteria(object_ids: list[int]) -> dict[str, Any]:
    """
    Builds the filter of the files attached to any of the given CmdbObjects

    ``$in`` on `metadata.reference` matches a reference stored as one id and one stored as a list alike

    Args:
        object_ids (list[int]): public_ids of the CmdbObjects

    Returns:
        dict[str, Any]: The filter
    """
    return {
        MEDIA_FILE_REFERENCE_TYPE_PATH: OBJECT_REFERENCE_TYPE,
        MEDIA_FILE_REFERENCE_PATH: {'$in': object_ids},
    }


def build_detach_objects_update(object_ids: list[int]) -> list[dict[str, Any]]:
    """
    Builds the update pipeline taking the given CmdbObjects' ids out of a file's `metadata.reference`

    A reference is stored as one id (an upload) or a list of ids (a library file attached to several objects), and
    ``$pull`` refuses a value that is no array - so the pipeline reads the reference as a list either way and keeps
    every entry that is not one of the ids. A file referencing nothing else is left with an empty list, the state the
    attachment dialog's own "remove" leaves

    Args:
        object_ids (list[int]): public_ids of the CmdbObjects to detach

    Returns:
        list[dict[str, Any]]: The update pipeline
    """
    reference: str = f'${MEDIA_FILE_REFERENCE_PATH}'

    return [Builder.set_({
        MEDIA_FILE_REFERENCE_PATH: {
            '$filter': {
                'input': {'$cond': [{'$isArray': reference}, reference, [reference]]},
                'as': REFERENCE_ENTRY_VARIABLE,
                'cond': {'$not': [{'$in': [f'$${REFERENCE_ENTRY_VARIABLE}', object_ids]}]},
            },
        },
    })]

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

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
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

    def insert_file(self, data: Any, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Inserts a new media file into GridFS

        The metadata is normalised by `build_media_file_metadata` before it is stored: the file ends up
        carrying every key the media library declares and nothing else, whatever the caller passed in

        Args:
            data (Any): The file-like object containing the media data
            metadata (dict[str, Any]): Metadata describing the media file, e.g. its author, folder and reference

        Returns:
            dict[str, Any]: The inserted MediaFile document

        Raises:
            MediaFileManagerInsertError: If the file could not be inserted
        """
        try:
            with self.fs.new_file(filename=data.filename) as media_file:
                media_file.write(data)
                media_file.public_id = self.get_new_media_file_id()
                media_file.metadata = build_media_file_metadata(metadata)

            return media_file._file
        except Exception as err:
            raise MediaFileManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_media_file_id(self) -> int:
        """
        Generates a new public ID for a MediaFile

        Returns:
            int: A new unique public_id
        """
        return self.get_next_public_id(inc_id=True)


    def get_file(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """
        Retrieves a media file's document by its metadata

        `None` means the file is genuinely ABSENT and nothing else: a storage failure is raised, so a
        caller that maps None onto a 404 cannot turn a database outage into "not found"

        Args:
            metadata (dict[str, Any]): Filter criteria for locating the file

        Raises:
            MediaFileManagerGetError: If the lookup failed

        Returns:
            dict[str, Any] | None: The file's document, or None when no such file exists
        """
        grid_out: GridOut | None = self.open_file(metadata)

        return grid_out._file if grid_out is not None else None


    def open_file(self, metadata: dict[str, Any]) -> GridOut | None:
        """
        Opens a media file for reading, without reading its content

        The returned `GridOut` reads the content chunk by chunk (`readchunk`), which is what lets the
        download route stream a file of any size instead of holding all of it in memory. `None` means
        the file is absent, as for `get_file`

        Args:
            metadata (dict[str, Any]): Filter criteria for locating the file

        Raises:
            MediaFileManagerGetError: If the lookup failed

        Returns:
            GridOut | None: The open file, or None when no such file exists
        """
        try:
            return self.fs.get_last_version(**metadata)
        except NoFile:
            return None
        except Exception as err:
            LOGGER.error("[open_file] Exception: %s. Type: %s", err, type(err), exc_info=True)
            raise MediaFileManagerGetError(err) from err


    def get_many_media_files(
            self,
            metadata: dict[str, Any],
            limit: int = 0,
            skip: int = 0,
            sort: list[tuple[str, int]] | None = None,
    ) -> IterationResult[dict[str, Any]]:
        """
        Retrieves the media files matching the given metadata, one page of them when asked

        Paging and sorting are applied in the GridFS query itself, so only the page is read. ``limit`` 0
        means every match - what the unpaged list callers rely on - and in that case ``total`` is simply the
        number read; a cut page is counted separately, with the
        same filter, so ``total`` is always the number of matching files

        Args:
            metadata (dict[str, Any]): Filter criteria
            limit (int): Maximum number of files to return; 0 for all. Defaults to 0
            skip (int): Number of matching files to skip. Defaults to 0
            sort (list[tuple[str, int]] | None): ``(key, direction)`` pairs; None keeps the storage
                order. Defaults to None

        Raises:
            MediaFileManagerGetError: If retrieval fails

        Returns:
            IterationResult[dict[str, Any]]: The page of MediaFiles (``results``) and the total number of
                matching files
        """
        try:
            iterator: GridOutCursor = self.fs.find(filter=metadata, skip=skip, limit=limit, sort=sort)
            results: list[dict[str, Any]] = [MediaFile.to_json(MediaFile(**grid._file)) for grid in iterator]

            if not limit and not skip:
                return IterationResult(results, len(results))

            total: int = self.dbm.count(f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}', self.db_name, metadata)

            return IterationResult(results, total)
        except Exception as err:
            raise MediaFileManagerGetError(err) from err


    def file_exists(self, filter_metadata: dict[str, Any]) -> bool:
        """
        Checks whether a media file exists with the given metadata

        Args:
            filter_metadata (dict[str, Any]): Metadata to filter files

        Raises:
            MediaFileManagerGetError: If the existence check failed

        Returns:
            bool: True if file exists, otherwise False
        """
        try:
            return self.fs.exists(**filter_metadata)
        except Exception as err:
            raise MediaFileManagerGetError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_file(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Updates the stored document of an existing media file

        Writes the given data onto the file document addressed by its `public_id`. `uploadDate` is
        NOT touched: it is GridFS's record of when the content was stored, so renaming a file or moving
        it to another folder must not make it look freshly uploaded. The caller's dict is left alone -
        the write goes through a copy

        Args:
            data (dict[str, Any]): Updated data dictionary, must include 'public_id'

        Raises:
            MediaFileManagerUpdateError: If the update fails or `public_id` is missing

        Returns:
            dict[str, Any]: The data that was written
        """
        try:
            # A copy, so a caller that reuses its dict does not receive our edits back
            update_data: dict[str, Any] = dict(data)
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
            raise MediaFileManagerDeleteError(f'Could not delete file with ID: {public_id}: {err}') from err

        try:
            self.fs.delete(file_id)

            return True
        except Exception as err:
            raise MediaFileManagerDeleteError(f'Could not delete file with ID: {public_id}: {err}') from err


    def collect_subtree(self, root: dict[str, Any]) -> list[list[dict[str, Any]]]:
        """
        Reads a MediaFile and everything beneath it, one level per query

        Each level is ONE read - every entry whose parent is any entry of the level above (``$in``, served by the
        parent index) - so the cost follows the depth of the tree, not the number of entries in it. The children of
        every entry are asked for, not only of the folders: an entry stored under a non-folder before the write
        contract refused it would otherwise outlive its parent. An entry already collected is never collected again,
        so a folder stored inside its own subtree ends the walk instead of looping

        Args:
            root (dict[str, Any]): The stored document of the entry to start from (carries its ``_id`` and public_id)

        Raises:
            MediaFileManagerGetError: If a level could not be read

        Returns:
            list[list[dict[str, Any]]]: The levels, the root's first; each entry is its ``_id`` and public_id
        """
        public_id_key: str = MediaFileKey.PUBLIC_ID.value
        root_entry: dict[str, Any] = {MONGO_ID_FIELD: root[MONGO_ID_FIELD], public_id_key: root[public_id_key]}
        levels: list[list[dict[str, Any]]] = [[root_entry]]
        collected: set[int] = {root_entry[public_id_key]}

        while True:
            parent_ids: list[int] = [entry[public_id_key] for entry in levels[-1]]

            try:
                children: list[dict[str, Any]] = self.get_many_from_other_collection(
                    MEDIA_FILES_COLLECTION,
                    projection=SUBTREE_PROJECTION,
                    criteria={MEDIA_FILE_PARENT_PATH: {'$in': parent_ids}},
                )
            except BaseManagerGetError as err:
                LOGGER.error("[collect_subtree] BaseManagerGetError: %s", err)
                raise MediaFileManagerGetError(err) from err

            level: list[dict[str, Any]] = [
                child for child in children if child.get(public_id_key) not in collected
            ]

            if not level:
                return levels

            collected.update(child[public_id_key] for child in level)
            levels.append(level)


    def delete_subtree(self, levels: list[list[dict[str, Any]]]) -> int:
        """
        Deletes a collected subtree level by level, deepest first, a batch per level

        Per level: one batch through ``gridfs_helper.delete_gridfs_files`` - the chunks, then the file documents, by
        ``_id`` - instead of a lookup and two deletes per file. The order of the levels makes a failure part-way
        leave a CONNECTED tree: the levels already removed are the deepest, so every entry still stored hangs from a
        folder that is still there, and the request can be repeated. Within a level the chunks go first, so a
        failure between the two leaves file documents without content, which the repeated delete finds and
        removes - never chunks nothing would find again

        Args:
            levels (list[list[dict[str, Any]]]): The subtree as ``collect_subtree`` answered it

        Raises:
            MediaFileManagerDeleteError: If a level could not be deleted - the levels below it are gone, it and the
                levels above it are not

        Returns:
            int: How many file documents were deleted
        """
        deleted: int = 0

        for level in reversed(levels):
            try:
                deleted += delete_gridfs_files(
                    self, MediaFile.COLLECTION, [entry[MONGO_ID_FIELD] for entry in level],
                )
            except BaseManagerDeleteError as err:
                LOGGER.error("[delete_subtree] BaseManagerDeleteError: %s", err)
                raise MediaFileManagerDeleteError(err) from err

        return deleted


    def detach_objects(self, object_ids: list[int]) -> int:
        """
        Takes deleted CmdbObjects' ids out of every file attached to them, keeping the files

        One update of every file whose `metadata.reference` names any of the ids (``build_detach_objects_criteria``,
        ``build_detach_objects_update``). The files stay in the library: a file can be attached to several objects and
        filed in a folder, and the library cannot tell an upload from a library file attached later. Written to the
        `.files` collection by name - this manager's own collection is the GridFS bucket, which holds no document

        Args:
            object_ids (list[int]): public_ids of the deleted CmdbObjects

        Raises:
            MediaFileManagerUpdateError: If the update failed

        Returns:
            int: How many files were changed
        """
        if not object_ids:
            return 0

        try:
            return self.dbm.update_many_raw(
                MEDIA_FILES_COLLECTION,
                self.db_name,
                build_detach_objects_criteria(object_ids),
                build_detach_objects_update(object_ids),
            ).modified_count
        except DocumentUpdateError as err:
            LOGGER.error("[detach_objects] DocumentUpdateError: %s", err)
            raise MediaFileManagerUpdateError(err) from err
