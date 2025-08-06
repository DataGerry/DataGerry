# DataGerry - OpenSource Enterprise CMDB
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
This module contains the implementation of the ObjectRelationLogsManager
"""
import logging
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction
from cmdb.models.user_model import CmdbUser

from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerInitError,
    ObjectRelationLogsManagerBuildError,
    ObjectRelationLogsManagerInsertError,
    ObjectRelationLogsManagerGetError,
    ObjectRelationLogsManagerIterationError,
    ObjectRelationLogsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           ObjectRelationLogsManager - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectRelationLogsManager(BaseManager):
    """
    The ObjectRelationLogsManager handles the interaction between the CmdbObjectRelationLogs-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database:str = None):
        """
        Set the database connection for the ObjectRelationLogsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            ObjectRelationLogsManagerInitError: If the ObjectRelationLogsManager could not be initialised
        """
        try:
            super().__init__(CmdbObjectRelationLog.COLLECTION, dbm, database)
        except Exception as err:
            raise ObjectRelationLogsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object_relation_log(self, object_relation_log: dict) -> int:
        """
        Insert a CmdbObjectRelationLog into the database

        Args:
            object_relation_log (dict): Raw data of the CmdbObjectRelationLog

        Raises:
            ObjectRelationLogsManagerInsertError: When a CmdbObjectRelationLog could not be inserted into database

        Returns:
            int: The public_id of the created CmdbObjectRelationLog
        """
        try:
            return self.insert(object_relation_log)
        except BaseManagerInsertError as err:
            raise ObjectRelationLogsManagerInsertError(err) from err


# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object_relation_log(self, public_id: int) -> dict | None:
        """
        Retrieves a CmdbObjectRelationLog from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelationLog

        Raises:
            ObjectRelationLogsManagerGetError: When a CmdbObjectRelationLog could not be retrieved

        Returns:
            dict | None: Raw data of the CmdbObjectRelationLog if it exists
        """
        try:
            return self.get_one(public_id)
        except BaseManagerGetError as err:
            raise ObjectRelationLogsManagerGetError(err) from err


    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser = None,
                permission: AccessControlPermission = None) -> IterationResult[CmdbObjectRelationLog]:
        """
        Retrieves multiple CmdbObjectRelationLogs

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjectRelationLogs should be retrieved
            user (CmdbUser | None): CmdbUser requestion this operation. Defaults to None
            permission (AccessControlPermission | None): Required permission for the operation. Defaults to None

        Raises:
            ObjectRelationLogsManagerIterationError: When the iteration or creating the IterationResult failed

        Returns:
            IterationResult[CmdbObjectRelationLog]: All CmdbObjectRelationLogs matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbObjectRelationLog] = IterationResult(aggregation_result,
                                                                                       total,
                                                                                       CmdbObjectRelationLog)

            return iteration_result
        except (BaseManagerIterationError, Exception) as err:
            raise ObjectRelationLogsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object_relation_log(self, public_id: int) -> bool:
        """
        Deletes a CmdbObjectRelationLog from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelationLog which should be deleted

        Raises:
            ObjectRelationLogsManagerDeleteError: When the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete({'public_id':public_id})
        except BaseManagerDeleteError as err:
            raise ObjectRelationLogsManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def build_object_relation_log(
            self,
            action: LogInteraction,
            request_user: CmdbUser,
            old_object_relation: dict = None,
            new_object_relation: dict= None) -> None:
        """
        Creates a CmdbObjectRelationLog from a CmdbObjectRelation and inserts it into the database

        Args:
            action (LogInteraction): The action (CREATE / EDIT / DELETE)
            old_object_relation (dict | None): The previous version of the CmdbObjectRelation
            new_object_relation (dict | None): The new version of the CmdbObjectRelation

        Raises:
            ObjectRelationLogsManagerBuildError: If bulding the log dict failed
        """
        try:
            object_relation = new_object_relation if new_object_relation else old_object_relation

            # Initialize log object with common attributes
            object_relation_log = {
                "action": action,
                "creation_time": datetime.now(timezone.utc),
                "author_id": request_user.get_public_id(),
                "author_name": request_user.get_display_name(),
                "object_relation_parent_id": object_relation.get("relation_parent_id"),
                "object_relation_child_id": object_relation.get("relation_child_id"),
                "object_relation_id": object_relation.get("public_id"),
                "changes": {}
            }

            # Handle different actions
            if action == LogInteraction.CREATE:
                # Example changes:
                #
                # {'a': 1, 'b': 2, 'c': 3}
                object_relation_log["changes"] = {
                    item['name']: item['value'] for item in new_object_relation.get("field_values", [])
                }
            elif action == LogInteraction.EDIT:
                # Example changes:
                #
                # {
                #     'modified': {'status': {'before': 'active', 'after': 'inactive'}},
                #     'added': {'assigned_to': 'Bob'},
                #     'deleted': {'owner': 'Alice'}
                # }
                object_relation_log["changes"] = self.get_field_value_changes(
                    old_object_relation.get("field_values", []),
                    new_object_relation.get("field_values", [])
                )

            self.insert(object_relation_log)
        except Exception as err:
            raise ObjectRelationLogsManagerBuildError(err) from err


    def get_field_value_changes(self, old_fields: list[dict], new_fields: list[dict]) -> dict:
        """
        Compare old and new field_values and return changes
        """
        # Convert list of dicts to dictionary {name: value}
        old_dict = {item['name']: item['value'] for item in old_fields}
        new_dict = {item['name']: item['value'] for item in new_fields}

        changes = {
            'modified': {},  # Fields that changed values
            'added': {},     # Newly added fields
            'deleted': {}    # Removed fields
        }

        # Find modified values
        for name in old_dict:
            if name in new_dict and old_dict[name] != new_dict[name]:
                changes['modified'][name] = {'before': old_dict[name], 'after': new_dict[name]}

        # Find added fields
        for name in new_dict:
            if name not in old_dict:
                changes['added'][name] = new_dict[name]

        # Find deleted fields
        for name in old_dict:
            if name not in new_dict:
                changes['deleted'][name] = old_dict[name]

        return changes


    def check_related_object_changed(self, old_values: dict, new_values: dict) -> bool:
        """
        Checks if a parent or child public id changed for the CmdbObjectRelation

        Args:
            old_values (dict): old data of the CmdbObjectRelation
            new_values (dict): new data of the CmdbObjectRelation

        Returns:
            bool: True if either relation_parent_id or relation_child_id changed, else False
        """
        parent_id_changed = old_values.get("relation_parent_id") != new_values.get("relation_parent_id")
        child_id_changed = old_values.get("relation_child_id") != new_values.get("relation_child_id")

        return parent_id_changed or child_id_changed
