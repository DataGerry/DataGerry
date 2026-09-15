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
Database update 20260226: migrate legacy ObjectLinks into the DgObjectLinks relation

The legacy 'framework.links' collection held undecorated object-to-object links ('primary' /
'secondary' object public_ids). Relations replaced them, so this update rebuilds the same
information as CmdbObjectRelations under one catch-all CmdbRelation named 'DgObjectLinks' that
permits every type present at migration time on both ends.

Operator notes:

* The migration is **one-way**: there is no reverse update. The legacy collection is deliberately
  left in place (nothing reads or writes it any more), so the source data survives the upgrade.
* The catch-all relation's type lists are **frozen at migration time**. A CmdbType created after
  the upgrade is not permitted on either end, so it cannot use the migrated relation - editing the
  relation afterwards is a normal user task.
* Every migrated CmdbObjectRelation is attributed to ``MIGRATION_AUTHOR_ID`` - the migration runs
  during startup, outside any request, so there is no acting user to record.
* A link whose parent or child object no longer exists is skipped ("skipped" always means "not
  written", never "written empty").

**Re-run safety.** The updater framework applies a migration only once, but the version is persisted
as the very last statement of ``start_update`` and there are no multi-document transactions, so any
failure re-enters this migration on the next boot on top of whatever the crashed run committed.
Every write phase is therefore repeatable and converges to the same end state:

* the mapper relation is *created or adopted* by name, never created twice;
* an already-migrated (parent, child) pair is skipped, so a partially written batch is completed
  rather than duplicated (``insert_many`` is unordered, so a failed batch can leave a subset behind);
* the pair set is extended while the batch is built, so a legacy link duplicated in the source
  collection yields one CmdbObjectRelation regardless of how far an earlier run got;
* ``reserve_public_ids`` is an atomic counter increment, so an abandoned block is only an id gap.

Every literal this module writes or queries is a **local, frozen constant**: a migration is a
historical record of the 2026-02-26 schema, so it must keep reading and writing those names even if
the live models rename them later. That is why nothing here is imported from the model classes or
their key enums - see the constants block below.

The pure builders / collectors are module-level functions (directly importable and testable); the
methods on the class are exactly the ones that touch the database.
"""
from typing import Any
from datetime import datetime, timezone

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

# Collection names as of 2026-02-26. Frozen on purpose: reading them from CmdbRelation.COLLECTION /
# CmdbObjectRelation.COLLECTION would silently redirect this migration if a collection is ever renamed
OBJECT_LINK_COLLECTION: str = "framework.links"
RELATION_COLLECTION: str = "framework.relations"
OBJECT_RELATION_COLLECTION: str = "framework.objectRelations"

# The catch-all relation hosting every migrated link, and the presentation values it is created with
MAPPER_RELATION_NAME: str = "DgObjectLinks"
MAPPER_PARENT_SIDE_LABEL: str = "to secondary"
MAPPER_CHILD_SIDE_LABEL: str = "to primary"
MAPPER_RELATION_ICON: str = "fa fa-cube"
MAPPER_RELATION_COLOR: str = "#e9ecef"

# Author recorded on every migrated CmdbObjectRelation: the migration runs at startup without a
# request user, so it is attributed to the bootstrap admin (public_id 1)
MIGRATION_AUTHOR_ID: int = 1

# Keys of a legacy 'framework.links' document
LINK_PARENT_FIELD: str = "primary"
LINK_CHILD_FIELD: str = "secondary"

# Document keys read from / written to the framework collections
PUBLIC_ID_FIELD: str = "public_id"
TYPE_ID_FIELD: str = "type_id"
RELATION_NAME_FIELD: str = "relation_name"
RELATION_ID_FIELD: str = "relation_id"
RELATION_PARENT_ID_FIELD: str = "relation_parent_id"
RELATION_CHILD_ID_FIELD: str = "relation_child_id"
RELATION_PARENT_TYPE_ID_FIELD: str = "relation_parent_type_id"
RELATION_CHILD_TYPE_ID_FIELD: str = "relation_child_type_id"
RELATION_NAME_PARENT_FIELD: str = "relation_name_parent"
RELATION_NAME_CHILD_FIELD: str = "relation_name_child"
RELATION_ICON_PARENT_FIELD: str = "relation_icon_parent"
RELATION_ICON_CHILD_FIELD: str = "relation_icon_child"
RELATION_COLOR_PARENT_FIELD: str = "relation_color_parent"
RELATION_COLOR_CHILD_FIELD: str = "relation_color_child"
PARENT_TYPE_IDS_FIELD: str = "parent_type_ids"
CHILD_TYPE_IDS_FIELD: str = "child_type_ids"
DESCRIPTION_FIELD: str = "description"
SECTIONS_FIELD: str = "sections"
FIELDS_FIELD: str = "fields"
AUTHOR_ID_FIELD: str = "author_id"
FIELD_VALUES_FIELD: str = "field_values"
CREATION_TIME_FIELD: str = "creation_time"
MONGO_ID_FIELD: str = "_id"
# -------------------------------------------------------------------------------------------------------------------- #
#                                                     PURE HELPERS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def collect_linked_object_ids(object_links: list[dict[str, Any]]) -> set[int]:
    """
    Collects the public_ids of every object referenced by the legacy links

    Args:
        object_links (list[dict[str, Any]]): The legacy 'framework.links' documents

    Returns:
        set[int]: Deduplicated public_ids of all parent (primary) and child (secondary) objects
    """
    linked_object_ids: set[int] = set()

    for link in object_links:
        linked_object_ids.add(link[LINK_PARENT_FIELD])
        linked_object_ids.add(link[LINK_CHILD_FIELD])

    return linked_object_ids


def get_mapper_relation(existing_type_ids: list[int]) -> dict[str, Any]:
    """
    Builds the 'DgObjectLinks' CmdbRelation document that hosts the migrated object links

    The type lists are the caller's snapshot of every existing CmdbType and are stored as-is, so the
    relation is frozen to the types present at migration time. The presentation values (labels, icons,
    colors) are the 2026-02-26 defaults and are only written on creation - a user editing them
    afterwards is never overwritten, since a re-run adopts the relation instead of rebuilding it

    Args:
        existing_type_ids (list[int]): public_ids of all types, allowed on both relation ends

    Returns:
        dict[str, Any]: The relation document ready to insert (public_id is assigned by the insert)
    """
    return {
        RELATION_NAME_FIELD: MAPPER_RELATION_NAME,
        RELATION_NAME_PARENT_FIELD: MAPPER_PARENT_SIDE_LABEL,
        RELATION_ICON_PARENT_FIELD: MAPPER_RELATION_ICON,
        RELATION_COLOR_PARENT_FIELD: MAPPER_RELATION_COLOR,
        RELATION_NAME_CHILD_FIELD: MAPPER_CHILD_SIDE_LABEL,
        RELATION_ICON_CHILD_FIELD: MAPPER_RELATION_ICON,
        RELATION_COLOR_CHILD_FIELD: MAPPER_RELATION_COLOR,
        PARENT_TYPE_IDS_FIELD: existing_type_ids,
        CHILD_TYPE_IDS_FIELD: existing_type_ids,
        DESCRIPTION_FIELD: "",
        SECTIONS_FIELD: [],
        FIELDS_FIELD: [],
    }


def get_object_relation_dict(
        parent_id: int,
        child_id: int,
        parent_type_id: int,
        child_type_id: int,
        relation_id: int,
    ) -> dict[str, Any]:
    """
    Builds a single CmdbObjectRelation document linking a parent object to a child object

    The legacy link's 'primary' object becomes the parent and its 'secondary' the child. The document
    carries no field values (the legacy links had none) and is attributed to ``MIGRATION_AUTHOR_ID`` -
    the migration has no acting user

    Args:
        parent_id (int): public_id of the parent (primary) object
        child_id (int): public_id of the child (secondary) object
        parent_type_id (int): type public_id of the parent object
        child_type_id (int): type public_id of the child object
        relation_id (int): public_id of the owning 'DgObjectLinks' relation

    Returns:
        dict[str, Any]: The object-relation document (public_id is assigned by the caller)
    """
    return {
        RELATION_ID_FIELD: relation_id,
        RELATION_PARENT_ID_FIELD: parent_id,
        RELATION_CHILD_ID_FIELD: child_id,
        RELATION_PARENT_TYPE_ID_FIELD: parent_type_id,
        RELATION_CHILD_TYPE_ID_FIELD: child_type_id,
        AUTHOR_ID_FIELD: MIGRATION_AUTHOR_ID,
        FIELD_VALUES_FIELD: [],
        CREATION_TIME_FIELD: datetime.now(timezone.utc)
    }


def build_object_relations(
        object_links: list[dict[str, Any]],
        object_type_map: dict[int, int],
        migrated_pairs: set[tuple[int, int]],
        relation_id: int,
    ) -> list[dict[str, Any]]:
    """
    Turns the legacy links into the CmdbObjectRelation documents that are still missing

    A link is skipped - producing no document at all - when its (parent, child) pair is already on the
    relation or when either object no longer exists (a broken link). The pair set is copied and extended
    while the batch is built, so the same pair is emitted once no matter how often it appears in the
    source collection or how far an earlier, crashed run got; the caller's set is never mutated

    Args:
        object_links (list[dict[str, Any]]): The legacy 'framework.links' documents
        object_type_map (dict[int, int]): {object public_id: type public_id} of the linked objects
        migrated_pairs (set[tuple[int, int]]): (parent, child) pairs the relation already holds
        relation_id (int): public_id of the owning 'DgObjectLinks' relation

    Returns:
        list[dict[str, Any]]: The documents to insert, in source order (public_ids not yet assigned)
    """
    seen_pairs: set[tuple[int, int]] = set(migrated_pairs)
    relations_to_insert: list[dict[str, Any]] = []

    for link in object_links:
        parent_id: int = link[LINK_PARENT_FIELD]
        child_id: int = link[LINK_CHILD_FIELD]

        # Skip an already migrated pair (previous run) or a repeat within this run
        if (parent_id, child_id) in seen_pairs:
            continue

        parent_type_id: int | None = object_type_map.get(parent_id)
        child_type_id: int | None = object_type_map.get(child_id)

        # Skip broken links
        if parent_type_id is None or child_type_id is None:
            continue

        seen_pairs.add((parent_id, child_id))
        relations_to_insert.append(
            get_object_relation_dict(
                parent_id=parent_id,
                child_id=child_id,
                parent_type_id=parent_type_id,
                child_type_id=child_type_id,
                relation_id=relation_id,
            )
        )

    return relations_to_insert

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260226 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260226(BaseDatabaseUpdate):
    """
    Migrates legacy ObjectLinks into the 'DgObjectLinks' relation as CmdbObjectRelations

    One-way and re-runnable; the catch-all relation's type lists are frozen at migration time and the
    legacy collection is kept - see the module docstring for the operator-facing details

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20260226


    def description(self) -> str:
        return "Maps all ObjectLinks onto a Relation"


    def start_update(self) -> None:
        """
        Creates (or adopts) the 'DgObjectLinks' relation and maps every legacy object link onto it

        Each framework.links entry becomes one CmdbObjectRelation between the two objects, carrying
        their type public_ids. The relation is created with every currently existing CmdbType allowed
        on both ends (frozen at migration time) or adopted when one of that name is already present,
        in which case the pairs it already holds are read first so nothing is duplicated.

        A link is skipped - producing no document at all - when its pair is already migrated, when the
        same pair repeats inside this run, or when either object no longer exists. An empty legacy
        collection is a no-op (no relation is created) but the updater version is still bumped, so the
        migration does not run again. The version bump is the last statement: a failure anywhere before
        it leaves the version untouched and the whole migration is repeated on the next boot, which is
        safe by construction (see the module docstring)

        Raises:
            UpdaterException: If the migration fails at any point (every error is wrapped)
        """
        try:
            object_links: list[dict[str, Any]] = self.read_legacy_links()

            if object_links:
                object_type_map: dict[int, int] = self.build_object_type_map(
                    collect_linked_object_ids(object_links)
                )
                mapper_relation_id, migrated_pairs = self.resolve_mapper_relation()

                self.insert_object_relations(
                    build_object_relations(object_links, object_type_map, migrated_pairs, mapper_relation_id)
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err

# ------------------------------------------------- DATABASE ACCESS -------------------------------------------------- #

    def read_legacy_links(self) -> list[dict[str, Any]]:
        """
        Reads every legacy object link, projected down to the two object ids

        Returns:
            list[dict[str, Any]]: The 'framework.links' documents ({primary, secondary}); empty on an
                installation that never had object links
        """
        return list(self.dbm.find(
            collection=OBJECT_LINK_COLLECTION,
            db_name=self.db_name,
            filter={},
            projection={LINK_PARENT_FIELD: 1, LINK_CHILD_FIELD: 1, MONGO_ID_FIELD: 0}
        ))


    def build_object_type_map(self, linked_object_ids: set[int]) -> dict[int, int]:
        """
        Resolves the type of every linked object in one query

        An id missing from the result belongs to a deleted object, which is how a broken link is
        detected downstream

        Args:
            linked_object_ids (set[int]): public_ids of the objects the legacy links reference

        Returns:
            dict[int, int]: {object public_id: type public_id} for every object that still exists
        """
        object_documents: list[dict[str, Any]] = self.objects_manager.find(
            criteria={PUBLIC_ID_FIELD: {"$in": list(linked_object_ids)}},
            projection={PUBLIC_ID_FIELD: 1, TYPE_ID_FIELD: 1, MONGO_ID_FIELD: 0}
        )

        return {
            object_document[PUBLIC_ID_FIELD]: object_document[TYPE_ID_FIELD]
            for object_document in object_documents
        }


    def resolve_mapper_relation(self) -> tuple[int, set[tuple[int, int]]]:
        """
        Returns the catch-all relation to migrate onto, creating it when it does not exist yet

        One read answers both questions - whether the relation exists and what its public_id is. An
        existing relation is adopted as-is (an earlier crashed run, or a user-created one) and the pairs
        it already holds are read so they are not migrated twice; a freshly created relation cannot hold
        any pair, so no second query is paid for it

        Returns:
            tuple[int, set[tuple[int, int]]]: public_id of the relation, and the (parent, child) pairs
                already migrated onto it
        """
        existing_relation: dict[str, Any] | None = next(
            self.dbm.find(
                RELATION_COLLECTION,
                self.db_name,
                filter={RELATION_NAME_FIELD: MAPPER_RELATION_NAME},
                projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0}
            ),
            None,
        )

        if existing_relation is None:
            return self.create_mapper_relation(), set()

        mapper_relation_id: int = existing_relation[PUBLIC_ID_FIELD]

        return mapper_relation_id, self.read_migrated_pairs(mapper_relation_id)


    def create_mapper_relation(self) -> int:
        """
        Creates the catch-all relation, permitting every CmdbType that exists right now

        The type snapshot is only needed on this path, so an installation that already carries the
        relation never pays the full type read

        Returns:
            int: public_id assigned to the created relation
        """
        all_types: list[dict[str, Any]] = self.types_manager.find(
            criteria={}, projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0}
        )
        existing_type_ids: list[int] = [a_type[PUBLIC_ID_FIELD] for a_type in all_types]

        return self.dbm.insert(
            RELATION_COLLECTION,
            self.db_name,
            get_mapper_relation(existing_type_ids)
        )


    def read_migrated_pairs(self, mapper_relation_id: int) -> set[tuple[int, int]]:
        """
        Reads the object pairs already migrated onto the given relation

        This is what makes a repeated run (or the completion of a partially written batch) skip the
        documents that are already there

        Args:
            mapper_relation_id (int): public_id of the 'DgObjectLinks' relation

        Returns:
            set[tuple[int, int]]: The (parent object id, child object id) pairs already present
        """
        existing_object_relations: list[dict[str, Any]] = list(self.dbm.find(
            collection=OBJECT_RELATION_COLLECTION,
            db_name=self.db_name,
            filter={RELATION_ID_FIELD: mapper_relation_id},
            projection={
                RELATION_PARENT_ID_FIELD: 1,
                RELATION_CHILD_ID_FIELD: 1,
                MONGO_ID_FIELD: 0,
            }
        ))

        return {
            (relation[RELATION_PARENT_ID_FIELD], relation[RELATION_CHILD_ID_FIELD])
            for relation in existing_object_relations
        }


    def insert_object_relations(self, relations_to_insert: list[dict[str, Any]]) -> None:
        """
        Assigns a reserved public_id to each document and writes them in one bulk insert

        A no-op for an empty batch (nothing to migrate, or everything already migrated). The ids come
        from one atomic counter increment, so an abandoned reservation only leaves an id gap; ``strict``
        zipping makes a count mismatch fail loudly instead of silently inserting an id-less document

        Args:
            relations_to_insert (list[dict[str, Any]]): The documents to write
        """
        if not relations_to_insert:
            return

        reserved_ids: list[int] = self.dbm.reserve_public_ids(
            OBJECT_RELATION_COLLECTION,
            self.db_name,
            amount=len(relations_to_insert)
        )

        for relation, public_id in zip(relations_to_insert, reserved_ids, strict=True):
            relation[PUBLIC_ID_FIELD] = public_id

        self.dbm.insert_many(
            collection=OBJECT_RELATION_COLLECTION,
            db_name=self.db_name,
            data=relations_to_insert,
            skip_public=True
        )
