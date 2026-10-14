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
Database update 20261017: an attachment no longer references a CmdbObject that was deleted

Since this version deleting a CmdbObject detaches it from its media files: its id leaves every file's
`metadata.reference` and the files stay in the library. Before, nothing did, so every object deleted until now left
its id behind on its attachments - a reference to an id that resolves to nothing. This update takes those ids out the
same way the delete now does.

**Only the reference changes.** No file is deleted: a file attached to an object may be filed in a folder or attached
to other objects as well, and the library cannot tell an upload from a library file attached later. A reference is
stored as one id or a list of ids; both are read as a list, and a file left referencing nothing keeps an empty list -
the state the attachment dialog's own "remove" leaves. Only files of reference kind 'object' are read, and only an
integer entry is judged: anything else in a reference is left as it is.

Re-run safe: the referenced ids and the objects that still exist are read again on every run, and a second run finds
no id left to take out
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
MEDIA_FILES_COLLECTION: str = 'media.libary.files'
OBJECTS_COLLECTION: str = 'framework.objects'
PUBLIC_ID_FIELD: str = 'public_id'
REFERENCE_PATH: str = 'metadata.reference'
REFERENCE_TYPE_PATH: str = 'metadata.reference_type'
OBJECT_REFERENCE_TYPE: str = 'object'
MONGO_ID_FIELD: str = '_id'

# Aggregation keys of the referenced-ids read
REFERENCES_KEY: str = 'references'
REFERENCED_IDS_KEY: str = 'ids'

# The BSON types an object's public_id is stored as
INTEGER_BSON_TYPES: list[str] = ['int', 'long']

# How many ids one existence read and one detach update name at most
ID_BATCH_SIZE: int = 1000

# The name each entry of a file's reference list goes by inside the update's $filter
REFERENCE_ENTRY_VARIABLE: str = 'reference'

# -------------------------------------------------------------------------------------------------------------------- #

def reference_as_list() -> dict[str, Any]:
    """
    Builds the expression reading a file's reference as a list, whether it is stored as one id or several

    Returns:
        dict[str, Any]: The aggregation expression
    """
    reference: str = f'${REFERENCE_PATH}'

    return {'$cond': [{'$isArray': reference}, reference, [reference]]}


def referenced_ids_pipeline() -> list[dict[str, Any]]:
    """
    Builds the pipeline answering every integer id an object attachment references, once

    Returns:
        list[dict[str, Any]]: The pipeline; its one result carries the ids under REFERENCED_IDS_KEY
    """
    return [
        {'$match': {REFERENCE_TYPE_PATH: OBJECT_REFERENCE_TYPE, REFERENCE_PATH: {'$ne': None}}},
        {'$project': {MONGO_ID_FIELD: 0, REFERENCES_KEY: reference_as_list()}},
        {'$unwind': f'${REFERENCES_KEY}'},
        {'$match': {REFERENCES_KEY: {'$type': INTEGER_BSON_TYPES}}},
        {'$group': {MONGO_ID_FIELD: None, REFERENCED_IDS_KEY: {'$addToSet': f'${REFERENCES_KEY}'}}},
    ]


def detach_update(object_ids: list[int]) -> list[dict[str, Any]]:
    """
    Builds the update pipeline taking the given ids out of a file's reference

    Args:
        object_ids (list[int]): The ids to take out

    Returns:
        list[dict[str, Any]]: The update pipeline
    """
    return [{'$set': {
        REFERENCE_PATH: {
            '$filter': {
                'input': reference_as_list(),
                'as': REFERENCE_ENTRY_VARIABLE,
                'cond': {'$not': [{'$in': [f'$${REFERENCE_ENTRY_VARIABLE}', object_ids]}]},
            },
        },
    }}]


def batches(ids: list[int], size: int) -> list[list[int]]:
    """
    Splits ids into consecutive batches of at most `size`

    Args:
        ids (list[int]): The ids
        size (int): The largest batch

    Returns:
        list[list[int]]: The batches, in order
    """
    return [ids[start:start + size] for start in range(0, len(ids), size)]

# ---------------------------------------------- Update20261017 - CLASS ---------------------------------------------- #

class Update20261017(BaseDatabaseUpdate):
    """
    Takes the ids of deleted CmdbObjects out of the media files attached to them

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261017


    def description(self) -> str:
        return "Detaches media files from CmdbObjects that were deleted"


    def start_update(self) -> None:
        """
        Finds the referenced ids whose object is gone and takes them out of every attachment, then bumps the version

        Raises:
            UpdaterException: If a read or an update fails
        """
        try:
            missing: list[int] = self.find_deleted_object_ids()
            changed: int = self.detach(missing)

            if changed:
                LOGGER.info(
                    "[updater_20261017] Detached %s deleted Object(s) from %s media file(s)", len(missing), changed,
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def find_deleted_object_ids(self) -> list[int]:
        """
        Answers the ids an object attachment references although no CmdbObject carries them any more

        Returns:
            list[int]: The ids, ascending
        """
        results: list[dict[str, Any]] = list(
            self.dbm.aggregate(MEDIA_FILES_COLLECTION, self.db_name, referenced_ids_pipeline())
        )
        referenced: list[int] = sorted(results[0][REFERENCED_IDS_KEY]) if results else []
        existing: set[int] = set()

        for batch in batches(referenced, ID_BATCH_SIZE):
            existing.update(
                document[PUBLIC_ID_FIELD] for document in self.dbm.find(
                    OBJECTS_COLLECTION,
                    self.db_name,
                    {PUBLIC_ID_FIELD: {'$in': batch}},
                    projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0},
                )
            )

        return [object_id for object_id in referenced if object_id not in existing]


    def detach(self, object_ids: list[int]) -> int:
        """
        Takes the ids out of every object attachment referencing them, a batch per update

        Args:
            object_ids (list[int]): The ids of the deleted CmdbObjects

        Returns:
            int: How many files were changed
        """
        changed: int = 0

        for batch in batches(object_ids, ID_BATCH_SIZE):
            changed += self.dbm.update_many_raw(
                MEDIA_FILES_COLLECTION,
                self.db_name,
                {REFERENCE_TYPE_PATH: OBJECT_REFERENCE_TYPE, REFERENCE_PATH: {'$in': batch}},
                detach_update(batch),
            ).modified_count

        return changed
