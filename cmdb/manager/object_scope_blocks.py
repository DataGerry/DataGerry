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
Computes and stores the objects' materialised scope blocks (``_scope``) - the reads behind them

A block (``cmdb.models.object_model.object_scope_block``) needs three facts outside the object: the location chain
above the node the object is placed under, read from the CmdbLocation tree in one ``$graphLookup``, the supernet of
each subnet its interface rows name, and the object relations naming the object (its ``related`` list). All three
are memoised per instance, so one instance serves a request or a batch.

The stored blocks are kept current synchronously (ruled D1): the object writes compute the block (``stamp`` before an
insert or a replace, ``refresh`` after an update), and the writes that change what other objects' blocks are built from
refresh those - a location node moved, added or removed (every object naming that location), a subnet's supernet
changed or a network object deleted (every object naming the network), an object relation written or deleted (both
ends, ``refresh_endpoints``). ``refresh`` reads the objects back and writes
only the blocks that differ. An object without a block counts as having an empty one
"""
from collections.abc import Collection, Iterable, Mapping
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.utils import Builder
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.locations_manager import ancestors_lookup_stage, usable_object_ids
from cmdb.manager.locations_manager_constants import LocationLookupField
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectScopeKey,
    CmdbObjectScopeRelatedKey,
)
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.object_model.object_scope_block import (
    build_scope_block,
    interface_subnets,
    location_entry,
    related_entries,
    scope_path,
)
from cmdb.models.object_relation_model.cmdb_object_relation import CmdbObjectRelation
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationKey
from cmdb.models.special_type_model.ipam_constants import SubnetField

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError, BaseManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ObjectScopeBlocks',
    'relation_endpoints',
    'NAMING_KEYS',
    'SCOPE_BLOCK_READ_PROJECTION',
]

LOGGER: Logger = getLogger(__name__)

# The block lists that name other objects: a location chain, the networks, the related objects
NAMING_KEYS: tuple[CmdbObjectScopeKey, ...] = (CmdbObjectScopeKey.LOCATIONS, CmdbObjectScopeKey.NETWORKS,
                                               CmdbObjectScopeKey.RELATED)
# Where a naming list holds the ids - the related list holds documents
_NAMING_PATHS: dict[CmdbObjectScopeKey, str] = {
    CmdbObjectScopeKey.LOCATIONS: scope_path(CmdbObjectScopeKey.LOCATIONS),
    CmdbObjectScopeKey.NETWORKS: scope_path(CmdbObjectScopeKey.NETWORKS),
    CmdbObjectScopeKey.RELATED: f'{scope_path(CmdbObjectScopeKey.RELATED)}.{CmdbObjectScopeRelatedKey.OBJECT.value}',
}
_RELATION_PROJECTION: dict[str, int] = {'_id': 0, ObjectRelationKey.RELATION_ID.value: 1,
                                        ObjectRelationKey.RELATION_PARENT_ID.value: 1,
                                        ObjectRelationKey.RELATION_CHILD_ID.value: 1}
# What a block is computed from, plus the stored block to compare against
SCOPE_BLOCK_READ_PROJECTION: dict[str, int] = {
    '_id': 0,
    CmdbObjectKey.PUBLIC_ID.value: 1,
    CmdbObjectKey.FIELDS.value: 1,
    CmdbObjectKey.MULTI_DATA_SECTIONS.value: 1,
    CmdbObjectScopeKey.BLOCK.value: 1,
}
# Objects read back per refresh round
REFRESH_BATCH_SIZE: int = 1000

_MONGO_ID: str = '_id'
_ANCESTORS: str = LocationLookupField.ANCESTORS.value


class ObjectScopeBlocks:
    """
    The scope blocks of the objects of one database - computed, memoised reads, stored

    Built on the objects' manager (``ObjectsManager``); the location tree is read through its ``collection`` argument
    """
    def __init__(self, objects_manager: BaseManager) -> None:
        """
        Args:
            objects_manager (BaseManager): The manager of ``framework.objects``
        """
        self.manager: BaseManager = objects_manager
        self._chains: dict[int, list[int]] = {}
        self._supernets: dict[int, int | None] = {}
        self._placements: dict[int, int | None] = {}
        self._related: dict[int, list[dict[str, int]]] = {}


    def block_of(self, document: Mapping[str, Any]) -> dict[str, list[Any]]:
        """
        One document's block, as it would be stored

        Args:
            document (Mapping[str, Any]): An object document or state

        Raises:
            BaseManagerIterationError: If the location tree or a subnet could not be read

        Returns:
            dict[str, list[Any]]: The block
        """
        return self.blocks_of([document])[0]


    def blocks_of(self, documents: list[Mapping[str, Any]]) -> list[dict[str, list[Any]]]:
        """
        The blocks of several documents, with at most three reads for all of them

        Args:
            documents (list[Mapping[str, Any]]): Object documents or states

        Raises:
            BaseManagerIterationError: If the location tree, a subnet or the object relations could not be read

        Returns:
            list[dict[str, list[Any]]]: The blocks, in the order of the documents
        """
        self._read_placements([document.get(CmdbObjectKey.PUBLIC_ID.value) for document in documents
                               if not location_entry(document)[0]])
        parents: list[int | None] = [self._parent_of(document) for document in documents]
        self._read_chains([parent for parent in parents if parent is not None])
        self._read_supernets([subnet for document in documents for subnet in interface_subnets(document)])
        self._read_related([document.get(CmdbObjectKey.PUBLIC_ID.value) for document in documents])
        supernets: dict[int, int] = {subnet: supernet for subnet, supernet in self._supernets.items()
                                     if supernet is not None}

        return [build_scope_block(document, self._chains.get(parent, []) if parent is not None else [], supernets,
                                  self._related.get(document.get(CmdbObjectKey.PUBLIC_ID.value), []))
                for document, parent in zip(documents, parents, strict=True)]


    def stamp(self, documents: list[dict[str, Any]]) -> None:
        """
        Writes the block into documents about to be inserted or to replace a stored object - a block a document
        brought along is replaced

        Args:
            documents (list[dict[str, Any]]): The documents; changed in place

        Raises:
            BaseManagerIterationError: If the location tree or a subnet could not be read
        """
        for document, block in zip(documents, self.blocks_of(documents), strict=True):
            document[CmdbObjectScopeKey.BLOCK.value] = block


    def refresh(self, object_ids: Iterable[int]) -> int:
        """
        Recomputes the stored blocks of objects and writes the ones that differ

        Args:
            object_ids (Iterable[int]): The objects; one that is gone is passed over

        Raises:
            BaseManagerIterationError: If an object, the location tree or a subnet could not be read
            BaseManagerUpdateError: If a block could not be written

        Returns:
            int: How many blocks were written
        """
        ids: list[int] = sorted(set(object_ids))
        written: int = 0

        for start in range(0, len(ids), REFRESH_BATCH_SIZE):
            documents: list[dict[str, Any]] = self.manager.aggregate_all([
                Builder.match_({CmdbObjectKey.PUBLIC_ID.value: {'$in': ids[start:start + REFRESH_BATCH_SIZE]}}),
                Builder.project_(SCOPE_BLOCK_READ_PROJECTION),
            ])
            operations: list[UpdateOne] = [
                UpdateOne({CmdbObjectKey.PUBLIC_ID.value: document[CmdbObjectKey.PUBLIC_ID.value]},
                          {'$set': {CmdbObjectScopeKey.BLOCK.value: block}})
                for document, block in zip(documents, self.blocks_of(documents), strict=True)
                if document.get(CmdbObjectScopeKey.BLOCK.value) != block
            ]

            if operations:
                written += self.manager.bulk_write(operations)

        return written


    def refresh_naming(self, object_ids: Collection[int],
                       keys: tuple[CmdbObjectScopeKey, ...] = NAMING_KEYS) -> int:
        """
        Refreshes objects and every object whose stored block names one of them - the objects placed below a location,
        the objects in a network

        Args:
            object_ids (Collection[int]): The objects that changed
            keys (tuple[CmdbObjectScopeKey, ...]): The block lists to look the ids up in. Defaults to both

        Raises:
            BaseManagerGetError: If the naming objects could not be listed
            BaseManagerIterationError: If an object, the location tree or a subnet could not be read
            BaseManagerUpdateError: If a block could not be written

        Returns:
            int: How many blocks were written
        """
        if not object_ids:
            return 0

        naming: list[Any] = self.manager.get_distinct(CmdbObjectKey.PUBLIC_ID.value, {
            '$or': [{_NAMING_PATHS[key]: {'$in': sorted(object_ids)}} for key in keys]})

        return self.refresh({*object_ids, *naming})


    def refresh_endpoints(self, relations: Iterable[Mapping[str, Any]]) -> int:
        """
        Refreshes both ends of object relations just written or deleted - their ``related`` lists

        Args:
            relations (Iterable[Mapping[str, Any]]): Object relation documents, as stored before or after the write

        Raises:
            BaseManagerIterationError: If an object, the location tree, a subnet or a relation could not be read
            BaseManagerUpdateError: If a block could not be written

        Returns:
            int: How many blocks were written
        """
        return self.refresh(relation_endpoints(relations))


    def try_refresh_endpoints(self, relations: Iterable[Mapping[str, Any]]) -> bool:
        """
        ``refresh_endpoints``, best-effort - beside a write that may have failed part-way: a failure is logged, never
        raised over that write's own error

        Args:
            relations (Iterable[Mapping[str, Any]]): Object relation documents

        Returns:
            bool: False when the blocks could not be refreshed and stay stale
        """
        endpoints: list[int] = relation_endpoints(relations)

        try:
            self.refresh(endpoints)
        except (BaseManagerIterationError, BaseManagerUpdateError) as err:
            LOGGER.error("[try_refresh_endpoints] The scope blocks of %s stay stale: %s", endpoints, err)
            return False

        return True


    def try_refresh_naming(self, object_ids: Collection[int],
                           keys: tuple[CmdbObjectScopeKey, ...] = NAMING_KEYS) -> bool:
        """
        ``refresh_naming``, best-effort - for a request already failing with an error of its own (an undone write): a
        failure is logged, never raised over that error

        Args:
            object_ids (Collection[int]): The objects that changed
            keys (tuple[CmdbObjectScopeKey, ...]): The block lists to look the ids up in. Defaults to both

        Returns:
            bool: False when the blocks could not be refreshed and stay stale
        """
        try:
            self.refresh_naming(object_ids, keys)
        except (BaseManagerGetError, BaseManagerIterationError, BaseManagerUpdateError) as err:
            LOGGER.error("[try_refresh_naming] The scope blocks of %s stay stale: %s", sorted(object_ids), err)
            return False

        return True


    def ids_with_blocks(self, criteria: list[dict[str, Any]]) -> list[int]:
        """
        The objects matching any of the filters whose stored block is not empty

        Args:
            criteria (list[dict[str, Any]]): Object filters

        Raises:
            BaseManagerGetError: If the objects could not be listed

        Returns:
            list[int]: Their ids
        """
        if not criteria:
            return []

        not_empty: dict[str, Any] = {'$or': [{f'{scope_path(key)}.0': {'$exists': True}}
                                             for key in CmdbObjectScopeKey if key != CmdbObjectScopeKey.BLOCK]}

        return self.manager.get_distinct(CmdbObjectKey.PUBLIC_ID.value, {'$and': [{'$or': criteria}, not_empty]})


    def _parent_of(self, document: Mapping[str, Any]) -> int | None:
        """
        The node a document is placed under: its location entry's, else its stored node's parent

        Args:
            document (Mapping[str, Any]): An object document or state

        Returns:
            int | None: The node id, None when unplaced
        """
        has_entry, parent = location_entry(document)

        if has_entry:
            return parent

        return self._placements.get(document.get(CmdbObjectKey.PUBLIC_ID.value))


    def _read_placements(self, object_ids: list[Any]) -> None:
        """
        Reads the parent node of the objects' own nodes - for documents without a location entry

        Args:
            object_ids (list[Any]): The objects' ids; anything that is no id and anything read already is passed over
        """
        missing: list[int] = sorted({object_id for object_id in object_ids if isinstance(object_id, int)
                                     and not isinstance(object_id, bool) and object_id not in self._placements})

        if not missing:
            return

        nodes: list[dict[str, Any]] = self.manager.aggregate_all([
            Builder.match_({LocationKey.OBJECT_ID.value: {'$in': missing}}),
            Builder.project_({_MONGO_ID: 0, LocationKey.OBJECT_ID.value: 1, LocationKey.PARENT.value: 1}),
        ], collection=CmdbLocation.COLLECTION)
        self._placements.update({object_id: None for object_id in missing})
        self._placements.update({node[LocationKey.OBJECT_ID.value]: node.get(LocationKey.PARENT.value)
                                 for node in nodes})


    def _read_chains(self, node_ids: list[int]) -> None:
        """
        Reads the location chain of nodes: the object of the node and of every node above it, the root's left out

        Args:
            node_ids (list[int]): The nodes; anything read already is passed over
        """
        missing: list[int] = sorted({node_id for node_id in node_ids if node_id not in self._chains})

        if not missing:
            return

        nodes: list[dict[str, Any]] = self.manager.aggregate_all([
            Builder.match_({LocationKey.PUBLIC_ID.value: {'$in': missing}}),
            ancestors_lookup_stage(),
            Builder.project_({_MONGO_ID: 0, LocationKey.PUBLIC_ID.value: 1, LocationKey.OBJECT_ID.value: 1,
                              f'{_ANCESTORS}.{LocationKey.OBJECT_ID.value}': 1}),
        ], collection=CmdbLocation.COLLECTION)
        self._chains.update({node_id: [] for node_id in missing})
        # The root's object_id is the 0 sentinel - no object answers to it
        self._chains.update({node[LocationKey.PUBLIC_ID.value]: [object_id for object_id in usable_object_ids(
            [node, *node.get(_ANCESTORS, [])]) if object_id > 0] for node in nodes})


    def _read_related(self, object_ids: list[Any]) -> None:
        """
        Reads the object relations naming the objects, either end

        Args:
            object_ids (list[Any]): The objects' ids; anything that is no id and anything read already is passed over
        """
        missing: list[int] = sorted({object_id for object_id in object_ids if isinstance(object_id, int)
                                     and not isinstance(object_id, bool) and object_id not in self._related})

        if not missing:
            return

        relations: list[dict[str, Any]] = self.manager.aggregate_all([
            Builder.match_({'$or': [{ObjectRelationKey.RELATION_PARENT_ID.value: {'$in': missing}},
                                    {ObjectRelationKey.RELATION_CHILD_ID.value: {'$in': missing}}]}),
            Builder.project_(_RELATION_PROJECTION),
        ], collection=CmdbObjectRelation.COLLECTION)
        self._related.update({object_id: related_entries(object_id, relations) for object_id in missing})


    def _read_supernets(self, subnet_ids: list[int]) -> None:
        """
        Reads the supernet each subnet names

        Args:
            subnet_ids (list[int]): The subnets; anything read already is passed over
        """
        missing: list[int] = sorted({subnet for subnet in subnet_ids if subnet not in self._supernets})

        if not missing:
            return

        subnets: list[dict[str, Any]] = self.manager.aggregate_all([
            Builder.match_({CmdbObjectKey.PUBLIC_ID.value: {'$in': missing}}),
            Builder.project_({_MONGO_ID: 0, CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.FIELDS.value: 1}),
        ])
        self._supernets.update({subnet: None for subnet in missing})

        for subnet in subnets:
            supernet: Any = extract_field_value(subnet, SubnetField.PARENT_SUPERNET.value)

            if isinstance(supernet, int) and not isinstance(supernet, bool) and supernet > 0:
                self._supernets[subnet[CmdbObjectKey.PUBLIC_ID.value]] = supernet


def relation_endpoints(relations: Iterable[Mapping[str, Any]]) -> list[int]:
    """
    The objects at either end of object relations

    Args:
        relations (Iterable[Mapping[str, Any]]): Object relation documents

    Returns:
        list[int]: Their parent and child ids, ascending, once each; anything that is no id left out
    """
    return sorted({end for relation in relations
                   for end in (relation.get(ObjectRelationKey.RELATION_PARENT_ID.value),
                               relation.get(ObjectRelationKey.RELATION_CHILD_ID.value))
                   if isinstance(end, int) and not isinstance(end, bool)})
