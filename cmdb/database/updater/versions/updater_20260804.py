# DataGerry - OpenSource Enterprise CMDB
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
Database update 20260804: makes the CmdbLocation 'object_id' index unique

A CmdbObject has at most one node in the location tree - LocationsManager.get_location_for_object is
a get_one_by, and the object<->location mirror in location_helper assumes the single node it finds is
the only one - but the index was declared non-unique, so nothing enforced it. This migration
de-duplicates any object that accumulated several nodes and rebuilds the index as unique.

The rebuild is needed because index reconciliation is name-based and purely additive (see
CollectionValidator.ensure_indexes): flipping 'unique' in CmdbLocation.INDEX_KEYS alone would only
affect databases whose collection is created from scratch, and would leave every existing deployment
silently non-unique.
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import IndexModel

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model.field_type_enum import FieldType

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Name of the index being rebuilt; matches the declaration in CmdbLocation.INDEX_KEYS
OBJECT_ID_INDEX_NAME: str = 'object_id'

# Aggregation output keys of the duplicate-group pipeline
GROUP_OBJECT_ID_KEY: str = '_id'
GROUP_NODES_KEY: str = 'nodes'

# The 'unique' flag is only present in index_information() output when the index actually is unique
INDEX_UNIQUE_KEY: str = 'unique'

# Dotted path into a CmdbObject's flat 'fields' list, used with an array filter to rewrite the
# location field's value in place
ARRAY_FILTER_ALIAS: str = 'f'
FIELD_VALUE_PATH: str = (
    f'{CmdbObjectKey.FIELDS.value}.$[{ARRAY_FILTER_ALIAS}].{CmdbObjectFieldKey.VALUE.value}'
)
# -------------------------------------------------------------------------------------------------------------------- #

def find_duplicate_location_groups(dbm: MongoDatabaseManager, db_name: str) -> list[dict[str, Any]]:
    """
    Finds every object_id that owns more than one CmdbLocation node

    Groups the whole collection by 'object_id' and keeps only the groups holding at least two
    documents, carrying each node's public_id and parent so a keeper can be chosen without a second
    read

    Args:
        dbm (MongoDatabaseManager): Database manager used for the aggregation
        db_name (str): Name of the database to inspect

    Returns:
        list[dict[str, Any]]: One entry per duplicated object_id, each with the group's '_id'
            (the object_id) and 'nodes' (a list of {'public_id', 'parent'} dicts)
    """
    pipeline: list[dict[str, Any]] = [
        {
            '$group': {
                GROUP_OBJECT_ID_KEY: f'${LocationKey.OBJECT_ID.value}',
                GROUP_NODES_KEY: {
                    '$push': {
                        LocationKey.PUBLIC_ID.value: f'${LocationKey.PUBLIC_ID.value}',
                        LocationKey.PARENT.value: f'${LocationKey.PARENT.value}',
                    },
                },
            },
        },
        {
            '$match': {f'{GROUP_NODES_KEY}.1': {'$exists': True}},
        },
    ]

    return list(dbm.aggregate(CmdbLocation.COLLECTION, db_name, pipeline))


def get_mirrored_parents(
        dbm: MongoDatabaseManager,
        db_name: str,
        object_ids: list[int]) -> dict[int, Any]:
    """
    Reads the stored location-field value of the given CmdbObjects

    An object's location field holds the public_id of its parent CmdbLocation, so this value is the
    object's own record of where it belongs and is the best available tie-breaker when several nodes
    claim it. Objects with no location field are simply absent from the result

    Args:
        dbm (MongoDatabaseManager): Database manager used for the read
        db_name (str): Name of the database to read from
        object_ids (list[int]): public_ids of the CmdbObjects to look up

    Returns:
        dict[int, Any]: public_id of the object mapped to its location field's stored value
    """
    if not object_ids:
        return {}

    # 'projection' must be passed as a keyword: MongoDatabaseManager.find injects its own default
    # projection into kwargs, so a positional one collides with it
    documents: list[dict[str, Any]] = dbm.find_all(
        CmdbObject.COLLECTION,
        db_name,
        {CmdbObjectKey.PUBLIC_ID.value: {'$in': object_ids}},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.FIELDS.value: 1, '_id': 0},
    )

    mirrored: dict[int, Any] = {}

    for document in documents:
        for field in document.get(CmdbObjectKey.FIELDS.value) or []:
            if field.get(CmdbObjectFieldKey.TYPE.value) == FieldType.LOCATION.value:
                mirrored[document[CmdbObjectKey.PUBLIC_ID.value]] = field.get(CmdbObjectFieldKey.VALUE.value)
                break

    return mirrored


