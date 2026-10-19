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
The cloud user: who a hosted-cloud request or login belongs to, and the tenant it lands in

Every cloud entry point - the login (`auth_helper.cloud_login`) and an x-api-key or Basic request
(`route_utils.verify_api_access`) - asks the Service Portal through `check_user_in_service_portal`, which answers
from the process-wide user cache when it can (`get_cached_user_manager`) and keeps that cache in step with the portal.
The rest is what a first login of a tenant needs: its database created and brought up to date (`check_db_exists`,
`init_db_routine`), its subscription's admin stored (`set_admin_user`), and the stored user read back
(`retrieve_user`). In local mode (`--cloud --local`) the portal is replaced by a JSON file of test users.

Nothing here imports `route_utils`, which imports this module for `verify_api_access`
"""
import os
import json
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any
import requests
from flask import current_app

from cmdb.database.database_services import CollectionValidator, DatabaseUpdater
from cmdb.manager import (
    UsersManager,
    SecurityManager,
    CachedUserManager,
)

from cmdb.security.auth.login_name import normalize_login_email

from cmdb.models.user_model import CmdbUser, CmdbUserKey

from cmdb.errors.security import (
    InvalidCloudUserError,
    NoAccessTokenError,
    MissingApiKeyError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_cached_user_manager() -> CachedUserManager:
    """
    Builds a CachedUserManager for the process-wide cloud user cache

    **Why this is not `ManagerProvider.get_manager`.** Every other manager is resolved there, and this
    one deliberately is not: the cache does not live in a tenant's database. `CachedUserManager`
    ignores the database argument entirely - its collection is always `DG_CACHE_DB` - so the tenant
    name `ManagerProvider` would pass is discarded, and `get_manager` REQUIRES a request_user in cloud
    mode, which the login path (`check_user_in_service_portal`) cannot supply: nobody is authenticated
    yet. That is why `ManagerType` carries no entry for it

    Called from the login path, the /setup routes and the OpenCelium routes; keeping it in one place
    makes a change to how the cache is reached one edit rather than one per caller

    Returns:
        CachedUserManager: A manager bound to this process' database handle and the cache database
    """
    return CachedUserManager(current_app.database_manager)


def check_user_in_service_portal(
    email: str,
    password: str,
    x_api_key: str | None = None,
    api_key_required: bool = False
) -> dict[str, Any] | None:
    """Check if a user exists in the service portal

    The email is normalised first (stripped and lower-cased), whatever spelling the caller submitted.
    This function verifies user credentials in two modes:
    - **Local mode**: Loads test users from a JSON file and verifies credentials
    - **Cloud mode**: Validates user credentials via the service portal

    Args:
        email (str): The user's email address
        password (str): The user's password
        x_api_key (str | None): API key for authentication. Defaults to None
        api_key_required (bool): When True, the request is rejected unless an ``x_api_key`` is supplied

    Raises:
        NoAccessTokenError: If the service portal authentication fails due to a missing access token
        InvalidCloudUserError: If the user is invalid in the cloud authentication system
        RequestTimeoutError: If the authentication request times out
        RequestError: For general request failures
        MissingApiKeyError: If the portal requires an x-api-key the request did not send

        Any other error - a failed read or write of the user cache, a key the password HMAC cannot be computed without -
        propagates as itself, unwrapped

    Returns:
        dict | None: A dictionary representing the user if authentication is successful, otherwise None. Its
            ``password`` is always the password's HMAC, never the plaintext - in both modes - so a caller that
            stores it (``set_admin_user``) stores a digest the user's password can be verified against
    """
    # Every cloud entry point funnels through here, so the portal and the user cache always see the
    # same spelling of one address - see cmdb.security.auth.login_name
    email = normalize_login_email(email)

    if current_app.local_mode:
        local_user: dict[str, Any] | None = _load_local_test_user(email, password)

        # The fixture holds the plaintext; the answer carries its HMAC, as the portal path's does
        if local_user:
            local_user['password'] = SecurityManager(current_app.database_manager).generate_hmac(local_user['password'])

        return local_user

    # Validation through service portal. Nothing here is caught: every error - a portal refusal, a failed cache
    # read - reaches the caller as itself, so the caller's own except arms decide its answer
    # Early out if no api_key is provided when it is required
    if api_key_required and not x_api_key:
        return None

    cached_user_manager: CachedUserManager = get_cached_user_manager()
    security_manager = SecurityManager(current_app.database_manager)

    user_exists_in_cache = cached_user_manager.cached_user_exists(email)
    # 1. Check cache first
    if user_exists_in_cache:
        cached_user: dict[str, Any] | None = cached_user_manager.get_validated_user_data(
                                                                email,
                                                                security_manager.generate_hmac(password),
                                                                x_api_key,
                                                                api_key_required
                                                            )

        if cached_user:
            return cached_user

    # 2. Not cached or invalid data → validate against portal, then sync the cache
    user_data: dict[str, Any] = validate_subscription_user(email, password, x_api_key, api_key_required)

    if user_data:
        user_data["password"] = security_manager.generate_hmac(user_data["password"])

        if api_key_required and x_api_key:
            _sync_api_cached_user(
                cached_user_manager, security_manager, email, password, x_api_key,
                user_data, user_exists_in_cache
            )
        else:
            _sync_frontend_cached_user(cached_user_manager, email, user_data, user_exists_in_cache)

    return user_data


def _load_local_test_user(email: str, password: str) -> dict[str, Any] | None:
    """
    Validates credentials against the local ``etc/test_users.json`` fixture (local mode only)

    Args:
        email (str): The user's email address (key into the fixture)
        password (str): The user's password to match

    Returns:
        dict[str, Any] | None: The matching test user, or None when unknown / wrong password / on error
    """
    try:
        with open('etc/test_users.json', 'r', encoding='utf-8') as users_file:
            users_data = json.load(users_file)

        user = users_data.get(email)

        if user and user["password"] == password:
            return user

        return None
    except Exception as err:
        LOGGER.debug("[_load_local_test_user] Exception: %s, Type: %s", err, type(err))
        return None


def _sync_api_cached_user(
    cached_user_manager: CachedUserManager,
    security_manager: SecurityManager,
    email: str,
    password: str,
    x_api_key: str,
    user_data: dict[str, Any],
    user_exists_in_cache: bool,
) -> None:
    """
    Syncs the cached user for an external-API (x-api-key) login

    The portal returns a single subscription for an API login. An already-cached user just gets the
    api_key stamped onto the matching subscription; an uncached user is only created when its database
    exists, and then from the FULL subscription list (a second portal call) with the api_key applied.
    The password of a newly cached user is HMAC-hashed before storage so it matches what
    `CachedUserManager.get_validated_user_data` compares against (which hashes the login password) -
    otherwise the cached entry never validates and every request falls back to the portal.

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        security_manager (SecurityManager): Used to HMAC the password before it is cached
        email (str): The user's email
        password (str): The user's (plain) password, for the full-subscription portal call
        x_api_key (str): The API key to associate with the matching subscription
        user_data (dict[str, Any]): The single-subscription user data from the portal
        user_exists_in_cache (bool): Whether the user is already cached
    """
    target_db = user_data['subscriptions'][0]['database']

    if user_exists_in_cache:
        # A cached entry whose password is the current HMAC only lacked this api_key (frontend-first
        # then API case) - just stamp the key. Otherwise the entry is stale (e.g. a plaintext password
        # rather than its HMAC), so drop it and fall through to recreate it correctly.
        if _cached_password_is_current(cached_user_manager, security_manager, email, password):
            cached_user_manager.update_cached_user_api_key(email, target_db, x_api_key)
            return

        cached_user_manager.delete_cached_user(email)

    # Only create if the user's database exists
    if not check_db_exists(target_db):
        return

    # External API returns one subscription, so re-fetch the full subscription list to cache
    full_user_data: dict[str, Any] = validate_subscription_user(email, password)

    if full_user_data:
        # Store the password as its HMAC (the cache validation hashes the login password to compare)
        full_user_data["password"] = security_manager.generate_hmac(full_user_data["password"])

        for sub in full_user_data["subscriptions"]:
            if sub["database"] == target_db:
                sub["api_key"] = x_api_key
                break

        cached_user_manager.insert_cached_user(full_user_data)


def _cached_password_is_current(
    cached_user_manager: CachedUserManager,
    security_manager: SecurityManager,
    email: str,
    password: str,
) -> bool:
    """
    Reports whether the cached user's stored password is the current HMAC of the login password

    Used to distinguish a still-valid cached entry (only missing an api_key) from a stale one that must
    be rewritten - e.g. an entry still holding a plaintext password rather than its HMAC.

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        security_manager (SecurityManager): Used to HMAC the login password for comparison
        email (str): The user's email
        password (str): The (plain) login password to hash and compare

    Returns:
        bool: True if a cached entry exists and its stored password equals the HMAC of the login password
    """
    cached_user = cached_user_manager.get_cached_user(email)

    return bool(cached_user) and cached_user.get("password") == security_manager.generate_hmac(password)


def _sync_frontend_cached_user(
    cached_user_manager: CachedUserManager,
    email: str,
    user_data: dict[str, Any],
    user_exists_in_cache: bool,
) -> None:
    """
    Syncs the cached user for a frontend login (all subscriptions cached)

    A new user is cached as-is; an existing cached user is refreshed with the fresh subscription data,
    restoring any api_key that was previously stored for a given database

    Args:
        cached_user_manager (CachedUserManager): The cached-user store
        email (str): The user's email
        user_data (dict[str, Any]): The full (all-subscriptions) user data from the portal
        user_exists_in_cache (bool): Whether the user is already cached
    """
    if not user_exists_in_cache:
        cached_user_manager.insert_cached_user(user_data)
        return

    cached_user = cached_user_manager.get_cached_user(email)

    if not cached_user:
        return

    # Restore any previously-cached api_key onto the matching fresh subscription
    cached_api_keys: dict[Any, Any] = {
        sub["database"]: sub.get("api_key")
        for sub in cached_user.get("subscriptions", [])
        if sub.get("api_key")
    }

    for sub in user_data["subscriptions"]:
        if sub["database"] in cached_api_keys:
            sub["api_key"] = cached_api_keys[sub["database"]]

    cached_user_manager.update_cached_user(email, user_data)


def check_db_exists(db_name: str) -> bool:
    """
    This function checks if a given database name exists within the current database manager

    Args:
        db_name (str): The name of the database to check

    Returns:
        bool: True if the database exists, False otherwise
    """
    return current_app.database_manager.check_database_exists(db_name)


def init_db_routine(db_name: str) -> None:
    """
    Creates a database with the given name and all corresponding collections

    Args:
        db_name (str): Name of the database
    """
    # Initialise the database
    collection_validator = CollectionValidator(db_name, current_app.database_manager)
    collection_validator.validate_collections()

    # Sets the update version to the newest version
    database_updater = DatabaseUpdater(current_app.database_manager, db_name)
    database_updater.set_update_version(database_updater.get_highest_update_version())


def set_admin_user(user_data: dict[str, Any], subscription: dict[str, Any]) -> None:
    """
    Ensures an admin user exists for a subscription's database (cloud mode)

    Creates the admin user in the subscription's database when it is missing; otherwise updates the
    existing user's database, api_level and config_items_limit from the subscription. A created user stores
    ``user_data['password']`` AS GIVEN: it is already the password's HMAC (``check_user_in_service_portal``
    answers it so), and hashing it again stored a digest no password could ever match. Both numbers
    are converted with int() once, before either branch, so a created and an updated user store the
    same type - a string limit on the user would make every later limit check fail with a TypeError

    Args:
        user_data (dict[str, Any]): The portal user data (email, user_name, and password as its HMAC)
        subscription (dict[str, Any]): The subscription providing database, api_level and config_item_limit

    Raises:
        UsersManagerGetError: If reading the existing user fails
        UsersManagerInsertError: If creating/updating the admin user fails, including a subscription
            whose api_level or config_item_limit is not a number
    """
    users_manager = UsersManager(current_app.database_manager, subscription['database'])

    try:
        api_level: int = int(subscription['api_level'])
        config_items_limit: int = int(subscription['config_item_limit'])
        admin_user_from_db = None

        try:
            admin_user_from_db = users_manager.get_user_by(
                {CmdbUserKey.EMAIL.value: user_data[CmdbUserKey.EMAIL.value]}
            )
        except UsersManagerGetError:
            pass

        if not admin_user_from_db:
            admin_user = CmdbUser(
                public_id = users_manager.get_next_public_id(inc_id=True),
                user_name = user_data['user_name'],
                email = user_data[CmdbUserKey.EMAIL.value],
                database = subscription['database'],
                active = True,
                api_level = api_level,
                config_items_limit = config_items_limit,
                group_id = 1,
                registration_time = datetime.now(timezone.utc),
                password = user_data['password'],
            )

            users_manager.insert_user(admin_user)
        else: # Update the database, api-level and config_items_limit of user
            admin_user_from_db.api_level = api_level
            admin_user_from_db.database = subscription['database']
            admin_user_from_db.config_items_limit = config_items_limit

            users_manager.update_user(admin_user_from_db.get_public_id(), admin_user_from_db)

    except UsersManagerGetError as err:
        raise UsersManagerGetError(err) from err
    except Exception as err:
        LOGGER.debug("[set_admin_user] Exception: %s, Type: %s", err, type(err))
        raise UsersManagerInsertError(err) from err


def retrieve_user(user_data: dict[str, Any], database: str) -> CmdbUser | None:
    """
    Retrieve a user from the database by email

    This function fetches a user from the database using the provided email from the user data

    Args:
        user_data (dict[str, str]): A dictionary containing user information (e.g., email)
        database (str): The name of the database to query

    Returns:
        CmdbUser | None: The matching user if found, or None if it does not exist / an error occurs
    """
    users_manager = UsersManager(current_app.database_manager, database)

    try:
        return users_manager.get_user_by({CmdbUserKey.EMAIL.value: user_data[CmdbUserKey.EMAIL.value]})
    except UsersManagerGetError as err:
        LOGGER.debug("[retrieve_user] Exception: %s, Type: %s", err, type(err))
        return None


def validate_subscription_user(
    email: str,
    password: str,
    x_api_key: str | None = None,
    api_key_required: bool = False
) -> dict[str , Any]:
    """
    Validates user credentials against the DataGerry service portal

    Posts the credentials (and optionally the API key) to the portal's auth endpoint and returns the
    portal's user payload on success. The endpoint switches to ``/datagerry/auth/subscription`` when an
    ``x_api_key`` is supplied

    Args:
        email (str): The user's email address
        password (str): The user's password
        x_api_key (str | None): API key for a subscription-scoped login. Defaults to None
        api_key_required (bool): When True, the request is rejected unless an ``x_api_key`` is supplied

    Raises:
        MissingApiKeyError: If an API key is required but not provided
        NoAccessTokenError: If the ``X-ACCESS-TOKEN`` env var is not set
        RequestError: If no portal URL is configured or the request fails
        RequestTimeoutError: If the portal request times out
        InvalidCloudUserError: If the portal rejects the credentials

    Returns:
        dict[str, Any]: The portal's user payload on successful authentication
    """
    if api_key_required and not x_api_key:
        raise MissingApiKeyError("No API-KEY provided!")

    x_access_token: str | None = os.getenv("X-ACCESS-TOKEN")

    if not x_access_token:
        raise NoAccessTokenError("No x-access-token provided!")

    headers: dict[str, str] = {
        "x-access-token": x_access_token
    }

    base_url: str | None = os.getenv("DG_SP_BASE_URL")
    target: str = f"{base_url}/datagerry/auth"

    payload: dict[str, str] = {
        "email": email,
        "password": password
    }

    if x_api_key:
        payload['x-api-key'] = x_api_key

        target: str = f"{base_url}/datagerry/auth/subscription"

    try:
        response = requests.post(target, headers=headers, json=payload, timeout=3)

        if response.status_code == 200:
            return response.json()

        try:
            err_msg = response.json().get("message", response.text)
        except ValueError:
            err_msg: str = response.text
        raise InvalidCloudUserError(err_msg)
    except requests.exceptions.Timeout as err:
        raise RequestTimeoutError(err) from err
    except requests.exceptions.RequestException as err:
        raise RequestError(err) from err
