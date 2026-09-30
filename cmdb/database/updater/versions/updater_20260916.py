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
Database update 20260916: makes a MediaFile's name unique inside its folder

The media library is a tree of GridFS documents, so a file's identity is the pair
`(filename, metadata.parent)` - the same name in two different folders is legal, a clash inside one
folder is not. The upload and update routes already enforce that, by reading the folder first and
renaming a clashing upload to `copy_(n)_<name>`; nothing else did. That check is a read followed by a
write, so two concurrent uploads can both pass it, and three of the library's routes address a file
**by name**, which makes a duplicate an addressing ambiguity rather than a cosmetic one.

`MediaFile.INDEX_KEYS` now declares the unique index that closes it. This migration is what lets that
declaration reach an existing database: it renames whatever duplicates accumulated and then builds the
index.

**The index cannot simply be declared.** Two reasons. A declaration naming `name`, a key no GridFS
document carries, would be a unique index over a uniformly-absent field - letting the collection hold
exactly one file. And nothing would build it:
`MediaFile` is not in `__COLLECTIONS__` and cannot be, because that loop indexes a class's COLLECTION
verbatim while `MediaFile.COLLECTION` is the GridFS *bucket* name; the documents live in
`media.libary.files`. `CollectionValidator.init_media_library_indexes` is the step that now reconciles
it, and index reconciliation is additive and name-based (see `CollectionValidator.ensure_indexes`), so
without this migration the new index would only ever reach a database created from scratch.

**A duplicate is RENAMED, never deleted.** This is the difference from `updater_20260902`, which
de-duplicated extendable options by discarding them: an option is a label, a media file is content a
customer uploaded. The keeper is the lowest public_id - the oldest, and the one an existing
`metadata.reference` is most likely to point at - and every other member is renamed with the
application's own `copy_(n)_` scheme, so what the library shows after the migration is what it would
have shown had the routes caught the clash at upload time.

**Renaming is visible.** `GET /media_library/file/<filename>` and its two siblings address a file by
name, so a caller that hard-coded a duplicated name now reaches the keeper. There is no silent option:
leaving the duplicates means the index never builds and the ambiguity stays.

Re-run safe throughout: the duplicate groups are recomputed from the current collection state on every
call, a name is only taken if nothing in that folder holds it at that moment, an index that is already
correct is left alone, and the version is bumped only after both halves complete.
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import IndexModel

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.framework.media_library.media_file import MediaFile
from cmdb.framework.media_library.media_file_keys import (
    MediaFileKey,
    GRIDFS_FILES_SUFFIX,
    MEDIA_FILE_PARENT_PATH,
    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
    LEGACY_MEDIA_FILE_NAME_INDEX_NAME,
)

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The collection holding the file DOCUMENTS. Frozen here rather than recomputed from the model, because
# a migration records what was done to a database on a given day and must keep doing exactly that
MEDIA_FILES_COLLECTION: str = f'{MediaFile.COLLECTION}{GRIDFS_FILES_SUFFIX}'

# Aggregation output keys of the duplicate-group pipeline
GROUP_IDENTITY_KEY: str = '_id'
GROUP_MEMBERS_KEY: str = 'files'

# Keys carried per group member
MEMBER_ID_KEY: str = 'document_id'
MEMBER_PUBLIC_ID_KEY: str = 'public_id'

# The identity halves, as the pipeline names them inside the group key
IDENTITY_FILENAME_KEY: str = 'filename'
IDENTITY_PARENT_KEY: str = 'parent'

# The document key a rename addresses; always present, unlike public_id
DOCUMENT_ID_KEY: str = '_id'

# The rename scheme the upload and update routes use, so a migrated clash is spelled exactly like one
# the routes would have renamed themselves
COPY_PREFIX_TEMPLATE: str = 'copy_({index})_'

# Sorts a member with no public_id behind every member that has one
MISSING_PUBLIC_ID_SORT_KEY: int = -1

# The 'unique' flag is only present in index_information() output when the index actually is unique
INDEX_UNIQUE_KEY: str = 'unique'

# -------------------------------------------------------------------------------------------------------------------- #