def select_keeper(nodes: list[dict[str, Any]], mirrored_parent: Any) -> int:
    """
    Picks which of an object's duplicate CmdbLocation nodes to keep

    Prefers the node whose parent matches the object's own location field, since that is the
    placement every other part of the system already believes in; falls back to the lowest public_id
    (the oldest node, and the one existing children are most likely to reference) when nothing
    matches - which is also the case for objects that carry no location field at all

    Args:
        nodes (list[dict[str, Any]]): The duplicate nodes, each with a 'public_id' and 'parent'
        mirrored_parent (Any): The value stored in the owning object's location field, or None

    Returns:
        int: public_id of the node to keep
    """
    public_ids: list[int] = sorted(node[LocationKey.PUBLIC_ID.value] for node in nodes)

    if mirrored_parent is not None:
        matching: list[int] = sorted(
            node[LocationKey.PUBLIC_ID.value]
            for node in nodes
            if node.get(LocationKey.PARENT.value) == mirrored_parent
        )

        if matching:
            return matching[0]

    return public_ids[0]


def merge_duplicate_locations(
        dbm: MongoDatabaseManager,
        db_name: str,
        keeper_id: int,
        dropped_ids: list[int]) -> None:
    """
    Folds duplicate CmdbLocation nodes into the node being kept, then removes them

    The three writes are ordered so that a crash between any two of them leaves the tree consistent
    and the migration re-runnable: references are moved onto the keeper BEFORE the duplicates are
    deleted, so an interrupted run can leave a childless duplicate behind (found and removed by the
    next run) but never a child pointing at a node that no longer exists

    Args:
        dbm (MongoDatabaseManager): Database manager used for the writes
        db_name (str): Name of the database to write to
        keeper_id (int): public_id of the CmdbLocation node that survives
        dropped_ids (list[int]): public_ids of the duplicate nodes to fold in and delete
    """
    if not dropped_ids:
        return

    # 1. Child nodes of the duplicates are re-parented onto the keeper
    dbm.update_many_raw(
        collection=CmdbLocation.COLLECTION,
        db_name=db_name,
        filter_query={LocationKey.PARENT.value: {'$in': dropped_ids}},
        update={'$set': {LocationKey.PARENT.value: keeper_id}},
    )

    # 2. Objects whose location field points at a duplicate are re-pointed at the keeper, so the
    #    object<->location mirror does not dangle (see delete_location_with_reparenting)
    dbm.update_many_raw(
        collection=CmdbObject.COLLECTION,
        db_name=db_name,
        filter_query={
            CmdbObjectKey.FIELDS.value: {
                '$elemMatch': {
                    CmdbObjectFieldKey.TYPE.value: FieldType.LOCATION.value,
                    CmdbObjectFieldKey.VALUE.value: {'$in': dropped_ids},
                },
            },
        },
        update={'$set': {FIELD_VALUE_PATH: keeper_id}},
        array_filters=[
            {
                f'{ARRAY_FILTER_ALIAS}.{CmdbObjectFieldKey.TYPE.value}': FieldType.LOCATION.value,
                f'{ARRAY_FILTER_ALIAS}.{CmdbObjectFieldKey.VALUE.value}': {'$in': dropped_ids},
            },
        ],
    )

    # 3. Only now are the duplicates removed
    dbm.delete_many_raw(
        collection=CmdbLocation.COLLECTION,
        db_name=db_name,
        filter_query={LocationKey.PUBLIC_ID.value: {'$in': dropped_ids}},
    )


