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
This module contains the implementation of the LocationsManager

Beyond plain CRUD this is the engine of the location tree, and three invariants of the
``framework.locations`` collection shape everything in here:

* the tree is rooted in a **synthetic root document** with ``public_id`` 1 and the 0 sentinels
  ``object_id`` / ``type_id`` (see RootLocationDefault). It is seeded with the database, is not
  backed by a CmdbObject and must never be deleted - ``delete_location`` refuses it, because the
  document is reachable through ``get_location_for_object(0)`` like any other node
* ``object_id`` is **unique**: a CmdbObject owns at most one node, which is why the object-driven
  reads are single-document lookups
* ``parent`` is a nullable integer in the schema, so a stored document may carry no usable parent.
  The delete path refuses to promote children onto such a node instead of writing them out of the
  tree

Every relationship walk (subtree, ancestor chain, expanded path) is resolved in a single
``$graphLookup`` - MongoDB detects cycles itself, so a malformed parent chain terminates - and the
per-level "does this node have children" hint is one grouped aggregation for the whole level rather
than a count per node. The tree-facing reads answer with canonical location documents
(``to_location_document``) ordered by name (``sort_locations_by_name``), so the frontend never
depends on insertion order
"""
import re
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.query_builder.builder import Builder
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.locations_manager_constants import (
    CASE_INSENSITIVE_REGEX_OPTIONS,
    LocationLookupField,
    MONGO_ID_KEY,
)

from cmdb.models.location_model.cmdb_location import CmdbLocation

from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.location_model.location_utils import sort_locations_by_name, to_location_document

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.locations_manager import (
    LocationsManagerInitError,
    LocationsManagerInsertError,
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerDeleteError,
    LocationsManagerIterationError,
    LocationsManagerChildrenError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def ancestors_lookup_stage() -> dict[str, Any]:
    """
    Builds the ``$graphLookup`` stage that collects the ancestor chain of a CmdbLocation

    Follows ``parent`` -> ``public_id`` upwards from each incoming document and writes every
    reachable ancestor - the synthetic root included - into the ``ancestors`` array. Shared by the
    tree search and the path expansion so both walk the edge in exactly the same direction

    Returns:
        dict[str, Any]: The `$graphLookup` stage collecting the ancestors of a CmdbLocation
    """
    return Builder.graph_lookup_(
        CmdbLocation.COLLECTION,
        f"${LocationKey.PARENT.value}",
        LocationKey.PARENT.value,
        LocationKey.PUBLIC_ID.value,
        LocationLookupField.ANCESTORS.value,
    )


def descendants_lookup_stage() -> dict[str, Any]:
    """
    Builds the ``$graphLookup`` stage that collects the whole subtree beneath a CmdbLocation

    The mirror image of :func:`ancestors_lookup_stage`: it follows ``public_id`` -> ``parent``
    downwards and writes every reachable descendant into the ``descendants`` array

    Returns:
        dict[str, Any]: The `$graphLookup` stage collecting the descendants of a CmdbLocation
    """
    return Builder.graph_lookup_(
        CmdbLocation.COLLECTION,
        f"${LocationKey.PUBLIC_ID.value}",
        LocationKey.PUBLIC_ID.value,
        LocationKey.PARENT.value,
        LocationLookupField.DESCENDANTS.value,
    )

# -------------------------------------------------------------------------------------------------------------------- #

class LocationsManager(BaseManager):
    """
    The LocationsManager manages the interaction between CmdbLocations and the database

    Extends: BaseManager
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the LocationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE

        Raises:
            LocationsManagerInitError: If the LocationsManager could not be initialised
        """
        try:
            super().__init__(CmdbLocation.COLLECTION, dbm, database)
        except Exception as err:
            raise LocationsManagerInitError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_location(self, location: dict[str, Any]) -> int:
        """
        Insert a CmdbLocation into the database

        Takes a document, not a model: nothing writes a location through the model - the object
        mirror and the POST route both assemble the document key by key (see ``LocationKey``), which
        is why the CmdbLocation-or-dict union this used to accept was never exercised outside its
        own test

        Args:
            location (dict[str, Any]): The CmdbLocation document to store

        Raises:
            LocationsManagerInsertError: When a CmdbLocation could not be inserted into the database,
                                         or when the insert returned no public_id

        Returns:
            int: The public_id of the created CmdbLocation
        """
        try:
            created_id: int | None = self.insert(location)

            # BaseManager.insert only answers with None when it is told to skip the public_id
            # generation, which this path never does - so a None here is a broken write, not a
            # CmdbLocation the caller could work with
            if created_id is None:
                raise LocationsManagerInsertError('The inserted CmdbLocation carries no public_id!')

            return created_id
        except LocationsManagerInsertError:
            raise
        except Exception as err:
            LOGGER.error("[insert_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerInsertError(str(err)) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate_location_documents(
            self,
            builder_params: BuilderParameters) -> tuple[list[dict[str, Any]], int]:
        """
        Retrieves the matching CmdbLocations as canonical documents, with the total match count

        The read behind the two list routes (the flat list and the eager tree). Answers documents
        rather than model instances - the same key set ``CmdbLocation.to_json`` produces, through
        ``to_location_document`` - because both routes only pass the result on as JSON: hydrating a
        CmdbLocation per row and converting it straight back was two objects per location for a
        response that is a document either way

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination for the read

        Raises:
            LocationsManagerIterationError: When the iteration failed

        Returns:
            tuple[list[dict[str, Any]], int]: The canonical documents of the page, and the total
                number of matches (counted independently of the page)
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            return [to_location_document(document) for document in aggregation_result], total
        except BaseManagerIterationError as err:
            raise LocationsManagerIterationError(str(err)) from err
        except Exception as err:
            LOGGER.error("[iterate_location_documents] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerIterationError(str(err)) from err


    def get_location(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbLocation from the database

        The synthetic root document (public_id 1) is a CmdbLocation like any other here and is
        returned as-is

        Args:
            public_id (int): public_id of the CmdbLocation

        Raises:
            LocationsManagerGetError: When a CmdbLocation could not be retrieved

        Returns:
            dict[str, Any] | None: A dictionary representation of the CmdbLocation if successful, otherwise None
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_location_for_object(self, object_id: int) -> dict[str, Any] | None:
        """
        Retrieves a single CmdbLocation for the given CmdbObject's public_id

        ``object_id`` is unique in the collection, so this is a single-document lookup. Note that
        the synthetic root carries the object_id sentinel 0 (RootLocationDefault.NO_OBJECT) and is
        therefore what this returns for object_id 0

        Args:
            object_id (int): public_id of the CmdbObject

        Raises:
            LocationsManagerGetError: If CmdbLocation could not be retrieved

        Returns:
            dict[str, Any] | None: The requested CmdbLocation as dict if found, else None
        """
        try:
            return self.get_one_by({LocationKey.OBJECT_ID.value: object_id})
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_location_for_object] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_location_names(self, public_ids: list[int]) -> dict[int, str]:
        """
        Retrieves the display name of every given CmdbLocation, keyed by public_id

        The read behind resolving a location reference into the label an export shows. One projected
        '$in' query over the public_id index, and only the two keys a name lookup needs leave the
        database - a caller that needs a name has no use for the render metadata, let alone for a
        model built from it.

        A location whose name is missing or is not text is left out rather than mapped to None: the
        caller's lookup then does not resolve, which is the same outcome as a reference to a location
        that no longer exists

        Args:
            public_ids (list[int]): public_ids of the CmdbLocations to read; an empty selection
                queries nothing

        Raises:
            LocationsManagerGetError: If the CmdbLocations could not be retrieved

        Returns:
            dict[int, str]: {public_id: name} for every readable match
        """
        if not public_ids:
            return {}

        try:
            documents: list[dict[str, Any]] = self.find(
                criteria={LocationKey.PUBLIC_ID.value: {'$in': list(public_ids)}},
                projection={
                    LocationKey.PUBLIC_ID.value: 1,
                    LocationKey.NAME.value: 1,
                },
            )

            return {
                document[LocationKey.PUBLIC_ID.value]: document[LocationKey.NAME.value]
                for document in documents
                if document.get(LocationKey.PUBLIC_ID.value) is not None
                and isinstance(document.get(LocationKey.NAME.value), str)
            }
        except Exception as err:
            LOGGER.error("[get_location_names] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_child_object_ids(self, parent_id: int) -> list[int]:
        """
        Retrieves the object_id of every direct child of a CmdbLocation

        The read behind "which objects sit under this one" - the CI Explorer's location expansion and
        the delete guard that refuses to strand a subtree. Projected to the single key both need, so
        the render metadata of a whole tree level is never transferred

        Args:
            parent_id (int): public_id of the parent CmdbLocation

        Raises:
            LocationsManagerGetError: If the child CmdbLocations could not be retrieved

        Returns:
            list[int]: The object_ids of the direct children, in read order. A child without a
                usable object_id is left out - the root's 0 sentinel is such a value, and no object
                answers to it
        """
        try:
            documents: list[dict[str, Any]] = self.find(
                criteria={LocationKey.PARENT.value: parent_id},
                projection={LocationKey.OBJECT_ID.value: 1},
            )

            return [
                document[LocationKey.OBJECT_ID.value] for document in documents
                if isinstance(document.get(LocationKey.OBJECT_ID.value), int)
                and not isinstance(document.get(LocationKey.OBJECT_ID.value), bool)
            ]
        except Exception as err:
            LOGGER.error("[get_child_object_ids] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def get_child_location_documents(self, parent_id: int) -> list[dict[str, Any]]:
        """
        Retrieves the direct children of a CmdbLocation as canonical, name-ordered documents

        The read behind one level of the lazily-expanded tree (the root level is the children of
        RootLocationDefault.PUBLIC_ID). Answers with the same key set ``CmdbLocation.to_json``
        produces - without building the model - and in name order (case-insensitive, public_id as
        tie-breaker), because the underlying document read is public_id-descending and the tree must
        not depend on insertion order

        Args:
            parent_id (int): public_id of the parent CmdbLocation whose children are requested

        Raises:
            LocationsManagerGetError: If the child CmdbLocations could not be retrieved

        Returns:
            list[dict[str, Any]]: The canonical documents of the direct children, name-ascending
        """
        try:
            documents: list[dict[str, Any]] = self.get_many(**{LocationKey.PARENT.value: parent_id})
        except BaseManagerGetError as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_child_location_documents] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err

        return sort_locations_by_name([to_location_document(document) for document in documents])


    def get_all_descendant_locations(self, public_id: int) -> list[dict[str, Any]]:
        """
        Retrieves the public_id of every descendant CmdbLocation beneath the given CmdbLocation

        Resolves the full subtree in a single ``$graphLookup`` aggregation (following
        ``public_id`` -> ``parent`` edges) instead of loading the whole collection and walking
        it in Python. ``$graphLookup`` detects cycles internally, so a malformed parent chain
        cannot cause infinite recursion. Requires MongoDB 3.4+ (well within the 7.0 floor)

        Only the ``public_id`` of each descendant is projected out: the callers use the ids to
        forbid cyclic re-parenting, and the subtree of a large tree is not worth sending in full
        (the aggregation still materialises it inside the server's memory limit)

        Args:
            public_id (int): public_id of the CmdbLocation whose descendants should be retrieved

        Raises:
            LocationsManagerChildrenError: If the descendant CmdbLocations could not be retrieved

        Returns:
            list[dict[str, Any]]: One ``{'public_id': int}`` document per descendant CmdbLocation
                                  (the location itself is excluded)
        """
        try:
            descendants_field: str = LocationLookupField.DESCENDANTS.value

            pipeline: list[dict[str, Any]] = [
                Builder.match_({LocationKey.PUBLIC_ID.value: public_id}),
                descendants_lookup_stage(),
                Builder.project_({
                    MONGO_ID_KEY: 0,
                    f"{descendants_field}.{LocationKey.PUBLIC_ID.value}": 1,
                }),
            ]

            result: list[dict[str, Any]] = list(self.aggregate(pipeline))

            if not result:
                return []

            return result[0].get(descendants_field, [])
        except BaseManagerIterationError as err:
            raise LocationsManagerChildrenError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_all_descendant_locations] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerChildrenError(str(err)) from err


    def get_parents_with_children(self, parent_ids: list[int]) -> set[int]:
        """
        Determines which of the given CmdbLocations have at least one direct child

        Resolves the has-children hint for a whole tree level in a single grouped aggregation
        (``$match`` on the candidate parents, then ``$group`` by parent) instead of one count per
        node, so a lazily-expanded tree level stays a single query. The ``parent`` index of the
        collection serves the match

        Args:
            parent_ids (list[int]): public_ids of the CmdbLocations to test for children

        Raises:
            LocationsManagerGetError: If the grouped lookup could not be executed

        Returns:
            set[int]: The subset of parent_ids that have at least one direct child location
        """
        if not parent_ids:
            return set()

        pipeline: list[dict[str, Any]] = [
            Builder.match_(Builder.in_(LocationKey.PARENT.value, parent_ids)),
            Builder.group_(f"${LocationKey.PARENT.value}"),
        ]

        try:
            return {document[MONGO_ID_KEY] for document in self.aggregate(pipeline)}
        except Exception as err:
            LOGGER.error("[get_parents_with_children] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err


    def search_locations_with_ancestors(self, query: str) -> list[dict[str, Any]]:
        """
        Finds locations whose name matches the query and returns them plus their ancestor chains

        Reproduces the location tree's search on the backend: a case-insensitive, literal-substring
        match on the stored location ``name`` (regex metacharacters in the query are escaped so it
        stays a literal substring). Each match is returned together with every ancestor up to - but
        excluding - the synthetic root, resolved in a single ``$graphLookup`` (parent -> public_id)
        so the ancestor paths cost one aggregation instead of a walk per match. The flat,
        de-duplicated result is name-ordered and meant to be assembled into a pruned forest by
        build_location_forest: non-matching descendants of a match are intentionally absent.
        Requires MongoDB 3.4+ (well within the 7.0 floor)

        Cost note: an unanchored case-insensitive regex cannot be served by an index (no index on
        ``name`` would change that, and a text index would match whole words instead of
        substrings), so the match stage is a deliberate collection scan bounded by the number of
        locations - typically the smallest collection in the database

        Args:
            query (str): The search string; an empty/whitespace query yields no matches

        Raises:
            LocationsManagerGetError: If the search aggregation fails

        Returns:
            list[dict[str, Any]]: canonical documents of the matches + their ancestors, flat,
                                  de-duplicated and name-ascending
        """
        if not query.strip():
            return []

        ancestors_field: str = LocationLookupField.ANCESTORS.value

        pipeline: list[dict[str, Any]] = [
            Builder.match_({
                **Builder.regex_(
                    LocationKey.NAME.value, re.escape(query), CASE_INSENSITIVE_REGEX_OPTIONS,
                ),
                LocationKey.PUBLIC_ID.value: {'$gt': RootLocationDefault.PUBLIC_ID},
            }),
            ancestors_lookup_stage(),
            Builder.project_({MONGO_ID_KEY: 0, f"{ancestors_field}.{MONGO_ID_KEY}": 0}),
        ]

        try:
            matches: list[dict[str, Any]] = list(self.aggregate(pipeline))
        except BaseManagerIterationError as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[search_locations_with_ancestors] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err

        # collapse every match + its ancestors into a de-duplicated set, dropping the synthetic root
        collected: dict[int, dict[str, Any]] = {}

        for match in matches:
            ancestors: list[dict[str, Any]] = match.pop(ancestors_field, [])

            for location in [match, *ancestors]:
                public_id: int = location[LocationKey.PUBLIC_ID.value]

                if public_id == RootLocationDefault.PUBLIC_ID or public_id in collected:
                    continue

                collected[public_id] = to_location_document(location)

        return sort_locations_by_name(list(collected.values()))


    def get_locations_on_path_to(self, public_id: int) -> list[dict[str, Any]]:
        """
        Retrieves the location tree expanded along the ancestor path of a single CmdbLocation

        Powers the location picker's "open to the current selection" case: given a target location
        (the value stored in an object's location field), returns the flat set of all locations
        needed to render the tree already expanded down to that target - every ROOT location plus
        every direct child of each ancestor on the path from the root to the target (i.e. the full
        set of siblings at each level along the path, so the user keeps sideways context). The
        target itself and its own siblings are included (they are the deepest expanded level); the
        target's own children are NOT - like the rest of the lazy tree they load on demand via
        get_child_location_documents.

        The ancestor chain is resolved in a single ``$graphLookup`` (parent -> public_id) which
        projects nothing but the ancestors' public_ids; the sibling levels are then one ``$in``
        query over {root} + {ancestors}, returned as canonical, name-ordered documents. Returns an
        empty list when the target does not exist. Requires MongoDB 3.4+ (well within the 7.0 floor)

        Args:
            public_id (int): public_id of the target CmdbLocation to expand the tree to

        Raises:
            LocationsManagerGetError: If the path/level aggregation fails

        Returns:
            list[dict[str, Any]]: flat, de-duplicated and name-ascending list of every root location
                plus all direct children of each ancestor on the path to the target (which includes
                the target and its siblings); empty when the target does not exist
        """
        ancestors_field: str = LocationLookupField.ANCESTORS.value

        ancestor_pipeline: list[dict[str, Any]] = [
            Builder.match_({LocationKey.PUBLIC_ID.value: public_id}),
            ancestors_lookup_stage(),
            Builder.project_({
                MONGO_ID_KEY: 0,
                f"{ancestors_field}.{LocationKey.PUBLIC_ID.value}": 1,
            }),
        ]

        try:
            matches: list[dict[str, Any]] = list(self.aggregate(ancestor_pipeline))

            # Target does not exist -> nothing to expand to
            if not matches:
                return []

            ancestors: list[dict[str, Any]] = matches[0].get(ancestors_field, [])

            # The parents whose direct children make up the expanded levels: the synthetic root plus
            # every ancestor of the target (the synthetic root is excluded from the ancestor chain)
            expand_parents: set[int] = {RootLocationDefault.PUBLIC_ID}
            expand_parents |= {
                ancestor[LocationKey.PUBLIC_ID.value]
                for ancestor in ancestors
                if ancestor[LocationKey.PUBLIC_ID.value] != RootLocationDefault.PUBLIC_ID
            }

            # One $in over all sibling levels at once (children of the root + of each ancestor)
            documents: list[dict[str, Any]] = self.get_many(
                **{LocationKey.PARENT.value: {'$in': list(expand_parents)}}
            )

            return sort_locations_by_name([to_location_document(document) for document in documents])
        except (BaseManagerGetError, BaseManagerIterationError) as err:
            raise LocationsManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_locations_on_path_to] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_location(self, object_id: int, data: dict[str, Any]) -> None:
        """
        Updates the CmdbLocation linked to the given CmdbObject

        Takes a document like ``insert_location``, and a **partial** one is normal: the object
        mirror sends only the keys an object write can change (``parent`` and ``name``), which
        BaseManager.update applies as a '$set'

        Args:
            object_id (int): public_id of the CmdbObject whose CmdbLocation should be updated
            data (dict[str, Any]): The CmdbLocation keys to write

        Raises:
            LocationsManagerUpdateError: When the update operation fails
        """
        try:
            self.update({LocationKey.OBJECT_ID.value: object_id}, data)
        except Exception as err:
            LOGGER.error("[update_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerUpdateError(str(err)) from err


    def update_locations_by_type(self, type_id: int, data: dict[str, Any]) -> bool:
        """
        Updates all CmdbLocations of the provided CmdbTypes public_id

        An empty payload is a no-op rather than an error - the type update path calls this with
        whatever of the mirrored type metadata (label, icon, selectable) actually changed, which is
        regularly nothing. The return value tells the caller which of the two happened

        Args:
            type_id (int): public_id of CmdbType for which the CmdbLocations should be updated
            data (dict[str, Any]): the data which should be applied

        Raises:
            LocationsManagerUpdateError: When the Update-Operation fails

        Returns:
            bool: True when an update was executed, False when there was no data to apply
        """
        try:
            if not data:
                LOGGER.debug("No data provided to [update_locations_by_type] therefore no update executed!")
                return False

            self.update_many(criteria={LocationKey.TYPE_ID.value: type_id}, update=data)

            return True
        except BaseManagerUpdateError as err:
            raise LocationsManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[update_locations_by_type] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def _reparent_children_to_grandparent(self, public_id: int) -> None:
        """
        Re-parents the direct children of a CmdbLocation onto that location's own parent

        Looks up the location's ``parent`` and points every CmdbLocation currently parented to
        ``public_id`` at it, in a single ``update_many`` (cost independent of the number of
        children). A no-op when the location does not exist or has no children. Called by
        :meth:`delete_location` so a deleted node's subtree is promoted one level instead of
        being orphaned

        ``parent`` is nullable in the schema, so the promotion target may be missing, None or (in a
        document the schema never validated) some other non-id value. That cannot be written onto the
        children - no tree level queries for a null parent, so they would
        silently disappear from the tree - and the deletion is refused instead. A node without a
        usable parent that has no children at all is still deletable: there is nothing to promote

        Args:
            public_id (int): public_id of the CmdbLocation whose children should be promoted

        Raises:
            LocationsManagerGetError: If the children lookup of a parentless location fails
            LocationsManagerUpdateError: If the location carries no usable parent but has children
            BaseManagerGetError: If the location lookup fails
            BaseManagerUpdateError: If the re-parenting update fails
        """
        location: dict[str, Any] | None = self.get_one_by({LocationKey.PUBLIC_ID.value: public_id})

        if not location:
            return

        grandparent_id: Any = location.get(LocationKey.PARENT.value)

        # bool is a subclass of int, so it has to be ruled out explicitly - a 'parent': True would
        # otherwise be written onto every child exactly like a None would
        if not isinstance(grandparent_id, int) or isinstance(grandparent_id, bool):
            if public_id in self.get_parents_with_children([public_id]):
                raise LocationsManagerUpdateError(
                    f"The Location with ID:{public_id} has no parent to promote its children to!"
                )

            return

        self.update_many(
            criteria={LocationKey.PARENT.value: public_id},
            update={LocationKey.PARENT.value: grandparent_id},
        )


    def delete_location(self, public_id: int) -> bool:
        """
        Deletes a CmdbLocation from the database, promoting its direct children

        Before the location is removed, every CmdbLocation that has it as ``parent`` is re-parented
        onto the deleted location's own parent (its grandparent). This keeps the location tree
        connected: the deleted node's subtree simply shifts up one level rather than being orphaned.
        The promotion is a separate write from the deletion and there is no transaction around the
        pair (see the open discussion-backlog item), so a deletion that fails afterwards leaves the
        children already promoted

        The synthetic root (RootLocationDefault.PUBLIC_ID) is refused: it is the anchor every tree
        level is queried against, it is not backed by a CmdbObject, and its own ``parent`` sentinel
        is 0 - deleting it would move every top-level location out of the tree

        Args:
            public_id (int): public_id of the CmdbLocation which should be deleted

        Raises:
            LocationsManagerDeleteError: When the CmdbLocation is the synthetic root, or when the
                                         delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        if public_id == RootLocationDefault.PUBLIC_ID:
            raise LocationsManagerDeleteError('The root Location can not be deleted!')

        try:
            self._reparent_children_to_grandparent(public_id)

            return self.delete({LocationKey.PUBLIC_ID.value: public_id})
        except (BaseManagerGetError, BaseManagerUpdateError, BaseManagerDeleteError) as err:
            raise LocationsManagerDeleteError(str(err)) from err
        except Exception as err:
            LOGGER.error("[delete_location] Exception: %s. Type: %s", err, type(err))
            raise LocationsManagerDeleteError(str(err)) from err
