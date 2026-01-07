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
Implementation of CachedUserManager
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import DG_CACHE_DB

from cmdb.open_celium import CachedOcIdType

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cached_user_model.cmdb_cached_user import CmdbCachedUser

from cmdb.errors.manager.cached_user_manager import CACHED_USER_MANAGER_ERRORS
from cmdb.errors.open_celium import OcNoSubError, OcMasterPwNotSetError
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
        Inserts a cached user in the  user cache database

        Args:
            user_data (dict[str, Any]): data of the cached user

        Returns:
            int: public_id of the created cached user
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


    def update_cached_user_api_key(
        self,
        email: str,
        subscription_database: str,
        api_key: str
    ) -> UpdateResult:
        """
        Sets the API key for a specific subscription of a cached user.

        Args:
            email (str): The user's email.
            subscription_database (str): Database name of the subscription to update.
            api_key (str): API key to set for this subscription.

        Returns:
            UpdateResult: Result of the MongoDB update operation.
        """
        if not api_key:
            raise ValueError("API key must be provided")
        if not subscription_database:
            raise ValueError("subscription_database must be provided")

        # Retrieve cached user
        cached_user = self.dbm.find_one_by(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            filter={"email": email}
        )

        if not cached_user:
            raise ValueError(f"Cached user for email '{email}' does not exist")

        # Update only the subscription matching subscription_database
        updated = False
        for sub in cached_user['subscriptions']:
            if sub['database'] == subscription_database:
                sub['api_key'] = api_key  # create or overwrite
                updated = True
                break

        if not updated:
            raise ValueError(f"Subscription '{subscription_database}' not found in cached user")

        # Update TTL timestamp
        cached_user['creation_time'] = datetime.now(timezone.utc)

        # Persist back to MongoDB
        return self.dbm.update(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"email": email},
            data=cached_user,
            upsert=False  # do not create a new document
        )
# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_cached_user(self, email: str) -> bool:
        """
        Remove a cached user explicitly (logout)
        """
        result = self.dbm.delete(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            criteria={"email": email}
        )

        return result.deleted_count > 0


    def delete_multiple_cached_users(self, emails: list[str]) -> bool:
        """
        Removes multiple cached users
        """
        result = self.dbm.delete_many(
            collection=CmdbCachedUser.COLLECTION,
            db_name=self.db_name,
            **{"email": {'$in': emails}}
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

        # If api_key if required return the subscription with the api_key else None
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


    def get_sub_by_db_name(self, user_data: dict[str, Any], db_name: str) -> dict[str, Any] | None:
        """
        Returns the subscription where the provided database is used

        Args:
            user_data (dict[str, Any]): a cached user data dict
            db_name (str): name of the database

        Returns:
            dict[str, Any] | None: The target subscription data if found
        """
        return next((sub for sub in user_data["subscriptions"] if sub["database"] == db_name), None)


    def get_master_pw_from_cached(
        self,
        cached_user: dict[str, Any],
        db_name: str
    ) -> str:
        """
        Retrieve the master password from the cached subscription.
        Raises an exception if the subscription or password is missing.
        """
        sub = self.get_sub_by_db_name(cached_user, db_name)
        if not sub:
            raise OcNoSubError(f"No subscription found for database '{db_name}'")

        master_pw = sub.get("masterPassword")
        if not master_pw:
            # clear the users cache immideatly
            self.delete_cached_user(cached_user['email'])
            raise OcMasterPwNotSetError("Master password not set in cached subscription")

        return master_pw


    def check_cached_master_password(
        self,
        cached_user: dict[str, Any],
        db_name: str,
        master_pw: str
    ) -> bool:
        """
        Check whether the provided master password matches the cached one.
        """
        cached_master_pw = self.get_master_pw_from_cached(cached_user, db_name)

        return cached_master_pw == master_pw


    def get_oc_ids(
        self,
        cached_user: dict[str, Any],
        db_name: str,
        id_type: CachedOcIdType
    ) -> list[int] | None:
        """
        Return OpenCelium IDs of the given type for a database from cached user data

        Args:
            cached_user (dict[str, Any]): Cached user data with subscriptions
            db_name (str): Database name to look up
            id_type (CachedOcIdType): Type of OpenCelium IDs to retrieve

        Returns:
            list[int] | None: List of integer IDs, an empty list if none are defined,
            or None if the subscription or OpenCelium data is missing
        """
        target_sub: dict[str, Any] | None = self.get_sub_by_db_name(cached_user, db_name)

        # Find subscription
        target_sub = self.get_sub_by_db_name(cached_user, db_name)
        if not target_sub:
            return None

        oc: dict[str, list[str]] = target_sub.get("opencelium", {})
        if not oc:
            return None

        # Map enum → JSON field name
        key_map: dict[CachedOcIdType, str] = {
            CachedOcIdType.CONNECTORS: "connectors",
            CachedOcIdType.CONNECTIONS: "connections",
            CachedOcIdType.SCHEDULERS: "schedules",
        }

        json_key: str = key_map[id_type]

        # Raw list (strings expected)
        raw_ids: list[str] | None = oc.get(json_key)
        if raw_ids is None:
            return []

        ids:list[int] = []

        for x in raw_ids:
            try:
                ids.append(int(x))
            except (ValueError, TypeError):
                continue  # ignore bad values

        return ids


    def oc_id_exists(
        self,
        cached_user: dict[str, Any],
        db_name: str,
        id_type: CachedOcIdType,
        oc_id: int
    ) -> bool:
        """
        Check whether a specific OpenCelium object ID exists for a given subscription

        Args:
            cached_user (dict[str, Any]): The cached user object containing all
                subscriptions and their OpenCelium data
            db_name (str): The database name used to select the subscription
            id_type (CachedOcIdType): The type of OpenCelium IDs to search within
                (e.g., CONNECTORS, CONNECTIONS, SCHEDULERS)
            oc_id (int): The OpenCelium ID to check for

        Returns:
            bool: True if the given ID exists in the corresponding OpenCelium list,
            otherwise False
        """
        # Reuse get_oc_ids() which already:
        # - finds the subscription
        # - finds the correct OpenCelium list
        # - converts IDs from str to int
        ids: list[int] | None = self.get_oc_ids(cached_user, db_name, id_type)

        if ids is None:
            return False

        return oc_id in ids
