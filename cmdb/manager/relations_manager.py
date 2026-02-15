# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import logging

from cmdb.database import MongoDatabaseManager

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.relation_model import CmdbRelation

from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
from cmdb.errors.models.cmdb_relation import (
    CmdbRelationToJsonError,
)
from cmdb.errors.manager.relations_manager import (
    RelationsManagerInitError,
    RelationsManagerInsertError,
    RelationsManagerGetError,
    RelationsManagerIterationError,
    RelationsManagerUpdateError,
    RelationsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               RelationsManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class RelationsManager(BaseManager):
    """
    The RelationsManager manages the interaction between CmdbRelations and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection for the RelationsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            RelationsManagerInitError: If the RelationsManager could not be initialised
        """
        try:
            super().__init__(CmdbRelation.COLLECTION, dbm, database)
        except Exception as err:
            raise RelationsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_relation(self, relation: CmdbRelation | dict) -> int:
        """
        Insert a CmdbRelation into the database

        Args:
            relation (CmdbRelation | dict): Raw data of the CmdbRelation

        Raises:
            RelationsManagerInsertError: When a CmdbRelation could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbRelation
        """
        try:
            if isinstance(relation, CmdbRelation):
                relation = CmdbRelation.to_json(relation)

            return self.insert(relation)
        except (BaseManagerInsertError, CmdbRelationToJsonError) as err:
            raise RelationsManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_relation] Exception: %s. Type: %s", err, type(err))
            raise RelationsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_relation(self, public_id: int) -> dict | None:
        """
        Retrieves a CmdbRelation from the database

        Args:
            public_id (int): public_id of the CmdbRelation

        Raises:
            RelationsManagerGetError: When a CmdbRelation could not be retrieved

        Returns:
            dict | None: A dictionary representation of the CmdbRelation if successful, otherwise None
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise RelationsManagerGetError(err) from err


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
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            result: IterationResult[CmdbRelation] = IterationResult(aggregation_result, total, CmdbRelation)

            return result
        except BaseManagerIterationError as err:
            raise RelationsManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise RelationsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_relation(self, public_id:int, data: CmdbRelation | dict) -> None:
        """
        Updates a CmdbRelation in the database

        Args:
            public_id (int): public_id of the CmdbRelation which should be updated
            data: CmdbRelation | dict: The new data for the CmdbRelation

        Raises:
            RelationsManagerUpdateError: When the update operation fails
        """
        try:
            if isinstance(data, CmdbRelation):
                data = CmdbRelation.to_json(data)

            self.update({'public_id':public_id}, data)
        except Exception as err:
            LOGGER.error("[update_relation] Exception: %s. Type: %s", err, type(err))
            raise RelationsManagerUpdateError(err) from err

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
        try:
            return self.delete({'public_id':public_id})
        except BaseManagerDeleteError as err:
            raise RelationsManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_added_and_removed_fields(self, old_relation: dict, new_relation: dict) -> dict:
        """
        Compares the 'sections' property of two CmdbRelations to identify fields that have been added or removed

        Args:
        - old_relation (dict): The old CmdbRelation (before changes), which contains the 'sections' field.
        - new_relation (dict): The new CmdbRelation (after changes), which contains the 'sections' field.

        Returns:
        - dict: A dictionary with two keys 'added' and 'removed', each containing a list of field unique identifiers
                that were added or removed, respectively.
        """
        old_fields = set()
        new_fields = set()

        # Extract all field names (unique identifiers) from sections
        for section in old_relation.get("sections", []):
            old_fields.update(section.get("fields", []))

        for section in new_relation.get("sections", []):
            new_fields.update(section.get("fields", []))

        # Compute added and removed fields
        added_fields = new_fields - old_fields
        removed_fields = old_fields - new_fields

        return {
            "added": list(added_fields),
            "removed": list(removed_fields)
        }
