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
Helper functions for the CmdbUser REST routes

Keeps the route handlers small and unit-testable by extracting the two blocks that otherwise
inflate their complexity: the ``registration_time`` coercion used on update, and the cloud-mode
preparation used on create.
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort

from cmdb.manager import UsersManager
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager.users_manager import UsersManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TEST_USERS_FILE: str = 'etc/test_users.json'

# Milliseconds per second, used when a BSON ``$date`` arrives as an epoch integer
MILLISECONDS_PER_SECOND: int = 1000


def parse_registration_time(raw: Any) -> Any:
    """
    Coerces a registration_time value into a timezone-aware datetime

    Accepts the two shapes the frontend / BSON round-trip can produce - a ``{'$date': ...}`` wrapper
    (ISO string or epoch-millisecond integer) and a bare ISO string - and returns them as a datetime.
    Any other value (already a datetime, None, or an unexpected shape) is returned unchanged

    Args:
        raw (Any): The incoming registration_time value

    Returns:
        Any: A datetime for the recognised shapes, otherwise the original value
    """
    if isinstance(raw, dict) and '$date' in raw:
        date_val = raw['$date']

        if isinstance(date_val, str):
            return datetime.fromisoformat(date_val.replace('Z', '+00:00'))

        if isinstance(date_val, int):  # epoch milliseconds
            return datetime.fromtimestamp(date_val / MILLISECONDS_PER_SECOND, tz=timezone.utc)

    elif isinstance(raw, str):
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))

    return raw


def apply_registration_time(data: dict[str, Any]) -> None:
    """
    Normalises ``data['registration_time']`` in place, when the key is present

    Args:
        data (dict[str, Any]): The update payload to normalise
    """
    if 'registration_time' in data:
        data['registration_time'] = parse_registration_time(data['registration_time'])


def prepare_cloud_user(
    data: dict[str, Any],
    plaintext_password: str,
    request_user: CmdbUser,
    users_manager: UsersManager,
    cloud_mode: bool,
    local_mode: bool,
) -> None:
    """
    Applies the cloud-mode-only preparation for a new CmdbUser (no-op outside cloud mode)

    In cloud mode this binds the user to the requester's database, enforces that an email is present
    and unique, and - when running the local cloud build - mirrors the user into the test users file.
    Any rule violation aborts the request with HTTP 400

    Args:
        data (dict[str, Any]): The new user's payload (mutated in place)
        plaintext_password (str): The user's password before hashing, stored in the local users file
        request_user (CmdbUser): The user issuing the request (provides the target database)
        users_manager (UsersManager): Manager used for the email-uniqueness lookup
        cloud_mode (bool): Whether the application runs in cloud mode
        local_mode (bool): Whether the application runs in local (cloud build) mode
    """
    if not cloud_mode:
        return

    try:
        # Confirm the database is available from the request
        data['database'] = request_user.database
    except KeyError:
        abort(400, "The database of the user could not be retrieved!")

    # Confirm an email was provided when creating the user
    user_email = data.get('email')

    if not user_email:
        LOGGER.error("[prepare_cloud_user] No email was provided!")
        abort(400, "The email is mandatory to create a new user!")

    # Check if email already exists
    try:
        if users_manager.get_user_by({'email': user_email}):
            abort(400, "The email is already in use!")
    except UsersManagerGetError:
        abort(400, "Failed to retrieve User from database!")

    if local_mode:
        _register_user_in_test_file(user_email, data, plaintext_password)


def _register_user_in_test_file(user_email: str, data: dict[str, Any], plaintext_password: str) -> None:
    """
    Mirrors a newly created user into the local test users file

    Args:
        user_email (str): The email keying the user in the file
        data (dict[str, Any]): The new user's payload
        plaintext_password (str): The user's password before hashing

    Raises:
        HTTPException: Aborts with 400 if a user with this email already exists in the file
    """
    with open(TEST_USERS_FILE, 'r', encoding='utf-8') as users_file:
        users_data = json.load(users_file)

        if user_email in users_data:
            abort(400, "A user with this email already exists!")

    users_data[user_email] = {
        "user_name": data["user_name"],
        "password": plaintext_password,
        "email": data["email"],
        "database": data["database"],
    }

    with open(TEST_USERS_FILE, 'w', encoding='utf-8') as cur_users_file:
        json.dump(users_data, cur_users_file, ensure_ascii=False, indent=4)
