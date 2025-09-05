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
Implementation of CachedUserManager
"""
from logging import Logger, getLogger
from typing import Any

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import DG_CACHE_DB

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cached_user_model.cmdb_cached_user import CmdbCachedUser

from cmdb.errors.manager.cached_user_manager import CACHED_USER_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CachedUserManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CachedUserManager(GenericManager):
    """
    The CachedUserManager manages the interaction between CmdbCachedUsers and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, CmdbCachedUser, CACHED_USER_MANAGER_ERRORS, DG_CACHE_DB)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def set_cached_user(
        self,
        mail: str,
        password: str,
        x_api_key: str | None,
        user_data: dict[str, Any]
    ) -> UpdateResult:
        """
        Insert/update a cached user entry with TTL
        """
        return self.dbm.update(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"mail": mail},
            data=user_data,
            upsert=True
        )

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_cached_user(
            self,
            email: str,
            password: str,
            api_key: str | None,
            api_key_required: bool = False) -> dict[str, Any] | None:
        """
        Retrieve cached user if available (password check included)
        """
        cached_user: dict[str, Any] | None = self.dbm.find_one_by(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            filter={"email": email}
        )

        if cached_user:

            # Check password

            # If api_key if requried return the subscription with the api_key else None
            # if api_key_required:


            return cached_user

        return None

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_cached_user(self, mail: str) -> bool:
        """
        Remove a cached user explicitly (logout)
        """
        result = self.dbm.delete(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"mail": mail}
        )

        return result.deleted_count > 0


    def clear_cache(self) -> int:
        """
        Remove all cached users (admin/debug)
        """
        result = self.dbm.delete_many(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={}
        )

        return result.deleted_count