def deduplicate_object_locations(dbm: MongoDatabaseManager, db_name: str) -> int:
    """
    Removes duplicate CmdbLocation nodes so that every object owns at most one

    Re-run safe: the duplicate groups are recomputed from the current collection state on every call,
    so a completed run finds nothing to do and an interrupted one resumes from where it stopped

    Args:
        dbm (MongoDatabaseManager): Database manager used for the reads and writes
        db_name (str): Name of the database to clean up

    Returns:
        int: Number of duplicate nodes that were removed
    """
    groups: list[dict[str, Any]] = find_duplicate_location_groups(dbm, db_name)

    if not groups:
        return 0

    object_ids: list[int] = [
        group[GROUP_OBJECT_ID_KEY] for group in groups if isinstance(group[GROUP_OBJECT_ID_KEY], int)
    ]
    mirrored_parents: dict[int, Any] = get_mirrored_parents(dbm, db_name, object_ids)

    removed: int = 0

    for group in groups:
        object_id: Any = group[GROUP_OBJECT_ID_KEY]
        nodes: list[dict[str, Any]] = group[GROUP_NODES_KEY]

        keeper_id: int = select_keeper(nodes, mirrored_parents.get(object_id))
        dropped_ids: list[int] = [
            node[LocationKey.PUBLIC_ID.value]
            for node in nodes
            if node[LocationKey.PUBLIC_ID.value] != keeper_id
        ]

        LOGGER.warning(
            "[updater_20260804] Object ID:%s had %s Location nodes - keeping ID:%s, removing %s",
            object_id, len(nodes), keeper_id, dropped_ids,
        )

        merge_duplicate_locations(dbm, db_name, keeper_id, dropped_ids)

        removed += len(dropped_ids)

    return removed


def rebuild_object_id_index(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Rebuilds the CmdbLocation 'object_id' index from the model declaration as a unique index

    Drops the existing index first when it is present but not unique, because MongoDB rejects
    recreating an index under the same name with different options. An index that is already unique
    is left alone, which makes the call idempotent

    Args:
        dbm (MongoDatabaseManager): Database manager used for the index operations
        db_name (str): Name of the database owning the collection

    Returns:
        bool: True if the index was (re)created, False if it was already unique
    """
    index_info: dict[str, Any] = dict(dbm.get_index_info(CmdbLocation.COLLECTION, db_name))
    existing: dict[str, Any] | None = index_info.get(OBJECT_ID_INDEX_NAME)

    if existing is not None:
        if existing.get(INDEX_UNIQUE_KEY, False):
            return False

        dbm.drop_index(CmdbLocation.COLLECTION, db_name, OBJECT_ID_INDEX_NAME)

    declaration: dict[str, Any] | None = next(
        (index for index in CmdbLocation.INDEX_KEYS if index.get('name') == OBJECT_ID_INDEX_NAME),
        None,
    )

    if declaration is None:
        return False

    dbm.create_indexes(CmdbLocation.COLLECTION, db_name, [IndexModel(**declaration)])

    return True

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260804 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260804(BaseDatabaseUpdate):
    """
    De-duplicates CmdbLocation nodes per CmdbObject and makes the 'object_id' index unique
    """
    def creation_date(self) -> int:
        return 20260804


    def description(self) -> str:
        return "De-duplicates CmdbLocations per object and rebuilds the 'object_id' index as unique"


    def start_update(self) -> None:
        """
        De-duplicates the location nodes, then rebuilds the 'object_id' index as unique

        The order is mandatory: a unique index cannot be built over a collection that still holds
        duplicates. Both steps are individually idempotent, so a crash anywhere in the migration
        leaves it re-runnable - which matters because the version is only bumped once both have
        completed, meaning an interrupted run starts over from the top

        Raises:
            UpdaterException: If the de-duplication or the index rebuild fails
        """
        try:
            removed: int = deduplicate_object_locations(self.dbm, self.db_name)

            if removed:
                LOGGER.info("[updater_20260804] Removed %s duplicate Location node(s)", removed)

            rebuild_object_id_index(self.dbm, self.db_name)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
