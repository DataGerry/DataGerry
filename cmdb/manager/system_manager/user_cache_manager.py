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
Implementation of UserCacheManager
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from pymongo import IndexModel
from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               UserCacheManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class UserCacheManager:
    """
    UserCacheManager handles cached user data
    """
    CACHE_TTL = 3600
    COLLECTION = 'cache.users'

    SUPER_INDEX_KEYS: list[dict[str, Any]] = [
        {
            "keys": [("created_at", 1)],
            "name": "expire_after",
            "expireAfterSeconds": CACHE_TTL,
        },
        {
            "keys": [("mail", 1), ("x_api_key", 1)],
            "name": "user_unique",
            "unique": True,
        }
    ]

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        init system settings reader
        Args:
            database_manager: database managers
        """
        self.db_name: str | None = database
        self.dbm: MongoDatabaseManager = dbm

        super().__init__()

# -------------------------------------------------- CLASS - METHOD -------------------------------------------------- #

    @classmethod
    def get_index_keys(cls) -> list[IndexModel]:
        """
        Retrieves a list of index models based on class-defined index keys

        Returns:
            list: A list of IndexModel instances created from `INDEX_KEYS` and `SUPER_INDEX_KEYS`
        """
        return [IndexModel(**index) for index in cls.SUPER_INDEX_KEYS]


# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def set_cached_user(self, mail: str, password: str, x_api_key: str | None, user_data: dict) -> UpdateResult:
        """
        Insert/update a cached user entry with TTL
        """
        doc: dict[str, Any] = {
            "mail": mail,
            "password": password,
            "x_api_key": x_api_key,
            "user_data": user_data,
            "created_at": datetime.now(timezone.utc),
        }

        return self.dbm.update(
            collection=self.COLLECTION,
            db_name=self.db_name,
            criteria={"mail": mail, "x_api_key": x_api_key},
            data=doc,
            upsert=True
        )

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_cached_user(self, mail: str, password: str, x_api_key: str | None) -> dict | None:
        """
        Retrieve cached user if available (password check included)
        """
        user = self.dbm.find_one_by(
            collection=self.COLLECTION,
            db_name=self.db_name,
            filter={"mail": mail, "x_api_key": x_api_key}
        )
        if user and user.get("password") == password:
            return user.get("user_data")
        return None

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_cached_user(self, mail: str, x_api_key: str | None) -> bool:
        """
        Remove a cached user explicitly (logout)
        """
        result = self.dbm.delete(
            collection=self.COLLECTION,
            db_name=self.db_name,
            criteria={"mail": mail, "x_api_key": x_api_key}
        )
        return result.deleted_count > 0


    def clear_cache(self) -> int:
        """
        Remove all cached users (admin/debug)
        """
        result = self.dbm.delete_many(
            collection=self.COLLECTION,
            db_name=self.db_name,
            criteria={}
        )

        return result.deleted_count
