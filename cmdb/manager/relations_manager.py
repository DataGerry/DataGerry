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
This module contains the implementation of the RelationsManager
"""
from logging import Logger, getLogger
<<<<<<< HEAD

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
=======
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
>>>>>>> origin/version-3.2
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.relation_model import CmdbRelation
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.relations_manager import RELATIONS_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
<<<<<<< HEAD
=======

# Document field carrying the CmdbRelation identity (pinned on update so a payload can never rewrite it)
PUBLIC_ID_FIELD: str = 'public_id'
>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                               RelationsManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class RelationsManager(GenericManager):
    """
    Manages CmdbRelation documents on top of GenericManager

    Keeps the named public API (``insert_relation`` / ``get_relation`` / ``iterate`` /
    ``update_relation`` / ``delete_relation``) used by the existing route call sites, delegating the
    CRUD + per-operation error wrapping to GenericManager. Adds the relation-specific operations
    ``remove_type_from_relations`` (server-side cascade on type deletion) and
    ``get_added_and_removed_fields`` (section/field diff helper)

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the RelationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the 'dbm' should connect to. Only used in CLOUD_MODE

        Raises:
            RelationsManagerInitError: If the RelationsManager could not be initialised
        """
        super().__init__(dbm, CmdbRelation, RELATIONS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_relation(self, relation: CmdbRelation | dict[str, Any]) -> int:
        """
        Insert a CmdbRelation into the database

        Args:
            relation (CmdbRelation | dict[str, Any]): Raw data or model instance of the CmdbRelation

        Raises:
            RelationsManagerInsertError: When a CmdbRelation could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbRelation
        """
        return self.insert_item(relation)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_relation(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbRelation from the database

        Args:
            public_id (int): public_id of the CmdbRelation

        Raises:
            RelationsManagerGetError: When a CmdbRelation could not be retrieved

        Returns:
            dict[str, Any] | None: A dict representation of the CmdbRelation if found, otherwise None
        """
        return self.get_item(public_id, as_dict=True)


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbRelation]:
        """
        Retrieves multiple CmdbRelations

        Args:
            builder_params (BuilderParameters): Filter for which CmdbRelations should be retrieved

        Raises:
            RelationsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbRelation]: All CmdbRelations matching the filter
        """
        return self.iterate_items(builder_params)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_relation(self, public_id: int, data: CmdbRelation | dict[str, Any]) -> None:
        """
        Updates a CmdbRelation in the database

        The document identity is pinned to ``public_id`` so a payload ``public_id`` can never rewrite
        the stored id. Updating an id that does not exist is a no-op (the underlying update does not
        upsert)

        Args:
            public_id (int): public_id of the CmdbRelation which should be updated
            data (CmdbRelation | dict[str, Any]): The new data for the CmdbRelation

        Raises:
            RelationsManagerUpdateError: When the update operation fails
        """
        if isinstance(data, CmdbRelation):
            data = CmdbRelation.to_json(data)

        # Pin the identity: a payload public_id can never rewrite the document's id
        data[PUBLIC_ID_FIELD] = public_id

        self.update_item(public_id, data)


    def remove_type_from_relations(self, type_id: int) -> None:
        """
        Removes a type_id from all relation parent/child lists

        Args:
            type_id (int): public_id of the CmdbType which should be removed from all relations
        """
        criteria: dict[str, list[dict[str, int]]] = {
            '$or': [
                {'parent_type_ids': type_id},
                {'child_type_ids': type_id}
            ]
        }

        update: dict[str, dict[str, int]] = {
            '$pull': {
                'parent_type_ids': type_id,
                'child_type_ids': type_id
            }
        }

        self.update_many(criteria=criteria, update=update, plain=True)


    def remove_type_from_relations(self, type_id: int) -> None:
        """
        Removes a type_id from all relation parent/child lists
        
        Args:
            type_id (int): public_id of the CmdbType which should be removed from all relations
        """
        criteria: dict[str, list[dict[str, int]]] = {
            '$or': [
                {'parent_type_ids': type_id},
                {'child_type_ids': type_id}
            ]
        }

        update: dict[str, dict[str, int]] = {
            '$pull': {
                'parent_type_ids': type_id,
                'child_type_ids': type_id
            }
        }

        self.update_many(criteria=criteria, update=update, plain=True)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_relation(self, public_id: int) -> bool:
        """
        Deletes a CmdbRelation from the database

        Args:
            public_id (int): public_id of the CmdbRelation which should be deleted

        Raises:
            RelationsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        return self.delete_item(public_id)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_added_and_removed_fields(self,
                                     old_relation: dict[str, Any],
                                     new_relation: dict[str, Any]) -> dict[str, list[str]]:
        """
        Compares the 'sections' of two CmdbRelations to find which fields were added or removed

        Collects every field identifier referenced by the sections of each relation and returns
        the set difference in both directions.

        Args:
            old_relation (dict[str, Any]): The CmdbRelation before the change (carries 'sections')
            new_relation (dict[str, Any]): The CmdbRelation after the change (carries 'sections')

        Returns:
            dict[str, list[str]]: A dict with keys 'added' and 'removed', each a list of the field
                identifiers that were added to / removed from the relation's sections
        """
        old_fields: set[str] = set()
        new_fields: set[str] = set()

        # Collect every field identifier referenced across the relation's sections
        for section in old_relation.get("sections", []):
            old_fields.update(section.get("fields", []))

        for section in new_relation.get("sections", []):
            new_fields.update(section.get("fields", []))

        return {
            "added": list(new_fields - old_fields),
            "removed": list(old_fields - new_fields),
        }
