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
This module contains the implementation of the ObjectRelationLogsManager
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.log_model import CmdbObjectRelationLog, LogInteraction
from cmdb.models.object_relation_model import ObjectRelationKey, ObjectRelationFieldValueKey
from cmdb.models.user_model import CmdbUser

from cmdb.framework.results import IterationResult

from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerBuildError,
    OBJECT_RELATION_LOGS_MANAGER_ERRORS,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The source CmdbObjectRelation document keys read when building a log come from the model
# (ObjectRelationKey / ObjectRelationFieldValueKey), shared with the routes and the
# ObjectRelationsManager

# Keys of the EDIT 'changes' diff structure produced by get_field_value_changes
CHANGES_MODIFIED_KEY: str = 'modified'
CHANGES_ADDED_KEY: str = 'added'
CHANGES_DELETED_KEY: str = 'deleted'
CHANGE_BEFORE_KEY: str = 'before'
CHANGE_AFTER_KEY: str = 'after'

# -------------------------------------------------------------------------------------------------------------------- #
#                                           ObjectRelationLogsManager - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectRelationLogsManager(GenericManager):
    """
    The ObjectRelationLogsManager handles the interaction between the CmdbObjectRelationLogs-API and the database

    CmdbObjectRelationLogs are append-only audit records: they are created internally (never via a
    public create route) whenever a CmdbObjectRelation is created, edited or deleted, and exposed
    read-only (plus a single delete) through the REST API.

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ObjectRelationLogsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect.
                                   Only used in CLOUD_MODE. Defaults to None

        Raises:
            ObjectRelationLogsManagerInitError: If the ObjectRelationLogsManager could not be initialised
        """
        super().__init__(dbm, CmdbObjectRelationLog, OBJECT_RELATION_LOGS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object_relation_log(self, object_relation_log: dict[str, Any]) -> int:
        """
        Insert a CmdbObjectRelationLog into the database

        Args:
            object_relation_log (dict[str, Any]): Raw data of the CmdbObjectRelationLog

        Raises:
            ObjectRelationLogsManagerInsertError: When a CmdbObjectRelationLog could not be inserted into database

        Returns:
            int: The public_id of the created CmdbObjectRelationLog
        """
        return self.insert_item(object_relation_log)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object_relation_log(self, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a CmdbObjectRelationLog from the database

        Args:
            public_id (int): public_id of the CmdbObjectRelationLog

        Raises:
            ObjectRelationLogsManagerGetError: When a CmdbObjectRelationLog could not be retrieved

        Returns:
            dict[str, Any] | None: Raw data of the CmdbObjectRelationLog if it exists else None
        """
        return self.get_item(public_id, as_dict=True)


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbObjectRelationLog]:
        """
        Retrieves multiple CmdbObjectRelationLogs

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjectRelationLogs should be retrieved

        Raises:
            ObjectRelationLogsManagerIterationError: When the iteration or creating the IterationResult failed

        Returns:
            IterationResult[CmdbObjectRelationLog]: All CmdbObjectRelationLogs matching the filter
        """
        return self.iterate_items(builder_params)

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
        return self.delete_item(public_id)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def build_object_relation_log(
            self,
            action: LogInteraction,
            request_user: CmdbUser,
            old_object_relation: dict[str, Any] | None = None,
            new_object_relation: dict[str, Any] | None = None) -> None:
        """
        Builds a CmdbObjectRelationLog from a CmdbObjectRelation and inserts it into the database

        Args:
            action (LogInteraction): The action being logged (CREATE / EDIT / DELETE)
            request_user (CmdbUser): The CmdbUser who performed the action
            old_object_relation (dict[str, Any] | None): The previous version of the CmdbObjectRelation.
                                                         Defaults to None
            new_object_relation (dict[str, Any] | None): The new version of the CmdbObjectRelation.
                                                         Defaults to None

        Raises:
            ObjectRelationLogsManagerBuildError: If building the log dict failed
            ObjectRelationLogsManagerInsertError: If inserting the built log failed
        """
        object_relation_log = self.format_object_relation_log_data(
            action,
            request_user,
            old_object_relation,
            new_object_relation,
        )

        self.insert_object_relation_log(object_relation_log)


    def format_object_relation_log_data(
            self,
            action: LogInteraction,
            request_user: CmdbUser,
            old_object_relation: dict[str, Any] | None = None,
            new_object_relation: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Builds the CmdbObjectRelationLog document for the given action without persisting it

        The shape of the ``changes`` entry depends on the action:

        - **CREATE**: a flat ``{field_name: value}`` snapshot of the new field values
          (e.g. ``{'a': 1, 'b': 2}``)
        - **EDIT**: a structured diff with ``modified`` / ``added`` / ``deleted`` sub-keys
          (e.g. ``{'modified': {'status': {'before': 'active', 'after': 'inactive'}}, ...}``)
        - **DELETE**: an empty dict (nothing changed, the relation is gone)

        Args:
            action (LogInteraction): The action being logged (CREATE / EDIT / DELETE)
            request_user (CmdbUser): The CmdbUser who performed the action
            old_object_relation (dict[str, Any] | None): The previous version of the CmdbObjectRelation.
                                                         Defaults to None
            new_object_relation (dict[str, Any] | None): The new version of the CmdbObjectRelation.
                                                         Defaults to None

        Raises:
            ObjectRelationLogsManagerBuildError: If neither relation is provided or the build fails

        Returns:
            dict[str, Any]: The CmdbObjectRelationLog document ready to be inserted
        """
        try:
            object_relation = new_object_relation if new_object_relation else old_object_relation

            if object_relation is None:
                raise ValueError("Either old_object_relation or new_object_relation must be provided")

            # Initialise the log document with the attributes common to every action
            object_relation_log: dict[str, Any] = {
                "action": action,
                "creation_time": datetime.now(timezone.utc),
                "author_id": request_user.get_public_id(),
                "author_name": request_user.get_display_name(),
                "object_relation_parent_id": object_relation.get(ObjectRelationKey.RELATION_PARENT_ID.value),
                "object_relation_child_id": object_relation.get(ObjectRelationKey.RELATION_CHILD_ID.value),
                "object_relation_id": object_relation.get(ObjectRelationKey.PUBLIC_ID.value),
                "changes": {},
            }

            if action == LogInteraction.CREATE:
                object_relation_log["changes"] = {
                    item[ObjectRelationFieldValueKey.NAME.value]: item[ObjectRelationFieldValueKey.VALUE.value]
                    for item in new_object_relation.get(ObjectRelationKey.FIELD_VALUES.value, [])
                }
            elif action == LogInteraction.EDIT:
                object_relation_log["changes"] = self.get_field_value_changes(
                    old_object_relation.get(ObjectRelationKey.FIELD_VALUES.value, []),
                    new_object_relation.get(ObjectRelationKey.FIELD_VALUES.value, []),
                )

            return object_relation_log
        except Exception as err:
            raise ObjectRelationLogsManagerBuildError(err) from err


    def get_field_value_changes(self,
                                old_fields: list[dict[str, Any]],
                                new_fields: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Computes the modified / added / deleted diff between two field_values lists

        Args:
            old_fields (list[dict[str, Any]]): The field values before the change (name/value pairs)
            new_fields (list[dict[str, Any]]): The field values after the change (name/value pairs)

        Returns:
            dict[str, Any]: A diff with three sub-dicts:
                - 'modified': ``{name: {'before': old, 'after': new}}`` for values that changed
                - 'added': ``{name: value}`` for names only present in new_fields
                - 'deleted': ``{name: value}`` for names only present in old_fields
        """
        name_key = ObjectRelationFieldValueKey.NAME.value
        value_key = ObjectRelationFieldValueKey.VALUE.value

        # Convert each list of name/value pairs into a {name: value} mapping
        old_dict = {item[name_key]: item[value_key] for item in old_fields}
        new_dict = {item[name_key]: item[value_key] for item in new_fields}

        changes: dict[str, Any] = {
            CHANGES_MODIFIED_KEY: {},
            CHANGES_ADDED_KEY: {},
            CHANGES_DELETED_KEY: {},
        }

        # Values present in both but no longer equal
        for name, old_value in old_dict.items():
            if name in new_dict and old_value != new_dict[name]:
                changes[CHANGES_MODIFIED_KEY][name] = {CHANGE_BEFORE_KEY: old_value, CHANGE_AFTER_KEY: new_dict[name]}

        # Names only present in the new values
        for name, new_value in new_dict.items():
            if name not in old_dict:
                changes[CHANGES_ADDED_KEY][name] = new_value

        # Names only present in the old values
        for name, old_value in old_dict.items():
            if name not in new_dict:
                changes[CHANGES_DELETED_KEY][name] = old_value

        return changes


    def check_related_object_changed(self, old_values: dict[str, Any], new_values: dict[str, Any]) -> bool:
        """
        Checks if the parent or child CmdbObject of the CmdbObjectRelation changed

        Args:
            old_values (dict[str, Any]): old data of the CmdbObjectRelation
            new_values (dict[str, Any]): new data of the CmdbObjectRelation

        Returns:
            bool: True if either relation_parent_id or relation_child_id changed, else False
        """
        parent_id_changed = old_values.get(ObjectRelationKey.RELATION_PARENT_ID.value) != new_values.get(
                                                                  ObjectRelationKey.RELATION_PARENT_ID.value)
        child_id_changed = old_values.get(ObjectRelationKey.RELATION_CHILD_ID.value) != new_values.get(
                                                                 ObjectRelationKey.RELATION_CHILD_ID.value)

        return parent_id_changed or child_id_changed
