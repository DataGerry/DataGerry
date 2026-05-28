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
This module contains the implementation of the GroupsManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.right_model.all_rights import flat_rights_tree, ALL_RIGHTS
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.group_model import CmdbUserGroup
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.groups_manager import (
    GROUPS_MANAGER_ERRORS,
    GroupsManagerInitError,
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerDeleteError,
)
from cmdb.errors.models.cmdb_user_group import CmdbUserGroupToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

PROTECTED_GROUP_IDS: tuple[int, int] = (1, 2)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 GroupsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupsManager(GenericManager):
    """
    Manages CmdbUserGroup documents on top of GenericManager

    Keeps the named public API (``insert_group`` / ``get_group`` / ``iterate`` / ``update_group`` /
    ``delete_group``) used by the existing route + bootstrap call sites. Insert overrides
    ``GenericManager.insert_item`` because ``CmdbUserGroup.to_json`` needs ``insert_mode=True`` to
    serialize rights as name strings; get overrides ``GenericManager.get_item`` to feed the cached
    ``self.rights`` to ``CmdbUserGroup.from_data``; delete keeps the admin / user-group guard

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager = None, database: str = None) -> None:
        """
        Set the database connection for the GroupsManager and cache the flat right tree

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the ``dbm`` should connect. Only used in cloud mode

        Raises:
            GroupsManagerInitError: If the manager (or the right-tree cache) could not be initialised
        """
        super().__init__(dbm, CmdbUserGroup, GROUPS_MANAGER_ERRORS, database)

        try:
            self.rights: list[BaseRight] = flat_rights_tree(ALL_RIGHTS)
        except Exception as err:
            raise GroupsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_group(self, group: CmdbUserGroup | dict) -> int:
        """
        Insert a single CmdbUserGroup into the database

        Overrides the generic insert path because ``CmdbUserGroup.to_json`` requires
        ``insert_mode=True`` on insert, which serializes rights as a list of name strings rather
        than as a list of full BaseRight dicts

        Args:
            group (CmdbUserGroup | dict): Raw dict or model instance of the CmdbUserGroup to create

        Raises:
            GroupsManagerInsertError: When the CmdbUserGroup could not be inserted

        Returns:
            int: The public_id of the inserted CmdbUserGroup
        """
        try:
            if isinstance(group, CmdbUserGroup):
                group = CmdbUserGroup.to_json(group, True)

            return self.insert(group)
        except CmdbUserGroupToJsonError as err:
            raise GroupsManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_group(self, public_id: int) -> CmdbUserGroup | None:
        """
        Get a single CmdbUserGroup by its public_id

        Overrides the generic get path because ``CmdbUserGroup.from_data`` needs the cached
        right tree to resolve right names into BaseRight instances

        Args:
            public_id (int): public_id of the CmdbUserGroup

        Raises:
            GroupsManagerGetError: When the requested CmdbUserGroup could not be retrieved

        Returns:
            CmdbUserGroup | None: The requested CmdbUserGroup, or None if no group has that id
        """
        try:
            requested_group = self.get_one(public_id)

            if not requested_group:
                return None

            return CmdbUserGroup.from_data(requested_group, self.rights)
        except Exception as err:
            LOGGER.error("[get_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbUserGroup]:
        """
        Retrieve multiple CmdbUserGroups via the generic iteration pipeline

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination parameters

        Raises:
            GroupsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbUserGroup]: All CmdbUserGroups matching the filter
        """
        return self.iterate_items(builder_params)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_group(self, public_id: int, group: CmdbUserGroup | dict) -> None:
        """
        Update an existing CmdbUserGroup via the generic update path

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be updated
            group (CmdbUserGroup | dict): New data for the CmdbUserGroup

        Raises:
            GroupsManagerUpdateError: When the update operation failed
        """
        self.update_item(public_id, group)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_group(self, public_id: int) -> bool:
        """
        Delete an existing CmdbUserGroup by its public_id

        Refuses to delete the bootstrap admin and user groups (public_ids in
        ``PROTECTED_GROUP_IDS``); for any other id the deletion is delegated to the generic
        delete path

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be deleted

        Raises:
            GroupsManagerDeleteError: When the target id is protected, or the delete operation failed

        Returns:
            bool: True if a document was actually removed, False otherwise
        """
        if public_id in PROTECTED_GROUP_IDS:
            raise GroupsManagerDeleteError(f'Deletion of Group with ID: {public_id} is not allowed!')

        return self.delete_item(public_id)