def find_duplicate_file_groups(dbm: MongoDatabaseManager, db_name: str) -> list[dict[str, Any]]:
    """
    Finds every (filename, metadata.parent) pair that more than one MediaFile carries

    Groups the file collection by the identity pair and keeps only the groups holding at least two
    documents, carrying each member's `_id` and public_id so a keeper can be chosen without a second
    read. Documents missing `filename` or a parent group under null, which is deliberate: a unique
    index treats every missing value as the same null, so those collide too and have to be resolved
    here as well

    Args:
        dbm (MongoDatabaseManager): Database manager used for the aggregation
        db_name (str): Name of the database to inspect

    Returns:
        list[dict[str, Any]]: One entry per duplicated identity, each with the group's '_id' (the
            filename/parent pair) and 'files' (a list of {'document_id', 'public_id'} dicts)
    """
    pipeline: list[dict[str, Any]] = [
        {
            '$group': {
                GROUP_IDENTITY_KEY: {
                    IDENTITY_FILENAME_KEY: f'${MediaFileKey.FILENAME.value}',
                    IDENTITY_PARENT_KEY: f'${MEDIA_FILE_PARENT_PATH}',
                },
                GROUP_MEMBERS_KEY: {
                    '$push': {
                        MEMBER_ID_KEY: f'${DOCUMENT_ID_KEY}',
                        MEMBER_PUBLIC_ID_KEY: f'${MediaFileKey.PUBLIC_ID.value}',
                    },
                },
            },
        },
        {
            '$match': {f'{GROUP_MEMBERS_KEY}.1': {'$exists': True}},
        },
    ]

    return list(dbm.aggregate(MEDIA_FILES_COLLECTION, db_name, pipeline))


def select_keeper(files: list[dict[str, Any]]) -> Any:
    """
    Chooses which of several identically-named MediaFiles keeps the name

    The lowest public_id wins: the oldest entry, and the one an existing `metadata.reference` is most
    likely to point at already. A member carrying no public_id sorts behind every member that has one,
    so a malformed document never displaces a well-formed file

    Args:
        files (list[dict[str, Any]]): The duplicate group's members, each with 'document_id' and
            'public_id'

    Returns:
        Any: The '_id' of the file that keeps its name
    """
    def sort_key(member: dict[str, Any]) -> tuple[int, Any]:
        public_id: Any = member.get(MEMBER_PUBLIC_ID_KEY)

        if isinstance(public_id, int):
            return (0, public_id)

        return (1, MISSING_PUBLIC_ID_SORT_KEY)

    return min(files, key=sort_key)[MEMBER_ID_KEY]


def taken_names_in_folder(dbm: MongoDatabaseManager, db_name: str, parent: Any) -> set[str]:
    """
    Reads every filename currently used inside one folder

    Read once per duplicate group so the renaming can pick a free name without a query per attempt,
    and re-read on a later run, which is what keeps the migration re-run safe

    Args:
        dbm (MongoDatabaseManager): Database manager used for the read
        db_name (str): Name of the database owning the collection
        parent (Any): The folder's public_id, or None for the library root

    Returns:
        set[str]: The filenames the folder already holds
    """
    # The projection goes in as a KEYWORD: MongoDatabaseManager.find injects its own when the caller
    # passes none, so a fourth positional argument collides with it
    documents = dbm.find(
        MEDIA_FILES_COLLECTION,
        db_name,
        {MEDIA_FILE_PARENT_PATH: parent},
        projection={MediaFileKey.FILENAME.value: 1},
    )

    return {
        document[MediaFileKey.FILENAME.value] for document in documents
        if isinstance(document.get(MediaFileKey.FILENAME.value), str)
    }


def build_free_name(filename: str, taken: set[str]) -> str:
    """
    Builds the first 'copy_(n)_<name>' the folder does not already hold

    Mirrors `create_attachment_name` in the media-library routes, including that the previous prefix is
    stripped before the next one is applied, so a re-run cannot produce 'copy_(2)_copy_(1)_file.png'

    Args:
        filename (str): The clashing name
        taken (set[str]): The names the folder already holds

    Returns:
        str: A name no document in that folder carries
    """
    index: int = 0
    candidate: str = filename

    while candidate in taken:
        index += 1
        stripped: str = candidate.replace(COPY_PREFIX_TEMPLATE.format(index=index - 1), '')
        candidate = f'{COPY_PREFIX_TEMPLATE.format(index=index)}{stripped}'

    return candidate


