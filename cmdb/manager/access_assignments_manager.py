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
This module contains the implementation of the AccessAssignmentsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.access_model import AccessAssignmentKey, CmdbAccessAssignment

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.access_assignments_manager import (
    ACCESS_ASSIGNMENTS_MANAGER_ERRORS,
    AccessAssignmentsManagerDeleteError,
    AccessAssignmentsManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The order every read of several assignments answers in
BY_PUBLIC_ID: list[tuple[str, int]] = [(CmdbDAO.PUBLIC_ID_KEY, CmdbDAO.DAO_ASCENDING)]

# -------------------------------------------------------------------------------------------------------------------- #
#                                           AccessAssignmentsManager - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessAssignmentsManager(GenericManager):
    """
    The AccessAssignmentsManager manages the assignments of the permission data model in the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the AccessAssignmentsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbAccessAssignment, ACCESS_ASSIGNMENTS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def _find_assignments(self, criteria: dict[str, Any], caller: str,
                          with_mongo_id: bool = False) -> list[dict[str, Any]]:
        """
        Reads the stored assignments matching the criteria, whole, ascending by public_id

        Args:
            criteria (dict[str, Any]): Which assignments
            caller (str): The public method reading, for the log line
            with_mongo_id (bool): Whether ``_id`` is kept - what a ledger's batch undo identifies them by. Defaults
                to False

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored
        """
        try:
            projection: dict[str, int] | None = None if with_mongo_id else {MONGO_ID_FIELD: 0}

            return self.find(criteria=criteria, projection=projection, sort=BY_PUBLIC_ID)
        except BaseManagerGetError as err:
            LOGGER.error("[%s] Exception: %s. Type: %s", caller, err, type(err))
            raise AccessAssignmentsManagerGetError(err) from err


    def all_assignments(self) -> list[dict[str, Any]]:
        """
        Reads every assignment - what a change to the access rules is judged against

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored, ascending by public_id
        """
        return self._find_assignments({}, 'all_assignments')


    def assignments_of_role(self, role_id: int) -> list[dict[str, Any]]:
        """
        Reads the assignments granting a scope role - what keeps the role from being deleted

        Args:
            role_id (int): The CmdbScopeRole's public_id

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored, ascending by public_id
        """
        return self._find_assignments({AccessAssignmentKey.ROLE_ID.value: role_id}, 'assignments_of_role')


    def assignments_of_roles(self, role_ids: list[int]) -> list[dict[str, Any]]:
        """
        Reads the assignments granting any of the given scope roles, in one read

        Args:
            role_ids (list[int]): The roles' public_ids; none reads nothing

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored, ascending by public_id
        """
        if not role_ids:
            return []

        return self._find_assignments({AccessAssignmentKey.ROLE_ID.value: {'$in': list(role_ids)}},
                                      'assignments_of_roles')


    def assignments_of_group(self, group_id: int, with_mongo_id: bool = False) -> list[dict[str, Any]]:
        """
        Reads the assignments granting to a user group - the ones its delete removes

        Args:
            group_id (int): The CmdbUserGroup's public_id
            with_mongo_id (bool): Whether ``_id`` is kept, for a ledger's batch undo. Defaults to False

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored, ascending by public_id - what a ledger records before
                the delete
        """
        return self._find_assignments({AccessAssignmentKey.GROUP_ID.value: group_id}, 'assignments_of_group',
                                      with_mongo_id)

    def assignments_of_groups(self, group_ids: list[int]) -> list[dict[str, Any]]:
        """
        Reads the assignments granting to any of the given user groups - a user's assignments, in one read

        Args:
            group_ids (list[int]): The CmdbUserGroups' public_ids; none reads nothing

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The assignments as stored, ascending by public_id
        """
        if not group_ids:
            return []

        return self._find_assignments({AccessAssignmentKey.GROUP_ID.value: {'$in': list(group_ids)}},
                                      'assignments_of_groups')


    def assigned_role_ids(self) -> list[int]:
        """
        Reads the scope roles some assignment grants - any group's: each restricts its Types for everyone

        Raises:
            AccessAssignmentsManagerGetError: When the read fails

        Returns:
            list[int]: The roles' public_ids, ascending, each once
        """
        try:
            return sorted(self.get_distinct(AccessAssignmentKey.ROLE_ID.value, {}))
        except BaseManagerGetError as err:
            LOGGER.error("[assigned_role_ids] Exception: %s. Type: %s", err, type(err))
            raise AccessAssignmentsManagerGetError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_assignments(self, public_ids: list[int]) -> int:
        """
        Deletes exactly the given assignments, in one write - the ones a caller read and recorded, so a document
        written after the read is never deleted without its record. Re-run safe: a second call deletes nothing;
        an empty selection deletes nothing and writes nothing

        Args:
            public_ids (list[int]): The assignments' public_ids

        Raises:
            AccessAssignmentsManagerDeleteError: When the delete fails

        Returns:
            int: How many assignments were deleted
        """
        if not public_ids:
            return 0

        try:
            return self.delete_many({CmdbDAO.PUBLIC_ID_KEY: {'$in': list(public_ids)}}).deleted_count
        except BaseManagerDeleteError as err:
            LOGGER.error("[delete_assignments] Exception: %s. Type: %s", err, type(err))
            raise AccessAssignmentsManagerDeleteError(err) from err
