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

* the file DOCUMENTS live in a `.files` sub-collection (`MEDIA_FILES_COLLECTION`) - `MediaFile.COLLECTION`
  on its own is not an addressable collection, so a read or write of the documents themselves targets the
  sub-collection explicitly while the content goes through the GridFS handle
* GridFS exposes the stored document only as `GridIn._file` / `GridOut._file`, which is why the class
  carries a `protected-access` suppression
* `uploadDate` belongs to GridFS and records when the CONTENT was stored. It is not a "last modified"
  stamp, and a metadata-only edit deliberately leaves it untouched

Reads answer `None` only for a file that is genuinely absent; every other failure is raised as a
`MediaFileManager*Error` so a storage problem cannot be mistaken for "not found". A GridFS call goes to the
driver directly, so its failure is sorted by ``gridfs_helper``: a lost server or a lock timeout is raised
unwrapped, as the transient error the app answers 503 / 423, and only the driver's own errors are caught - a
programming error reaches the route as itself

A file is written with its public_id and metadata already on it, and a write that fails part-way is aborted,
so no chunks without a file document are left behind. Uploading over an existing entry replaces it in three
steps (`replace_file`): the replacement is stored under a name of its own, the old entry is deleted, and the
replacement takes the name. Every step leaves the content findable: before the delete both entries are stored,
after it the replacement is

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
from cmdb.manager.gridfs_helper import (
    GRIDFS_DRIVER_ERRORS,
    GRIDFS_WRITE_ERRORS,
    delete_gridfs_files,
    gridfs_failure,
    raise_gridfs_insert_failure,
)
from cmdb.utils import Builder

from cmdb.framework.results import IterationResult
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library import build_media_file_metadata, replacement_staging_name
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_FILES_SUFFIX,
    MEDIA_FILE_FOLDER_PATH,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_REFERENCE_PATH,
    MEDIA_FILE_REFERENCE_TYPE_PATH,
    OBJECT_REFERENCE_TYPE,
    MediaFileKey,
)

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
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

# What a delete reads of the entry: only the GridFS _id it removes
FILE_ID_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 1}

# What the unique-name check reads of a folder's entries: only their names
FILENAME_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 0, MediaFileKey.FILENAME.value: 1}

# The field the folder read collects the public_ids of every folder above the asked one under
ANCESTOR_IDS_FIELD: str = 'ancestor_ids'

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