def deduplicate_media_files(dbm: MongoDatabaseManager, db_name: str) -> int:
    """
    Renames MediaFiles so that a filename appears at most once per folder

    For each duplicate group the keeper is chosen and every other member is renamed to the first free
    'copy_(n)_<name>' in the same folder. Nothing is deleted: a media file is uploaded content, not a
    label, so the duplicate keeps its bytes, its public_id and its references and only loses its name.

    Re-run safe: the groups and the taken names are recomputed from the current collection state on
    every call, so a completed run finds nothing to do and an interrupted one resumes where it stopped

    Args:
        dbm (MongoDatabaseManager): Database manager used for the reads and writes
        db_name (str): Name of the database to de-duplicate

    Returns:
        int: How many files were renamed
    """
    renamed: int = 0

    for group in find_duplicate_file_groups(dbm, db_name):
        identity: dict[str, Any] = group[GROUP_IDENTITY_KEY]
        members: list[dict[str, Any]] = group[GROUP_MEMBERS_KEY]

        filename: Any = identity.get(IDENTITY_FILENAME_KEY)
        parent: Any = identity.get(IDENTITY_PARENT_KEY)

        # A document with no usable filename cannot be renamed into a free one; it is left for an
        # operator, and the index build will report the collection it blocks
        if not isinstance(filename, str) or not filename:
            LOGGER.warning(
                "[updater_20260916] %s files in folder %s carry no filename and were left untouched",
                len(members), parent,
            )
            continue

        keeper_id: Any = select_keeper(members)
        taken: set[str] = taken_names_in_folder(dbm, db_name, parent)

        for member in members:
            if member[MEMBER_ID_KEY] == keeper_id:
                continue

            free_name: str = build_free_name(filename, taken)
            taken.add(free_name)

            dbm.update(
                MEDIA_FILES_COLLECTION,
                db_name,
                {DOCUMENT_ID_KEY: member[MEMBER_ID_KEY]},
                {MediaFileKey.FILENAME.value: free_name},
            )

            renamed += 1

    return renamed


def rebuild_filename_index(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Builds the unique (filename, metadata.parent) index, replacing anything that preceded it

    Three states are handled: the index is already there and unique (nothing to do), it is there but
    not unique (dropped and rebuilt, since a unique flag cannot be added in place), or it is absent.
    The superseded 'name' index is dropped when a database somehow carries it

    Args:
        dbm (MongoDatabaseManager): Database manager used for the index operations
        db_name (str): Name of the database whose index is rebuilt

    Returns:
        bool: True when the index was created by this call, False when it was already correct
    """
    index_info: dict[str, Any] = dbm.get_index_info(MEDIA_FILES_COLLECTION, db_name)

    _drop_legacy_name_index(dbm, db_name, index_info)

    existing: dict[str, Any] | None = index_info.get(MEDIA_FILE_FILENAME_PARENT_INDEX_NAME)

    if existing is not None:
        if existing.get(INDEX_UNIQUE_KEY):
            return False

        dbm.drop_index(MEDIA_FILES_COLLECTION, db_name, MEDIA_FILE_FILENAME_PARENT_INDEX_NAME)

    declaration: dict[str, Any] | None = next(
        (index for index in MediaFile.INDEX_KEYS
         if index.get('name') == MEDIA_FILE_FILENAME_PARENT_INDEX_NAME),
        None,
    )

    if declaration is None:
        return False

    dbm.create_indexes(MEDIA_FILES_COLLECTION, db_name, [IndexModel(**declaration)])

    return True


def _drop_legacy_name_index(
        dbm: MongoDatabaseManager,
        db_name: str,
        index_info: dict[str, Any]) -> None:
    """
    Drops the superseded 'name' index when the collection still carries it

    It indexed a key no GridFS document has, so nothing can depend on it. It was never built by the
    application - the class it was declared on was never registered for reconciliation - so this is
    housekeeping for a database that acquired it some other way

    Args:
        dbm (MongoDatabaseManager): Database manager used for the drop
        db_name (str): Name of the database owning the collection
        index_info (dict[str, Any]): The collection's index information, as read before the rebuild
    """
    if LEGACY_MEDIA_FILE_NAME_INDEX_NAME not in index_info:
        return

    dbm.drop_index(MEDIA_FILES_COLLECTION, db_name, LEGACY_MEDIA_FILE_NAME_INDEX_NAME)

    LOGGER.info(
        "[updater_20260916] Dropped the superseded '%s' index, now covered by '%s'",
        LEGACY_MEDIA_FILE_NAME_INDEX_NAME, MEDIA_FILE_FILENAME_PARENT_INDEX_NAME,
    )

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20260916 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260916(BaseDatabaseUpdate):
    """
    Renames duplicate MediaFiles per folder and makes (filename, metadata.parent) unique

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20260916


    def description(self) -> str:
        return "Renames duplicate MediaFiles and makes their filename unique inside their folder"


    def start_update(self) -> None:
        """
        Renames duplicates first, then builds the index, then bumps the version

        The order is not optional: MongoDB refuses to build a unique index over a collection that
        still holds duplicates, so a crash between the two halves must leave the version untouched
        and start over

        Raises:
            UpdaterException: If either half fails
        """
        try:
            renamed: int = deduplicate_media_files(self.dbm, self.db_name)

            if renamed:
                LOGGER.info("[updater_20260916] Renamed %s duplicate MediaFile(s)", renamed)

            if rebuild_filename_index(self.dbm, self.db_name):
                LOGGER.info(
                    "[updater_20260916] Built the unique '%s' index on %s",
                    MEDIA_FILE_FILENAME_PARENT_INDEX_NAME, MEDIA_FILES_COLLECTION,
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
