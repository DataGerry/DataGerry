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
This module contains the implementation of the UsersManager
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.user_model import CmdbUser
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.users_manager import (
    UsersManagerInitError,
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerDeleteError,
    UsersManagerUpdateError,
    UsersManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 UsersManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class UsersManager(BaseManager):
    """
    The UsersManager handles the interaction between the CmdbUsers-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        Set the database connection for the UsersManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE
        """
        try:
            super().__init__(CmdbUser.COLLECTION, dbm, database)
        except Exception as err:
            raise UsersManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_user(self, user: CmdbUser | dict) -> int:
        """
        Insert a single CmdbUser into the database

        Args:
            user (CmdbUser | dict): Raw data of the CmdbUser

        Raises:
            UsersManagerInsertError: When the CmdbUser could not be inserted in the database

        Returns:
            int: The public_id of the created CmdbUser
        """
        try:
            if isinstance(user, CmdbUser):
                user = CmdbUser.to_json(user)

            return self.insert(user)
        except Exception as err:
            LOGGER.error("[insert_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_user(self, public_id: int) -> CmdbUser | None:
        """
        Retrieve a single CmdbUser by its public_id

        Args:
            public_id (int): public_id of the CmdbUser

        Raises:
            UsersManagerGetError: If CmdbUser could not be retrieved

        Returns:
            CmdbUser | None: The requested CmdbUser if it exist else None
        """
        try:
            requested_user = self.get_one(public_id)

            if not requested_user:
                return None

            return CmdbUser.from_data(requested_user)
        except Exception as err:
            LOGGER.error("[get_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err


    def get_user_by(self, query: dict) -> CmdbUser | None:
        """
        Get a single CmdbUser by a query

        Args:
            query (dict): Query filter of CmdbUser parameters

        Raises:
            UsersManagerGetError: When the CmdbUser could not be retrieved

        Returns:
            CmdbUser | None: CmdbUser matching the query if it exist else None
        """
        try:
            result = self.get(filter=query, limit=1)
            requested_user = result[0] if result else None

            if requested_user is None:
                return None

            return CmdbUser.from_data(requested_user)
        except IndexError: # No user found
            return None
        except Exception as err:
            LOGGER.error("[get_user_by] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err


    def get_many_users(self, query: list = None) -> list[CmdbUser]:
        """
        Get multiple CmdbUsers by a query. Passing no query means all users

        Args:
            query (dict): A database query for filtering

        Raises:
            UsersManagerGetError: Raised when CmdbUsers cant be retrieved or not transformed into CmdbUser

        Returns:
            list[CmdbUser]: A list of all users which matches the query
        """
        query = query or {}

        try:
            results = self.get(filter=query)

            return [CmdbUser.from_data(user) for user in results]
        except Exception as err:
            LOGGER.error("[get_many_users] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbUser]:
        """
        Iterate CmdbUsers

        Args:
            builder_params (BuilderParameters): Filter for iteration

        Raises:
            UsersManagerIterationError: When the iteration failed

        Returns:
            IterationResult: IterationResult with CmdbUsers matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbUser] = IterationResult(aggregation_result, total, CmdbUser)

            return iteration_result
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerIterationError(err) from err


    def get_user_lookup(self, user_ids: list[int]) -> dict[int, CmdbUser]:
        """
        Retrieves a lookup dictionary of CmdbUsers filtered by the provided user_ids

        Args:
            user_ids (list[int]): The public_ids of CmdbUsers which should be retrieved

        Returns:
            dict[int, CmdbUser]: The lookup dictionary with the CmdbUsers
        """
        users: list[dict[str, Any]] = self.find(criteria={"public_id": {"$in": list(user_ids)}})

        user_lookup: dict[int, CmdbUser] = {
            user['public_id']: CmdbUser.from_data(user) for user in users
        }

        return user_lookup

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_user(self, public_id: int, user_data: CmdbUser | dict) -> None:
        """
        Update an existing CmdbUser

        Args:
            public_id (int): public_id of the CmdbUser
            user(CmdbUser | dict): Instance or dict of CmdbUser

        Raises:
            UsersManagerUpdateError: When the CmdbUser could not be updated
        """
        try:
            if isinstance(user_data, CmdbUser):
                user_data = CmdbUser.to_json(user_data)

            self.update(criteria={'public_id': public_id}, data=user_data)
        except Exception as err:
            LOGGER.error("[update_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_user(self, public_id: int) -> bool:
        """
        Delete an existing CmdbUser with the given public_id

        Args:
            public_id (int): PublicID of the user

        Raises:
            UsersManagerDeleteError: When trying to delete the admin CmdbUser with public_id=1 or deletion failed

        Returns:
            bool: True if deletion was successful
        """
        try:
            if public_id == CmdbUser.ADMIN_PUBLIC_ID:
                raise UsersManagerDeleteError("It is not possible to delete the admin user!")

            return self.delete({'public_id': public_id})
        except Exception as err:
            LOGGER.error("[delete_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def handle_users_on_group_delete(
        self,
        group_id: int,
        action: GroupDeleteMode,
        target_group_id: int | None
    ) -> None:
        """
        Redistribute the members of a UserGroup that is about to be deleted

        Depending on ``action``:
          * ``MOVE`` - every user in ``group_id`` is reassigned to ``target_group_id`` in a single
            bulk write (``target_group_id`` must be provided)
          * ``DELETE`` - every user in ``group_id`` is deleted, but the call is refused first if the
            bootstrap admin user is a member (the admin must never be deleted)
        A group with no members is a no-op

        Args:
            group_id (int): public_id of the UserGroup being deleted
            action (GroupDeleteMode): How to handle the group's members (MOVE or DELETE)
            target_group_id (int | None): Destination group for MOVE; ignored for DELETE

        Raises:
            UsersManagerDeleteError: When the admin user is a member on DELETE, or a member delete /
                move failed
            UsersManagerGetError: When the group's members could not be retrieved
        """
        try:
            users_in_group: list[CmdbUser] = self.get_many_users({'group_id': group_id})

            if not users_in_group:
                return

            if action == GroupDeleteMode.MOVE:
                if not target_group_id:
                    raise UsersManagerUpdateError("Target group_id required when moving Users!")

                operations: list[UpdateOne] = [
                    UpdateOne(
                        {"public_id": user.public_id},
                        {"$set": {"group_id": int(target_group_id)}}
                    )
                    for user in users_in_group
                ]

                self.bulk_write(operations)
            elif action == GroupDeleteMode.DELETE:
                # Check if the admin user is part of this UserGroup
                admin_user: dict[str, Any] | None = self.get_one_by({
                    "group_id": group_id,
                    "public_id": CmdbUser.ADMIN_PUBLIC_ID
                })

                if admin_user:
                    raise UsersManagerDeleteError("This Group can not be deleted because the admin user is part of it")

                self.delete_many({"group_id": group_id})
        except UsersManagerDeleteError as err:
            LOGGER.error("[delete_user_group]  UsersManagerDeleteError: %s", err)
            raise UsersManagerDeleteError(str(err)) from err
        except UsersManagerUpdateError as err:
            LOGGER.error("[delete_user_group] UsersManagerUpdateError: %s", err)
            raise UsersManagerDeleteError(str(err)) from err
        except UsersManagerGetError as err:
            LOGGER.error("[delete_user_group] UsersManagerGetError: %s", err)
            raise UsersManagerGetError(str(err)) from err
