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
from cmdb.manager.base_manager import BaseManager

from cmdb.models.right_model.all_rights import flat_rights_tree, ALL_RIGHTS
from cmdb.models.group_model import CmdbUserGroup
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerInsertError,
    BaseManagerIterationError,
)
from cmdb.errors.manager.groups_manager import (
    GroupsManagerInitError,
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerIterationError,
    GroupsManagerUpdateError,
    GroupsManagerDeleteError,
)
from cmdb.errors.models.cmdb_user_group import (
    CmdbUserGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 GroupsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupsManager(BaseManager):
    """
    The GroupsManager handles the interaction between the CmdbUserGroup-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager = None, database :str = None):
        """
        Set the database connection for the GroupsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            GroupsManagerInitError: If the GroupsManager could not be initialised
        """
        try:
            self.rights = flat_rights_tree(ALL_RIGHTS)

            super().__init__(CmdbUserGroup.COLLECTION, dbm, database)
        except Exception as err:
            raise GroupsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_group(self, group: CmdbUserGroup | dict) -> int:
        """
        Insert a single CmdbUserGroup into the database

        Args:
            group (CmdbUserGroup | dict): data of the CmdbUserGroup which should be created

        Raises:
            GroupsManagerInsertError: When the CmdbUserGroup could not be inserted

        Returns:
            int: The public_id of the new inserted CmdbUserGroup
        """
        try:
            if isinstance(group, CmdbUserGroup):
                group = CmdbUserGroup.to_json(group, True)

            return self.insert(group)
        except (CmdbUserGroupToJsonError, BaseManagerInsertError) as err:
            raise GroupsManagerInsertError(err) from err
        except Exception as err:
            LOGGER.error("[insert_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_group(self, public_id: int) -> CmdbUserGroup:
        """
        Get a single CmdbUserGroup by its public_id

        Args:
            public_id (int): public_id of the CmdbUserGroup

        Raises:
            GroupsManagerGetError: When the requested CmdbUserGroup could not be retrieved

        Returns:
            CmdbUserGroup: The requested CmdbUserGroup
        """
        try:
            requested_group = self.get_one(public_id)

            return CmdbUserGroup.from_data(requested_group, self.rights)
        except Exception as err:
            LOGGER.error("[insert_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbUserGroup]:
        """
        Retrieve multiple CmdbUserGroups

        Args:
            builder_params (BuilderParameters): Filter for which CmdbUserGroups should be retrieved

        Raises:
            GroupsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbUserGroup]: All CmdbUserGroups matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbUserGroup] = IterationResult(aggregation_result,
                                                                               total,
                                                                               CmdbUserGroup)

            return iteration_result
        except BaseManagerIterationError as err:
            raise GroupsManagerIterationError(err) from err
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_group(self, public_id: int, group: CmdbUserGroup | dict) -> None:
        """
        Update an existing CmdbUserGroup in the database

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be updated
            group (CmdbUserGroup | dict): New data for the CmdbUserGroup

        Raises:
            GroupsManagerUpdateError: When the update operation failed
        """
        try:
            if isinstance(group, CmdbUserGroup):
                group = CmdbUserGroup.to_json(group)

            self.update({'public_id': public_id}, group)
        except Exception as err:
            LOGGER.error("[update_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_group(self, public_id: int) -> bool:
        """
        Delete an existing CmdbUserGroup by its public_id

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be deleted

        Raises:
            BaseManagerDeleteError: If deleting the Admin or User CmdbUserGroup or delete operation failed

        Returns:
            bool: True if the deletion succeded
        """
        try:
            if public_id in [1, 2]:
                raise GroupsManagerDeleteError(f'Deletion of Group with ID: {public_id} is not allowed!')

            self.delete({'public_id': public_id})
        except BaseManagerDeleteError as err:
            raise GroupsManagerDeleteError(err) from err
