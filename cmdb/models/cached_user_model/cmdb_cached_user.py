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
Represents a cached cloud user in DataGerry
"""
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.cached_user_model.cached_user_constants import CACHE_TTL_SECONDS, CachedUserKey

from cmdb.class_schema.cached_user_model.cmdb_cached_user_schema import get_cmdb_cached_user_schema

from cmdb.errors.models.cmdb_cached_user import (
    CmdbCachedUserInitError,
    CmdbCachedUserInitFromDataError,
    CmdbCachedUserToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbCachedUser - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbCachedUser(CmdbDAO):
    """
    Implementation of CmdbCachedUser, a cached cloud user with their subscriptions

    The entries live in the shared cache database and expire through the ``creation_time`` TTL index
    after CACHE_TTL_SECONDS; nothing in DataGerry deletes them on age. Note that the cache is keyed by
    EMAIL, not by public_id: every read looks a user up by email, and the unique email index is what
    keeps one entry per user

    Extends: CmdbDAO
    """
    COLLECTION = 'cache.users'
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(CachedUserKey.EMAIL.value, CmdbDAO.DAO_ASCENDING)],
            'name': CachedUserKey.EMAIL.value,
            'unique': True,
        },
        # The TTL index: MongoDB removes an entry CACHE_TTL_SECONDS after its creation_time, so nothing
        # in DataGerry has to expire the cache. Every write refreshes creation_time and restarts it
        {
            'keys': [(CachedUserKey.CREATION_TIME.value, CmdbDAO.DAO_ASCENDING)],
            'name': CachedUserKey.CREATION_TIME.value,
            'expireAfterSeconds': CACHE_TTL_SECONDS,
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

        Every argument must be passed as a KEYWORD: CmdbDAO.__new__ looks for public_id in the keyword
        arguments and raises RequiredInitKeyNotFoundError when it is passed positionally

        Args:
            public_id (int): Unique identifier of the cached CmdbUser
            user_name (str): user_name of the cached CmdbUser
            password (str): HMAC of the password of the cached CmdbUser
            email (str): email of the cached CmdbUser, the key the cache is read by
            active (bool): Indicates if the cached CmdbUser is active
            subscriptions (list[dict[str, Any]]): The subscriptions of the cached CmdbUser
            creation_time (datetime | None): When the entry was cached, which is what the TTL index
                measures; None means now

        Raises:
            CmdbCachedUserInitError: When the initialisation of the CmdbCachedUser fails
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

        Every key is mandatory, ACTIVE included - which no current write path stores, so this raises on
        a document written by the live cache. A string CREATION_TIME is parsed, a datetime (what MongoDB
        returns) is taken as it is

        Args:
            data (dict): Data with which the CmdbCachedUser should be initialised

        Raises:
            CmdbCachedUserInitFromDataError: If the initialisation with the given data fails, a missing
                key included

        Returns:
            CmdbCachedUser: CmdbCachedUser with the given data
        """
        try:
            creation_time: Any | None = data[CachedUserKey.CREATION_TIME]

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            return cls(
                public_id = data[CachedUserKey.PUBLIC_ID],
                user_name = data[CachedUserKey.USER_NAME],
                password = data[CachedUserKey.PASSWORD],
                email = data[CachedUserKey.EMAIL],
                active = data[CachedUserKey.ACTIVE],
                subscriptions = data[CachedUserKey.SUBSCRIPTIONS],
                creation_time = creation_time,
            )
        except Exception as err:
            raise CmdbCachedUserInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbDAO") -> dict[str, Any]:
        """
        Converts a CmdbCachedUser into a json compatible dict

        CREATION_TIME stays a datetime: the dict is written to MongoDB, which stores it as a date, and
        the TTL index only works on a real date

        Args:
            instance (CmdbCachedUser): The CmdbCachedUser which should be converted

        Raises:
            CmdbCachedUserToJsonError: If the CmdbCachedUser could not be converted to a json
                compatible dict, a wrongly typed instance included

        Returns:
            dict: Json compatible dict of the CmdbCachedUser values
        """
        try:
            if not isinstance(instance, CmdbCachedUser):
                raise TypeError(f"Expected CmdbCachedUser in 'to_json' got: {type(instance).__name__}!")

            return {
                CachedUserKey.PUBLIC_ID: instance.public_id,
                CachedUserKey.USER_NAME: instance.user_name,
                CachedUserKey.PASSWORD: instance.password,
                CachedUserKey.EMAIL: instance.email,
                CachedUserKey.ACTIVE: instance.active,
                CachedUserKey.SUBSCRIPTIONS: instance.subscriptions,
                CachedUserKey.CREATION_TIME: instance.creation_time,
            }
        except Exception as err:
            raise CmdbCachedUserToJsonError(str(err)) from err
