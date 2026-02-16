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
This module contains the implementation of the ObjectRelationsManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.object_relation_model import CmdbObjectRelation

from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.object_relations_manager import (
    ObjectRelationsManagerInitError,
    ObjectRelationsManagerInsertError,
    ObjectRelationsManagerGetError,
    ObjectRelationsManagerIterationError,
    ObjectRelationsManagerUpdateError,
    ObjectRelationsManagerDeleteError,
)
from cmdb.errors.models.cmdb_object_relation import (
    CmdbObjectRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            ObjectRelationsManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectRelationsManager(BaseManager):
    """
    The ObjectRelationsManager handles the interaction between the CmdbObjectRelations-API and the database
    `Extends`: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection for the ObjectRelationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            ObjectRelationsManagerInitError: If the ObjectRelationsManager could not be initialised
        """
        try:
            super().__init__(CmdbObjectRelation.COLLECTION, dbm, database)
        except Exception as err:
            raise ObjectRelationsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object_relation(self, object_relation: dict) -> int:
        """
        Insert a CmdbObjectRelation into the database

        Args:
            object_relation (dict): Raw data of the CmdbObjectRelation

        Raises:
            ObjectRelationsManagerInsertError: When a CmdbObjectRelation could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbObjectRelation
        """
        try:
            if isinstance(object_relation, CmdbObjectRelation):
                object_relation = CmdbObjectRelation.to_json(object_relation)

            return self.insert(object_relation)
        except CmdbObjectRelationToJsonError as err:
            raise ObjectRelationsManagerInsertError(err) from err
        except BaseManagerInsertError as err:
            raise ObjectRelationsManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_object_relation] Exception: %s. Type: %s", err, type(err))
            raise ObjectRelationsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object_relation(self, public_id: int) -> dict | None:
        """
        Retrieves a CmdbObjectRelation from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelation

        Raises:
            ObjectRelationsManagerGetError: When a CmdbObjectRelation could not be retrieved

        Returns:
            dict | None: Dict representation of the CmdbObjectRelation attributes if it exists else None
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise ObjectRelationsManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbObjectRelation]:
        """
        Retrieves multiple CmdbObjectRelations

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjectRelations should be retrieved

        Raises:
            ObjectRelationsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbRelation]: All CmdbObjectRelations matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbObjectRelation] = IterationResult(aggregation_result,
                                                                                    total,
                                                                                    CmdbObjectRelation)

            return iteration_result
        except Exception as err:
            raise ObjectRelationsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_object_relation(self, public_id:int, data: dict) -> None:
        """
        Updates a CmdbObjectRelation in the database

        Args:
            public_id (int): public_id of the CmdbObjectRelation which should be updated
            data (dict): The data with new values for the CmdbObjectRelation

        Raises:
            ObjectRelationsManagerUpdateError: When the update operation fails
        """
        try:
            self.update({'public_id':public_id}, CmdbObjectRelation.to_json(data))
        except Exception as err:
            LOGGER.error("[update_object_relation] Exception: %s. Type: %s", err, type(err))
            raise ObjectRelationsManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object_relation(self, public_id: int) -> bool:
        """
        Deletes a CmdbObjectRelation from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelation which should be deleted

        Raises:
            ObjectRelationsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete({'public_id':public_id})
        except BaseManagerDeleteError as err:
            raise ObjectRelationsManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def delete_invalidated_object_relations(
            self,
            relation_id: int,
            invalid_ids: list[int],
            is_parent_ids: bool) -> None:
        """
        Deletes invalid CmdbObjectRelations based on the given `relation_id` and `invalid_ids`

        This method checks whether the invalid IDs are related to the parent or child types
        of the given CmdbRelation. It then constructs a query to find the invalid CmdbObjectRelations
        and deletes them.

        Args:
            relation_id (int): The public_id of the CmdbRelation for which invalid
                               CmdbObjectRelations should be deleted
            invalid_ids (list[int]): A list of IDs (either parent or child) that should be invalidated
            is_parent_ids (bool): A flag indicating whether the invalid IDs belong to parent type relations
                                  (True) or child type relations (False)
        """
        query = {"$and": [{"relation_id": relation_id}, {"relation_child_type_id": { "$in": invalid_ids }}]}

        if is_parent_ids:
            query = {"$and": [{"relation_id": relation_id}, {"relation_parent_type_id": { "$in": invalid_ids }}]}

        invalid_object_relations = self.find_all(criteria=query)

        for invalid_object_relation in invalid_object_relations:
            self.delete({"public_id": invalid_object_relation['public_id']})


    def update_changed_fields(self, relation_id: int, changed_fields: dict) -> None:
        """
        Updates all CmdbObjectRelations that reference the given CmdbRelation

        - **Removes** any fields that have been deleted
        - **Adds** new fields with an empty value

        Args:
            relation_id (int): The public_id of the CmdbRelation whose fields were changed
            changed_fields (dict): A dictionary with two keys:
                - "added" (list[str]): Field names that were newly introduced
                - "removed" (list[str]): Field names that should be removed
        """
        affected_object_relations = self.get_many(filter={'relation_id':relation_id})

        for obj_relation in affected_object_relations:
            updated_field_values = []

            # Remove fields that are in 'removed'
            for field in obj_relation['field_values']:
                if field['name'] not in changed_fields['removed']:
                    updated_field_values.append(field)

            # Add new fields from 'added' with an empty value
            for new_field in changed_fields['added']:
                updated_field_values.append({'name': new_field, 'value': None})

            # Update object relation
            obj_relation['field_values'] = updated_field_values

            # Save the updated object relation
            self.update_object_relation(obj_relation['public_id'], obj_relation)
