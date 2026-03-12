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

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

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
            if public_id == 1:
                raise UsersManagerDeleteError("You can't delete the admin user!")

            return self.delete({'public_id': public_id})
        except Exception as err:
            LOGGER.error("[delete_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerDeleteError(err) from err