def build_folder_ancestry_pipeline(public_id: int) -> list[dict[str, Any]]:
    """
    Builds the aggregation reading one entry together with the public_ids of every folder above it

    ``$graphLookup`` follows `metadata.parent` to `public_id` until the library root, so the whole ancestry is one
    query however deep the entry sits; MongoDB stops at an entry it has already visited, so a loop already stored
    in the tree ends the walk instead of repeating it

    Args:
        public_id (int): public_id of the entry to read

    Returns:
        list[dict[str, Any]]: The pipeline; its one result carries the entry's public_id, its folder flag and
            ``ANCESTOR_IDS_FIELD``
    """
    ancestors_field: str = 'ancestors'

    return [
        Builder.match_({MediaFileKey.PUBLIC_ID.value: public_id}),
        Builder.graph_lookup_(
            MEDIA_FILES_COLLECTION,
            f'${MEDIA_FILE_PARENT_PATH}',
            MEDIA_FILE_PARENT_PATH,
            MediaFileKey.PUBLIC_ID.value,
            ancestors_field,
        ),
        Builder.project_({
            MONGO_ID_FIELD: 0,
            MediaFileKey.PUBLIC_ID.value: 1,
            MEDIA_FILE_FOLDER_PATH: 1,
            ANCESTOR_IDS_FIELD: f'${ancestors_field}.{MediaFileKey.PUBLIC_ID.value}',
        }),
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               MediaFilesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #


class MediaFilesManager(BaseManager):
    """
    Manager for MediaFiles, stored as GridFS files rather than plain documents

    Extends BaseManager: the content goes through the GridFS handle (`self.fs`), the file documents are read
    and written through the collection helpers, naming the `.files` sub-collection (`MEDIA_FILES_COLLECTION`)
    themselves. See the module docstring for why

    Extends: BaseManager
    """
    # GridFS exposes the underlying file document only via GridIn/GridOut ._file
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
            data (Any): The file-like object containing the media data, carrying its `filename`
            metadata (dict[str, Any]): Metadata describing the media file, e.g. its author, folder and reference

        Raises:
            MediaFileManagerInsertError: If the file could not be inserted; a refusal of the unique
                (filename, metadata.parent) index carries a `DocumentInsertDuplicateKeyError` in its cause chain
            DocumentLockTimeoutError: If the write ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

        Returns:
            dict[str, Any]: The inserted MediaFile document
        """
        return self._write_file(data, data.filename, self._draw_public_id(), metadata)


    def replace_file(self, data: Any, metadata: dict[str, Any], replaced_id: int) -> dict[str, Any]:
        """
        Stores an upload in place of the entry of the same name in the same folder

        The replacement is a new entry with a public_id of its own, as an insert is. The unique index over
        (filename, metadata.parent) forbids two entries of one name in one folder, so the swap takes three
        steps, ordered so that every failure leaves the content findable:

        1. the replacement is written under ``replacement_staging_name`` - a failure leaves the old entry alone
        2. the old entry is deleted - a failure removes the replacement again and leaves the old entry alone
        3. the replacement takes the name - a failure leaves it stored under the staging name, visible in its
           folder, and the old entry gone

        Args:
            data (Any): The file-like object containing the media data, carrying its `filename`
            metadata (dict[str, Any]): Metadata describing the media file
            replaced_id (int): public_id of the stored entry the upload replaces

        Raises:
            MediaFileManagerInsertError: If the replacement could not be written
            MediaFileManagerDeleteError: If the replaced entry could not be deleted; the replacement is removed
            MediaFileManagerUpdateError: If the replacement could not take the name; it is kept under the
                staging name
            DocumentLockTimeoutError: If a write ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

        Returns:
            dict[str, Any]: The stored replacement, carrying the real name
        """
        public_id: int = self._draw_public_id()
        stored: dict[str, Any] = self._write_file(
            data, replacement_staging_name(data.filename, public_id), public_id, metadata,
        )

        try:
            self.delete_file(replaced_id)
        except MediaFileManagerDeleteError:
            self._discard_staged_replacement(public_id)
            raise

        self.rename_file(public_id, data.filename)
        stored[MediaFileKey.FILENAME.value] = data.filename

        return stored


    def _draw_public_id(self) -> int:
        """
        Takes the public_id the next written file is stored with

        Raises:
            MediaFileManagerInsertError: If the public_id counter could not be read

        Returns:
            int: The consumed public_id
        """
        try:
            return self.get_new_media_file_id()
        except BaseManagerGetError as err:
            raise MediaFileManagerInsertError(err) from err


    def _write_file(self, data: Any, filename: str, public_id: int, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Writes one GridFS file, its public_id and metadata on it from the start

        Both are passed to `new_file`, so they are part of the file document GridFS writes when it closes the file.
        A write that fails is aborted: the chunks written so far and a file document, if one was written, are
        removed. An abort that fails itself is logged and the write's own failure raised

        Args:
            data (Any): The file-like object containing the media data
            filename (str): The name to store the file under
            public_id (int): The file's public_id
            metadata (dict[str, Any]): Metadata describing the media file

        Raises:
            MediaFileManagerInsertError: If the file could not be written
            DocumentLockTimeoutError: If the write ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

        Returns:
            dict[str, Any]: The stored file document
        """
        media_file = self.fs.new_file(
            filename=filename,
            **{
                MediaFileKey.PUBLIC_ID.value: public_id,
                MediaFileKey.METADATA.value: build_media_file_metadata(metadata),
            },
        )

        try:
            media_file.write(data)
            media_file.close()
        except GRIDFS_WRITE_ERRORS as err:
            try:
                media_file.abort()
            except GRIDFS_DRIVER_ERRORS as abort_err:
                LOGGER.error("[_write_file] the failed write of '%s' could not be aborted: %s", filename, abort_err)

            raise_gridfs_insert_failure(err, MEDIA_FILES_COLLECTION, MediaFileManagerInsertError)

        return media_file._file


    def _discard_staged_replacement(self, public_id: int) -> None:
        """
        Removes a replacement whose replaced entry could not be deleted, so only the old entry stays

        Best effort: the delete failed already, so a failure here is logged and the delete's failure is what the
        caller raises. The replacement then stays under its staging name, visible in its folder

        Args:
            public_id (int): public_id of the staged replacement
        """
        try:
            self.delete_file(public_id)
        except MediaFileManagerDeleteError as err:
            LOGGER.error("[replace_file] the staged replacement %s could not be removed: %s", public_id, err)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_media_file_id(self) -> int:
        """
        Generates a new public ID for a MediaFile

        Raises:
            BaseManagerGetError: If the public_id counter could not be read

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
            DocumentLockTimeoutError: If the read ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

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
            DocumentLockTimeoutError: If the read ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

        Returns:
            GridOut | None: The open file, or None when no such file exists
        """
        try:
            return self.fs.get_last_version(**metadata)
        except NoFile:
            return None
        except GRIDFS_DRIVER_ERRORS as err:
            LOGGER.error("[open_file] %s: %s", type(err).__name__, err)
            raise gridfs_failure(err, MediaFileManagerGetError) from err


    def get_folder_ancestry(self, public_id: int) -> dict[str, Any] | None:
        """
        Reads an entry together with the public_ids of every folder above it, in one query

        What a move needs to judge its new parent: whether it is a folder, and whether the moved entry is
        among the folders above it (``build_folder_ancestry_pipeline``)

        Args:
            public_id (int): public_id of the entry

        Raises:
            MediaFileManagerGetError: If the read failed

        Returns:
            dict[str, Any] | None: The entry's public_id, its `metadata.folder` and ``ANCESTOR_IDS_FIELD``; None
                when no entry carries the public_id
        """
        try:
            results: list[dict[str, Any]] = self.aggregate_all(
                build_folder_ancestry_pipeline(public_id), collection=MEDIA_FILES_COLLECTION,
            )
        except BaseManagerIterationError as err:
            LOGGER.error("[get_folder_ancestry] BaseManagerIterationError: %s", err)
            raise MediaFileManagerGetError(err) from err

        return results[0] if results else None


    def get_folder_filenames(self, parent: int | None, excluded_id: int) -> set[str]:
        """
        Reads the names the entries of one folder carry, all but one, in one query

        Args:
            parent (int | None): public_id of the folder; None for the library root
            excluded_id (int): public_id of the entry whose own name does not count

        Raises:
            MediaFileManagerGetError: If the read failed

        Returns:
            set[str]: The names
        """
        try:
            documents: list[dict[str, Any]] = self.get_many_from_other_collection(
                MEDIA_FILES_COLLECTION,
                projection=FILENAME_PROJECTION,
                criteria={
                    MEDIA_FILE_PARENT_PATH: parent,
                    MediaFileKey.PUBLIC_ID.value: {'$ne': excluded_id},
                },
            )
        except BaseManagerGetError as err:
            LOGGER.error("[get_folder_filenames] BaseManagerGetError: %s", err)
            raise MediaFileManagerGetError(err) from err

        return {
            document[MediaFileKey.FILENAME.value] for document in documents
            if isinstance(document.get(MediaFileKey.FILENAME.value), str)
        }


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
            MediaFileManagerGetError: If retrieval fails, or a stored file document can not be read as a
                MediaFile
            DocumentLockTimeoutError: If the read ran into a lock timeout
            DocumentNetworkError: If the database server could not be reached

        Returns:
            IterationResult[dict[str, Any]]: The page of MediaFiles (``results``) and the total number of
                matching files
        """
        try:
            iterator: GridOutCursor = self.fs.find(filter=metadata, skip=skip, limit=limit, sort=sort)
            results: list[dict[str, Any]] = [MediaFile.to_json(MediaFile.from_data(grid._file)) for grid in iterator]
        except GRIDFS_DRIVER_ERRORS as err:
            LOGGER.error("[get_many_media_files] %s: %s", type(err).__name__, err)
            raise gridfs_failure(err, MediaFileManagerGetError) from err
        except (MediaFile.INIT_FROM_DATA_ERROR, MediaFile.TO_JSON_ERROR) as err:
            LOGGER.error("[get_many_media_files] a stored file can not be read: %s", err)
            raise MediaFileManagerGetError(err) from err

        if not limit and not skip:
            return IterationResult(results, len(results))

        try:
            total: int = self.count_from_other_collection(MEDIA_FILES_COLLECTION, metadata)
        except BaseManagerGetError as err:
            LOGGER.error("[get_many_media_files] BaseManagerGetError: %s", err)
            raise MediaFileManagerGetError(err) from err

        return IterationResult(results, total)

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
            MediaFileManagerUpdateError: If `public_id` is missing or the update fails; a refusal of the unique
                (filename, metadata.parent) index carries a `DocumentUpdateDuplicateKeyError` in its cause chain

        Returns:
            dict[str, Any]: The data that was written
        """
        if MediaFileKey.PUBLIC_ID.value not in data:
            raise MediaFileManagerUpdateError(f"Could not update file: no '{MediaFileKey.PUBLIC_ID.value}' given")

        # A copy, so a caller that reuses its dict does not receive our edits back
        update_data: dict[str, Any] = dict(data)
        update_data.pop(MediaFileKey.UPLOAD_DATE.value, None)

        try:
            self.update(
                criteria={MediaFileKey.PUBLIC_ID.value: update_data[MediaFileKey.PUBLIC_ID.value]},
                data=update_data,
                collection=MEDIA_FILES_COLLECTION,
            )
        except BaseManagerUpdateError as err:
            LOGGER.error("[update_file] BaseManagerUpdateError: %s", err)
            raise MediaFileManagerUpdateError(err) from err

        return update_data


    def rename_file(self, public_id: int, filename: str) -> None:
        """
        Gives a stored media file another name, leaving the rest of its document alone

        Args:
            public_id (int): public_id of the file
            filename (str): The new name

        Raises:
            MediaFileManagerUpdateError: If the update failed
        """
        try:
            self.update(
                criteria={MediaFileKey.PUBLIC_ID.value: public_id},
                data={MediaFileKey.FILENAME.value: filename},
                collection=MEDIA_FILES_COLLECTION,
            )
        except BaseManagerUpdateError as err:
            LOGGER.error("[rename_file] BaseManagerUpdateError: %s", err)
            raise MediaFileManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_file(self, public_id: int) -> bool:
        """
        Deletes a media file by its public ID, its chunks first

        A file that does not exist is reported as False rather than raised: it is the state the caller
        wanted, and it is not a storage failure. Anything that actually goes wrong is raised, so the
        two are distinguishable. The file document is read for its `_id` alone, and the delete goes through
        ``gridfs_helper.delete_gridfs_files``: the chunks go before the file document, so a failure between the
        two leaves a file document a repeated delete finds again, never chunks nothing would find

        Args:
            public_id (int): The public ID of the media file

        Raises:
            MediaFileManagerDeleteError: If the deletion failed

        Returns:
            bool: True when a file was deleted, False when no file carries that public_id
        """
        try:
            documents: list[dict[str, Any]] = self.get_many_from_other_collection(
                MEDIA_FILES_COLLECTION,
                limit=1,
                projection=FILE_ID_PROJECTION,
                criteria={MediaFileKey.PUBLIC_ID.value: public_id},
            )

            if not documents:
                return False

            delete_gridfs_files(self, MediaFile.COLLECTION, [documents[0][MONGO_ID_FIELD]])

            return True
        except (BaseManagerGetError, BaseManagerDeleteError) as err:
            LOGGER.error("[delete_file] %s: %s", type(err).__name__, err)
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
            return self.update_many_raw(
                build_detach_objects_criteria(object_ids),
                build_detach_objects_update(object_ids),
                collection=MEDIA_FILES_COLLECTION,
            ).modified_count
        except BaseManagerUpdateError as err:
            LOGGER.error("[detach_objects] BaseManagerUpdateError: %s", err)
            raise MediaFileManagerUpdateError(err) from err
