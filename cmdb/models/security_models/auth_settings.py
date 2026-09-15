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
Implementation of CmdbAuthSettings, the in-memory form of the stored `auth` settings section

The section decides how every login works: which providers are installed and configured, whether
external (LDAP) authentication is allowed at all, and how long an issued token stays valid. It
reaches this class from two directions and both used to splat a raw dict into the constructor:

* `AuthModule.__init_settings` reads the stored document, and
* `PUT|POST /rest/auth/settings` reads a client payload

`**data` into `__init__` means an unexpected key is a `TypeError` raised while *binding the
signature*, before any of this class's code runs - so the `AuthSettingsInitError` the routes catch to
answer 400 could never be raised, a bad payload answered 500, and one stray key in the stored section
broke every login path. `from_data` is the entry point now: it validates and raises this model's own
error, and `to_json` is what goes back to the database

`to_json` deliberately omits `_id`. `SettingsManager.write` addresses the section by id separately,
and MongoDB refuses a `$set` that would change an immutable `_id`, so carrying it in the payload made
a client-supplied `_id` a 500. Reads never carried it either - `get_section` strips it - so the two
directions now agree
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.security_models.auth_settings_constants import (
    AUTH_SETTINGS_ID,
    DEFAULT_TOKEN_LIFETIME,
    AuthSettingsKey,
    ProviderEntryKey,
)

from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: The keys a client update has to carry in full. `_id` is excluded on purpose: it addresses the
#: settings section rather than living inside it, and `to_json` does not emit it
CONTENT_KEYS: set[str] = {key.value for key in AuthSettingsKey} - {AuthSettingsKey.ID.value}

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CmdbAuthSettings - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #


class CmdbAuthSettings:
    """
    The `auth` settings section: the installed providers and the token policy

    Build one with `from_data`, not by splatting a dict into the constructor - see the module
    docstring for why
    """

    def __init__(
        self,
        _id: str = AUTH_SETTINGS_ID,
        providers: list[dict] | None = None,
        enable_external: bool = False,
        token_lifetime: int = DEFAULT_TOKEN_LIFETIME,
    ) -> None:
        """
        Creates an instance of CmdbAuthSettings

        Args:
            _id (str): Id of the settings section this belongs to. Defaults to AUTH_SETTINGS_ID,
                which is the only value in use
            providers (list[dict] | None): One entry per configured authentication provider, each a
                `ProviderEntryKey` mapping. Defaults to an empty list
            enable_external (bool): Whether external (non-local) providers may authenticate at all.
                Defaults to False
            token_lifetime (int): Validity of an issued token **in minutes**. Defaults to
                DEFAULT_TOKEN_LIFETIME
        """
        self._id: str = _id or AUTH_SETTINGS_ID
        self.providers: list[dict] = providers if providers is not None else []
        self.token_lifetime: int = token_lifetime
        self.enable_external: bool = enable_external

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any], require_complete: bool = False) -> "CmdbAuthSettings":
        """
        Builds a CmdbAuthSettings from a stored document or a request payload

        Validates rather than trusting the input, which is the whole reason this exists: the two
        callers pass a document read from the database and a body posted by a client, and neither was
        checked before.

        `require_complete` selects between the two:

        * **False** (reading a stored section) - missing keys fall back to the defaults, so a
          document written by an older version still loads instead of failing the login path
        * **True** (a client update) - every *content* key must be present. Without it a payload
          omitting `providers` silently blanks the configured LDAP provider, because an absent key
          and "reset to the default" are otherwise indistinguishable. `_id` is NOT required: it is
          the section address, supplied by the route and absent from `to_json`. It is still accepted,
          because the Angular settings form posts it back with the rest of the object

        Args:
            data (dict[str, Any]): The stored document or the request payload
            require_complete (bool): Whether every key must be present. Defaults to False

        Raises:
            AuthSettingsInitError: When `data` is not a dict, carries an unknown key, omits a
                required one, or holds a value of the wrong type

        Returns:
            CmdbAuthSettings: The validated settings
        """
        if not isinstance(data, dict):
            raise AuthSettingsInitError(f"Auth settings must be an object, got {type(data).__name__}")

        known_keys: set[str] = {key.value for key in AuthSettingsKey}
        unknown_keys: set[str] = set(data) - known_keys

        if unknown_keys:
            raise AuthSettingsInitError(f"Unknown auth settings key(s): {sorted(unknown_keys)}")

        if require_complete:
            missing_keys: set[str] = CONTENT_KEYS - set(data)

            if missing_keys:
                raise AuthSettingsInitError(f"Missing auth settings key(s): {sorted(missing_keys)}")

        return cls(
            _id=cls.__validated_id(data.get(AuthSettingsKey.ID.value)),
            providers=cls.__validated_providers(data.get(AuthSettingsKey.PROVIDERS.value)),
            enable_external=cls.__validated_enable_external(data.get(AuthSettingsKey.ENABLE_EXTERNAL.value)),
            token_lifetime=cls.__validated_token_lifetime(data.get(AuthSettingsKey.TOKEN_LIFETIME.value)),
        )


    @staticmethod
    def to_json(instance: "CmdbAuthSettings") -> dict[str, Any]:
        """
        Serialises a CmdbAuthSettings into the document stored for the `auth` section

        `_id` is deliberately absent: `SettingsManager.write` takes it as a separate argument and
        MongoDB refuses a `$set` that would change an immutable `_id`, so including it turned a
        client-supplied id into a failed write

        Args:
            instance (CmdbAuthSettings): The settings to serialise

        Returns:
            dict[str, Any]: The stored shape, without `_id`
        """
        return {
            AuthSettingsKey.PROVIDERS.value: instance.providers,
            AuthSettingsKey.ENABLE_EXTERNAL.value: instance.enable_external,
            AuthSettingsKey.TOKEN_LIFETIME.value: instance.token_lifetime,
        }

