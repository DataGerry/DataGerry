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
Represents a CmdbUser in DataGerry

`CmdbUser` is both the domain object and the storage document: `UsersManager.insert_user` and
`update_user` persist exactly what `to_json` produces. That is why `to_json` carries the stored
password digest and why it must never be handed to a client - the REST routes and the login response
serialise with `to_public_json`, which is the same document minus the digest. Adding a field means
deciding which of the two it belongs in
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.class_schema.user_model.cmdb_user_schema import (
    get_cmdb_user_schema,
    DEFAULT_API_LEVEL,
    DEFAULT_AUTHENTICATOR,
    DEFAULT_CONFIG_ITEMS_LIMIT,
    DEFAULT_DATABASE,
    DEFAULT_GROUP,
)
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey

from cmdb.errors.models.cmdb_user import (
    CmdbUserInitError,
    CmdbUserInitFromDataError,
    CmdbUserToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CmdbUser - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #


class CmdbUser(CmdbDAO):
    """
    Implementation of a CmdbUser in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = 'management.users'
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [('user_name', CmdbDAO.DAO_ASCENDING)],
            'name': 'user_name',
            'unique': True
        }
    ]

    # The field defaults are defined once, next to the schema that also declares them - the model and
    # the validation schema must agree on what an omitted field means
    DEFAULT_AUTHENTICATOR: str = DEFAULT_AUTHENTICATOR
    DEFAULT_GROUP: int = DEFAULT_GROUP
    DEFAULT_API_LEVEL: int = DEFAULT_API_LEVEL
    DEFAULT_CONFIG_ITEMS_LIMIT: int = DEFAULT_CONFIG_ITEMS_LIMIT
    DEFAULT_DATABASE: str = DEFAULT_DATABASE

    # public_id of the bootstrap admin user seeded by conftest / installer; protected from deletion
    ADMIN_PUBLIC_ID: int = 1

    SCHEMA: dict[str, Any] = get_cmdb_user_schema()

    # pylint: disable=R0913, R0914, R0917
    def __init__(
        self,
        public_id: int,
        user_name: str,
        active: bool,
        group_id: int | None = None,
        registration_time: datetime | None = None,
        password: str | None = None,
        database: str = DEFAULT_DATABASE,
        api_level: int = DEFAULT_API_LEVEL,
        config_items_limit: int = DEFAULT_CONFIG_ITEMS_LIMIT,
        image: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        authenticator: str | None = None
    ) -> None:
        """
        Initializes a CmdbUser

        Args:
            public_id (int): Unique identifier for the CmdbUser
            user_name (str): Username of the CmdbUser
            active (bool): Indicates if the CmdbUser is active
            group_id (int, optional): public_id of the CmdbUser's CmdbUserGroup. Defaults to None
            registration_time (datetime, optional): When the CmdbUser was created. Defaults to now
            password (str, optional): The CmdbUser's password DIGEST (see the module docstring)
            database (str, optional): Name of the database the user belongs to. Defaults to
                DEFAULT_DATABASE
            api_level (int, optional): API access level of the CmdbUser. Defaults to DEFAULT_API_LEVEL
            config_items_limit (int, optional): Limit of configuration items. Defaults to
                DEFAULT_CONFIG_ITEMS_LIMIT
            image (str, optional): URL or path to the CmdbUser's profile image. Defaults to None
            first_name (str, optional): First name of the CmdbUser. Defaults to None
            last_name (str, optional): Last name of the CmdbUser. Defaults to None
            email (str, optional): Email address of the CmdbUser. Defaults to None
            authenticator (str, optional): Authentication method for the CmdbUser. Defaults to a default authenticator

        Two arguments are normalised rather than stored verbatim, both deliberately:

        * a falsy `group_id` or `authenticator` falls back to its default, so a document that omits
          the field and one that carries None behave the same
        * an empty `first_name` / `last_name` is stored as None, so `get_display_name` does not have
          to distinguish '' from a missing name

        Raises:
            CmdbUserInitError: When the initialisation of CmdbUser fails
        """
        try:
            self.user_name: str = user_name
            self.active: bool = active
            self.group_id: int = group_id or CmdbUser.DEFAULT_GROUP
            self.authenticator: str = authenticator or CmdbUser.DEFAULT_AUTHENTICATOR
            self.registration_time: datetime = registration_time or datetime.now(timezone.utc)
            self.database: str = database
            self.api_level: int = api_level
            self.config_items_limit: int = config_items_limit
            self.email: str | None = email
            self.password: str | None = password
            self.image: str | None = image
            self.first_name: str | None = first_name or None
            self.last_name: str | None = last_name or None

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbUserInitError(str(err)) from err


    def __str__(self) -> str:
        """
        Returns a string representation of the CmdbUser

        The output includes key attributes such as public_id, email, user_name, group_id,
        authenticator and database - never the password digest

        Returns:
            str: A formatted string representing the CmdbUser
        """
        return (
            f"User(\n"
            f"public_id: {self.public_id},\n"
            f"email: {self.email},\n"
            f"user_name: {self.user_name},\n"
            f"group_id: {self.group_id},\n"
            f"authenticator: {self.authenticator},\n"
            f"database: {self.database}\n"
            f")"
        )

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbUser":
        """
        Initialises a CmdbUser from a dict

        Args:
            data (dict): Data with which the CmdbUser should be initialised

        Raises:
            CmdbUserInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbUser: CmdbUser with the given data
        """
        try:
            reg_date = data.get(CmdbUserKey.REGISTRATION_TIME.value)

            if reg_date and isinstance(reg_date, str):
                reg_date = parse(reg_date, fuzzy=True)

            return cls(
                public_id=data[CmdbUserKey.PUBLIC_ID.value],
                user_name=data[CmdbUserKey.USER_NAME.value],
                active=data[CmdbUserKey.ACTIVE.value],
                database=data.get(CmdbUserKey.DATABASE.value, DEFAULT_DATABASE),
                api_level=data.get(CmdbUserKey.API_LEVEL.value, DEFAULT_API_LEVEL),
                config_items_limit=data.get(CmdbUserKey.CONFIG_ITEMS_LIMIT.value, DEFAULT_CONFIG_ITEMS_LIMIT),
                group_id=data.get(CmdbUserKey.GROUP_ID.value),
                registration_time=reg_date,
                authenticator=data.get(CmdbUserKey.AUTHENTICATOR.value),
                email=data.get(CmdbUserKey.EMAIL.value),
                password=data.get(CmdbUserKey.PASSWORD.value),
                image=data.get(CmdbUserKey.IMAGE.value),
                first_name=data.get(CmdbUserKey.FIRST_NAME.value),
                last_name=data.get(CmdbUserKey.LAST_NAME.value)
            )
        except Exception as err:
            raise CmdbUserInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbDAO") -> dict[str, Any]:
        """
        Converts a CmdbUser into a json compatible dict

        Args:
            instance (CmdbUser): The CmdbUser which should be converted

        This is the STORAGE representation: `UsersManager.insert_user` and `update_user` persist
        exactly this dict, which is why it carries `password`. Never return it to a client - use
        `to_public_json` for that

        Raises:
            CmdbUserToJsonError: If the CmdbUser could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbUser values, including the password digest
        """
        try:
            if not isinstance(instance, CmdbUser):
                raise TypeError(f"Expected CmdbUser in 'to_json' got: {type(instance).__name__}!")

            return {
                CmdbUserKey.PUBLIC_ID.value: instance.public_id,
                CmdbUserKey.USER_NAME.value: instance.user_name,
                CmdbUserKey.ACTIVE.value: instance.active,
                CmdbUserKey.GROUP_ID.value: instance.group_id,
                CmdbUserKey.REGISTRATION_TIME.value: instance.registration_time,
                CmdbUserKey.AUTHENTICATOR.value: instance.authenticator,
                CmdbUserKey.DATABASE.value: instance.database,
                CmdbUserKey.API_LEVEL.value: instance.api_level,
                CmdbUserKey.CONFIG_ITEMS_LIMIT.value: instance.config_items_limit,
                CmdbUserKey.EMAIL.value: instance.email,
                CmdbUserKey.PASSWORD.value: instance.password,
                CmdbUserKey.IMAGE.value: instance.image,
                CmdbUserKey.FIRST_NAME.value: instance.first_name,
                CmdbUserKey.LAST_NAME.value: instance.last_name
            }
        except Exception as err:
            raise CmdbUserToJsonError(str(err)) from err

    @classmethod
    def to_public_json(cls, instance: "CmdbDAO") -> dict[str, Any]:
        """
        Converts a CmdbUser into a json compatible dict that is safe to send to a client

        The same document `to_json` produces, minus the stored password digest. The digest is keyed by
        the instance's AES key so it is not directly reversible, but it is computed with one
        application-wide salt and no per-user salt - identical passwords therefore produce identical
        digests, and a list of them tells a reader which accounts share a password. Every REST route
        and the login response serialise through here for that reason

        Args:
            instance (CmdbUser): The CmdbUser which should be converted

        Raises:
            CmdbUserToJsonError: If the CmdbUser could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbUser values without the password digest
        """
        user_data: dict[str, Any] = cls.to_json(instance)
        user_data.pop(CmdbUserKey.PASSWORD.value, None)

        return user_data

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_database(self) -> str:
        """
        Retrieves the database name of the CmdbUser

        Returns:
            str: Name of the database
        """
        return self.database


    def get_display_name(self) -> str:
        """
        Get the display name of the CmdbUser

        The full name is only used when BOTH parts are set - a CmdbUser carrying just a first name is
        displayed by its user_name, because 'Ann' alone reads as a login rather than a person

        Returns:
            str: '<first_name> <last_name>' when both are set, otherwise the user_name
        """
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'

        return self.user_name


    def is_config_item_limit_reached(self, objects_count: int) -> bool:
        """
        Checks if the configuration item limit for the user has been reached

        Two behaviours here are deliberate as far as the current callers are concerned, and both are
        recorded as discussion-backlog #164: a falsy limit - which includes an explicit 0 - is treated
        as 'unset' and REPLACED with the default, and that replacement is written back onto the
        instance, so this predicate mutates the CmdbUser it is asked about

        Args:
            objects_count (int): Amount of current CmdbObjects

        Returns:
            bool: True if the user has reached or exceeded their config item limit, False otherwise
        """
        if not self.config_items_limit:
            self.config_items_limit = DEFAULT_CONFIG_ITEMS_LIMIT

        return objects_count >= self.config_items_limit
