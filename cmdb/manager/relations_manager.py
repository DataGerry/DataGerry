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
from typing import Any

from pymongo import ASCENDING

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.relation_model import CmdbRelation, RelationKey
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.relations_manager import RELATIONS_MANAGER_ERRORS, RelationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

# What a refused CmdbType delete names of each blocking CmdbRelation
RELATION_IDENTITY_PROJECTION: dict[str, int] = {
    RelationKey.PUBLIC_ID.value: 1,
    RelationKey.RELATION_NAME.value: 1,
    MONGO_ID_FIELD: 0,
}

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               RelationsManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class RelationsManager(GenericManager):
    """
    Manages CmdbRelation documents on top of GenericManager

    Keeps the named public API (``insert_relation`` / ``get_relation`` / ``iterate`` /
    ``update_relation`` / ``delete_relation``) used by the existing route call sites, delegating the
    CRUD + per-operation error wrapping to GenericManager. Adds the relation-specific
    ``remove_type_from_relations`` (server-side cascade on type deletion)

    The section/field diff of an update is pure data work and needs no database, so it lives with the
    route helpers (``relations_helper.get_added_and_removed_fields``) rather than here

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the RelationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the 'dbm' should connect to. Only used in CLOUD_MODE
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
        data[RelationKey.PUBLIC_ID.value] = public_id

        self.update_item(public_id, data)


    def remove_type_from_relations(self, type_id: int) -> None:
        """
        Removes a type_id from all relation parent/child lists

        Part of the CmdbType delete's follow-up. The delete is refused while the type is the only one on a side of
        any relation (``find_relations_left_without_types``), so the pull never empties a side here

        Args:
            type_id (int): public_id of the CmdbType which should be removed from all relations
        """
        criteria: dict[str, list[dict[str, int]]] = {
            '$or': [
                {RelationKey.PARENT_TYPE_IDS.value: type_id},
                {RelationKey.CHILD_TYPE_IDS.value: type_id}
            ]
        }

        update: dict[str, dict[str, int]] = {
            '$pull': {
                RelationKey.PARENT_TYPE_IDS.value: type_id,
                RelationKey.CHILD_TYPE_IDS.value: type_id
            }
        }

        self.update_many_raw(criteria, update)

    def find_relations_left_without_types(self, type_id: int) -> list[dict[str, Any]]:
        """
        Finds the CmdbRelations whose parent or child side allows the given CmdbType ALONE

        Those are the definitions ``remove_type_from_relations`` would leave with an empty side, which
        ``CmdbRelation.SCHEMA`` forbids (``empty: False``): no instance could be created on it, an unchanged save
        is refused, and the data-model import refuses the entry. The CmdbType delete refuses while any exists.
        A side holding the type next to another one is not found - pulling it leaves that side usable

        Args:
            type_id (int): public_id of the CmdbType about to be deleted

        Raises:
            RelationsManagerGetError: When the CmdbRelations could not be read

        Returns:
            list[dict[str, Any]]: ``public_id`` and ``relation_name`` of each such CmdbRelation, in ``public_id``
                order; empty when the delete would leave every relation usable
        """
        try:
            return self.find(
                criteria={'$or': [
                    {side: {'$all': [type_id], '$not': {'$elemMatch': {'$ne': type_id}}}}
                    for side in (RelationKey.PARENT_TYPE_IDS.value, RelationKey.CHILD_TYPE_IDS.value)
                ]},
                projection=RELATION_IDENTITY_PROJECTION,
                sort=[(RelationKey.PUBLIC_ID.value, ASCENDING)],
            )
        except BaseManagerGetError as err:
            raise RelationsManagerGetError(err) from err

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
