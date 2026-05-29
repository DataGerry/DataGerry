# DATAGERRY - OpenSource Enterprise CMDB
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
Represents a cached cloud in DataGerry
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.cached_user_model.cmdb_cached_user_schema import get_cmdb_cached_user_schema

from cmdb.errors.models.cmdb_cached_user import (
    CmdbCachedUserInitError,
    CmdbCachedUserInitFromDataError,
    CmdbCachedUserToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbCachedUser - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbCachedUser(CmdbDAO):
    """
    Implementation of CmdbCachedUser, a cached cloud user with their subscriptions

    Extends: CmdbDAO
    """
    CACHE_TTL: int = 3600 # How long an entry is valid (3600 = 1 hour)

    COLLECTION = 'cache.users'
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('email', CmdbDAO.DAO_ASCENDING)],
            'name': 'email',
            'unique': True
        },
        {
            "keys": [("creation_time", 1)],
            "name": "creation_time",
            "expireAfterSeconds": CACHE_TTL,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_cached_user_schema()

    #pylint: disable=R0917
    def __init__(
        self,
        public_id: int,
        user_name: str,
        password: str,
        email: str,
        active: bool,
        subscriptions: list[dict[str, Any]],
        creation_time: datetime | None
    ) -> None:
        """
        Initializes a CmdbCachedUser

        Args:
            public_id (int): Unique identifier for the CmdbCachedUser
            user_name (str): user_name of the CmdbUser
            password (str): password of the CmdbUser
            email (str): email of the CmdbUser
            active (bool): Indicates if the CmdbUser is active
            subscriptions (list[dict[str, Any]]): The subscriptions of the CmdbUser

        Raises:
            CmdbCachedUserInitError: WHen the initialisation of CmdbUser fails
        """
        try:
            self.user_name: str = user_name
            self.password: str = password
            self.email: str = email
            self.active: bool = active
            self.subscriptions: list[dict[str, Any]] = subscriptions
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbCachedUserInitError(str(err)) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbCachedUser":
        """
        Initialises a CmdbCachedUser from a dict

        Args:
            data (dict): Data with which the CmdbCachedUser should be initialised

        Raises:
            CmdbCachedUserInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbCachedUser: CmdbCachedUser with the given data
        """
        try:
            creation_time: Any | None = data['creation_time']

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            return cls(
                public_id = data['public_id'],
                user_name = data['user_name'],
                password = data['password'],
                email = data['email'],
                active = data['active'],
                subscriptions = data['subscriptions'],
                creation_time = creation_time,
            )
        except Exception as err:
            raise CmdbCachedUserInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbDAO") -> dict[str, Any]:
        """
        Converts a CmdbCachedUser into a json compatible dict

        Args:
            instance (CmdbCachedUser): The CmdbCachedUser which should be converted

        Raises:
            CmdbUserToJsonError: If the CmdbUser could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbCachedUser values
        """
        try:
            if not isinstance(instance, CmdbCachedUser):
                raise TypeError(f"Expected CmdbCachedUser in 'to_json' got: {type(instance).__name__}!")

            return {
                'public_id': instance.public_id,
                'user_name': instance.user_name,
                'password': instance.password,
                'email': instance.email,
                'active': instance.active,
                'subscriptions': instance.subscriptions,
                'creation_time': instance.creation_time,
            }
        except Exception as err:
            raise CmdbCachedUserToJsonError(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def is_cached_user_expired(self) -> bool:
        """
        Checks if the cached user lifetime is expired

        Returns:
            bool: True if the expiration time has been reached, else False
        """
        now: datetime = datetime.now(timezone.utc)
        age_seconds: float = (now - self.creation_time).total_seconds()

        return age_seconds >= self.CACHE_TTL