# -------------------------------------------------- VALIDATION HELPERS ---------------------------------------------- #

    @staticmethod
    def __validated_id(value: Any) -> str:
        """
        Checks the section id, falling back to the only value in use

        Args:
            value (Any): The `_id` as it arrived, or None when the key was absent

        Raises:
            AuthSettingsInitError: When the value is present but not a string

        Returns:
            str: The section id
        """
        if value is None:
            return AUTH_SETTINGS_ID

        if not isinstance(value, str):
            raise AuthSettingsInitError(f"'{AuthSettingsKey.ID.value}' must be a string")

        return value or AUTH_SETTINGS_ID


    @staticmethod
    def __validated_providers(value: Any) -> list[dict]:
        """
        Checks the provider list

        Only the shape is enforced here - a list of objects. Whether an entry names an installed
        provider and whether its config parses is `AuthModule`'s job, and it already falls back to a
        provider's defaults rather than failing

        Args:
            value (Any): The `providers` list as it arrived, or None when the key was absent

        Raises:
            AuthSettingsInitError: When the value is not a list of objects

        Returns:
            list[dict]: The provider entries
        """
        if value is None:
            return []

        if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
            raise AuthSettingsInitError(f"'{AuthSettingsKey.PROVIDERS.value}' must be a list of objects")

        return value


    @staticmethod
    def __validated_enable_external(value: Any) -> bool:
        """
        Checks the external-authentication flag

        Args:
            value (Any): The flag as it arrived, or None when the key was absent

        Raises:
            AuthSettingsInitError: When the value is present but not a boolean

        Returns:
            bool: Whether external providers may authenticate
        """
        if value is None:
            return False

        if not isinstance(value, bool):
            raise AuthSettingsInitError(f"'{AuthSettingsKey.ENABLE_EXTERNAL.value}' must be a boolean")

        return value


    @staticmethod
    def __validated_token_lifetime(value: Any) -> int:
        """
        Checks the token lifetime, which every issued token depends on

        `TokenGenerator.get_expire_time` does `int(...)` on this and feeds it to
        `timedelta(minutes=...)`. An unvalidated `null` therefore raised `TypeError` on **every**
        login until somebody edited the database by hand, and a zero or negative value issued tokens
        that were already expired

        Args:
            value (Any): The lifetime as it arrived, or None when the key was absent

        Raises:
            AuthSettingsInitError: When the value is not a positive whole number of minutes

        Returns:
            int: The token lifetime in minutes
        """
        if value is None:
            return DEFAULT_TOKEN_LIFETIME

        # bool is a subclass of int, and True would silently become a one-minute lifetime
        if isinstance(value, bool) or not isinstance(value, int):
            raise AuthSettingsInitError(f"'{AuthSettingsKey.TOKEN_LIFETIME.value}' must be a whole number of minutes")

        if value <= 0:
            raise AuthSettingsInitError(f"'{AuthSettingsKey.TOKEN_LIFETIME.value}' must be greater than 0")

        return value

# ------------------------------------------------------- GETTERS ---------------------------------------------------- #

    def get_token_lifetime(self) -> int:
        """
        Returns the validity of an issued token, in minutes

        Returns:
            int: The token_lifetime of this CmdbAuthSettings
        """
        return self.token_lifetime


    def get_provider_list(self) -> list[dict]:
        """
        Returns every configured provider entry

        Returns:
            list[dict]: One `ProviderEntryKey` mapping per configured provider
        """
        return self.providers


    def get_provider_settings(self, class_name: str) -> dict | None:
        """
        Returns the stored configuration of one provider, or None when it has no entry

        Both failure modes used to be exceptions: an unknown provider raised `StopIteration` from a
        bare `next(...)` (the one caller compensated by catching it), and an entry missing
        `class_name` raised `KeyError` - which nothing caught, and which is exactly the malformed
        shape a historical `AuthModule` bug wrote into this list

        Args:
            class_name (str): Name of the provider class whose configuration is wanted

        Returns:
            dict | None: The entry's `config` sub-document, or None when no entry names this provider
        """
        for entry in self.get_provider_list():
            if entry.get(ProviderEntryKey.CLASS_NAME.value) == class_name:
                return entry.get(ProviderEntryKey.CONFIG.value)

        return None
