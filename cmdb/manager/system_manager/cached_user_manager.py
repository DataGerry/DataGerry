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
from datetime import datetime, timezone

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

    def insert_cached_user(self, user_data: dict[str, Any])  -> int:
        """
        Insert a CmdbCachedUser entry with TTL
        """
        user_data['creation_time'] = datetime.now(timezone.utc)

        return self.insert_item(user_data)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def cached_user_exists(self, email: str) -> bool:
        """
        Checks if a user with the given email exists

        Returns:
            bool: True if it exists
        """
        cached_user: dict[str, Any] | None = self.dbm.find_one_by(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            filter={"email": email},
            projection={"public_id": 1}
        )

        return cached_user is not None


    def get_cached_user(self, email: str) -> dict[str, Any] | None:
        """
        Retrieve cached user if available (password check included)
        """
        cached_user: dict[str, Any] | None = self.dbm.find_one_by(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            filter={"email": email}
        )

        return cached_user

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_cached_user(
        self,
        email: str,
        user_data: dict[str, Any]
    ) -> UpdateResult:
        """
        Insert/update a cached user entry with TTL
        """
        user_data['creation_time'] = datetime.now(timezone.utc)

        return self.dbm.update(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"email": email},
            data=user_data,
            upsert=True
        )

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

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_subscription(self, email: str, api_key: str | None) -> dict[str, Any] | None:
        """
        Retrieves a subscription with a given API-kEY

        Args:
            api_key (str): _description_

        Returns:
            dict[str, Any]: _description_
        """
        cached_user: dict[str, Any] | None = self.dbm.find_one_by(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            filter={"email": email},
            projection={"subscriptions": 1}
        )

        if not cached_user:
            return None

        return next(
            (sub for sub in cached_user.get("subscriptions", []) if sub.get("api_key") == api_key),
            None
        )


    def set_subscription(self, email: str, api_key: str, db_name: str) -> bool:
        """
        Updates a subscription in the subscription list with the given API-KEY

        Args:
            api_key (str | None): _description_

        Returns:
            bool: _description_
        """
        result = self.dbm.update(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"email": email, "subscriptions.database": db_name},
            data={"subscriptions.$.api_key": api_key}
        )

        return result.modified_count > 0


    def get_validated_user_data(
        self,
        email: str,
        password: str,
        api_key: str | None,
        api_key_required: bool = False
    ) -> dict[str, Any] | None:
        """
        Validates the cached user

        Args:
            user_data (dict[str, Any]): _description_

        Returns:
            dict[str, Any] | None: _description_
        """
        if api_key_required and not api_key:
            return None

        cached_user: dict[str, Any] | None = self.get_cached_user(email)

        if not cached_user:
            return None

        # Check if password matches
        if cached_user.get('password') != password:
            return None

        # If api_key if requried return the subscription with the api_key else None
        if api_key_required:
            # Find single subscription for given api_key
            subscription = next(
                (
                    sub for sub in cached_user["subscriptions"]\
                    if sub.get("api_key") == api_key and sub.get("is_valid", False)
                ),
                None
            )

            if not subscription:
                return None

            cached_user["subscriptions"] = [subscription]

        # Remove all api_keys from subscriptions before returning
        sub: dict[str, Any]
        for sub in cached_user["subscriptions"]:
            sub.pop("api_key", None)

        return cached_user
