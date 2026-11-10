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

Keeps the route handlers small and unit-testable by extracting the blocks that otherwise inflate
their complexity: the completion and the field guard used on update, and the cloud-mode preparation used on create.

**An update keeps what its body leaves out.** The update schema has no defaults and no required keys, so the body
carries only what the client sent; ``complete_user_update`` fills every other key from the stored user before any
guard reads the body - the guards then judge a whole user, and an omitted key is never a change.

**The administrator group is administered by administrators only.** ``base.user-management.user.add`` / ``.edit`` /
``.delete`` let a caller manage users, not become one: only a member of the administrator group (``ADMIN_GROUP_ID``,
which holds ``base.*``) may assign that group, change an administrator's administrative fields or password, or delete
an administrator - anyone else is refused with **403** (``guard_administrator_create`` / ``_update`` /
``abort_unless_administrator``). And the group never loses its last active member (``guard_last_administrator``,
**400**): nobody could administrate DataGerry any more.
"""
import json
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.utils import keep_omitted_keys

from cmdb.manager import UsersManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    ADMINISTRATIVE_FIELDS,
    SERVER_OWNED_FIELDS,
    ADMINISTRATIVE_FIELD_REFUSED,
    ADMINISTRATOR_ONLY_REFUSED,
    ASSIGN_ADMIN_GROUP_ACTION,
    CHANGE_ADMINISTRATOR_ACTION,
    LAST_ADMINISTRATOR_DEACTIVATED,
    LAST_ADMINISTRATOR_DELETED,
    LAST_ADMINISTRATOR_DEMOTED,
    LAST_ADMINISTRATOR_REFUSED,
    SERVER_OWNED_FIELD_REFUSED,
    PASSWORD_FIELD_REFUSED,
)

from cmdb.errors.manager.users_manager import UsersManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TEST_USERS_FILE: str = 'etc/test_users.json'


def complete_user_update(data: dict[str, Any], stored_user: CmdbUser) -> dict[str, Any]:
    """
    The update body completed from the stored user: every key it leaves out keeps the stored value

    Runs before every guard, so each judges a whole user and an omitted key is never a change. The password is the
    one key not taken: ``guard_user_update`` refuses a body carrying one and keeps the stored digest itself. The
    ``registration_time`` and the ``public_id`` never reach the body (the update schema drops them), so both are the
    stored ones

    Args:
        data (dict[str, Any]): The validated update body (never mutated)
        stored_user (CmdbUser): The user as currently stored

    Returns:
        dict[str, Any]: A new dict - the body, every left-out key filled from the stored user
    """
    return keep_omitted_keys(data, CmdbUser.to_json(stored_user), excluded={CmdbUserKey.PASSWORD.value})


def guard_user_update(stored_user: CmdbUser, data: dict[str, Any], may_administer: bool) -> None:
    """
    Refuses the fields an update may not change, and keeps the stored password digest

    Runs on the body ``complete_user_update`` completed, so every field is present and a guarded field is compared
    with the stored value; ``data`` is mutated only to put the stored digest back:

    * **server-owned** (`SERVER_OWNED_FIELDS`) - nobody changes them here. `database` and
      `config_items_limit` must equal the stored value (400 otherwise); a `password` is refused when
      the body carries one at all, and the stored digest is kept when it does not - the read never
      returns the digest, so a client sending the user back cannot include it
    * **administrative** (`ADMINISTRATIVE_FIELDS`) - only when `may_administer` is False, i.e. the
      user reached the route through the self-edit carve-out: each must equal the stored value
      (400 otherwise). A holder of the edit right may change them freely

    A body that sends a user back unchanged - what the frontend's profile and edit screens do - passes

    Args:
        stored_user (CmdbUser): The user as currently stored
        data (dict[str, Any]): The completed update payload, mutated in place (the password)
        may_administer (bool): Whether the request user holds the user edit right

    Raises:
        HTTPException: 400 naming the first field the caller may not change
    """
    stored: dict[str, Any] = CmdbUser.to_json(stored_user)

    for field in sorted(SERVER_OWNED_FIELDS - {CmdbUserKey.PASSWORD}):
        _refuse_change(data, stored, field, SERVER_OWNED_FIELD_REFUSED)

    if data.get(CmdbUserKey.PASSWORD.value) is not None:
        abort(400, PASSWORD_FIELD_REFUSED)

    data[CmdbUserKey.PASSWORD.value] = stored[CmdbUserKey.PASSWORD.value]

    if not may_administer:
        for field in sorted(ADMINISTRATIVE_FIELDS):
            _refuse_change(data, stored, field, ADMINISTRATIVE_FIELD_REFUSED)


def _refuse_change(
        data: dict[str, Any],
        stored: dict[str, Any],
        field: CmdbUserKey,
        refusal: str,
        status: int = HTTPStatus.BAD_REQUEST) -> None:
    """
    Refuses a body value that differs from the stored one; a key the body does not carry is no change

    The route completes the body from the stored user first (``complete_user_update``), so on the update path every
    key is present - the absent case only keeps a partial body, such as a direct caller's, from being read as a change

    Args:
        data (dict[str, Any]): The update payload, mutated in place
        stored (dict[str, Any]): The stored user's document
        field (CmdbUserKey): The field to check
        refusal (str): The message, formatted with the field name
        status (int): The refusal's status. Defaults to 400

    Raises:
        HTTPException: ``status`` when the body carries a value other than the stored one
    """
    key: str = field.value

    if key in data and data[key] != stored[key]:
        abort(status, refusal.format(field=key))


def is_administrator(user: CmdbUser) -> bool:
    """
    Whether a CmdbUser is a member of the administrator group

    Args:
        user (CmdbUser): The user to judge

    Returns:
        bool: True for a member of ``ADMIN_GROUP_ID``
    """
    return user.group_id == ADMIN_GROUP_ID


def abort_unless_administrator(request_user: CmdbUser, action: str) -> None:
    """
    Refuses a caller outside the administrator group

    Args:
        request_user (CmdbUser): The user issuing the request
        action (str): What the caller tried, as the refusal names it

    Raises:
        HTTPException: 403 when the caller is no administrator
    """
    if not is_administrator(request_user):
        abort(HTTPStatus.FORBIDDEN, ADMINISTRATOR_ONLY_REFUSED.format(action=action))


def guard_administrator_create(request_user: CmdbUser, data: dict[str, Any]) -> None:
    """
    Refuses a non-administrator creating a user in the administrator group

    Args:
        request_user (CmdbUser): The user issuing the request
        data (dict[str, Any]): The validated create payload

    Raises:
        HTTPException: 403 when a non-administrator names the administrator group
    """
    if data.get(CmdbUserKey.GROUP_ID.value) == ADMIN_GROUP_ID:
        abort_unless_administrator(request_user, ASSIGN_ADMIN_GROUP_ACTION)


def guard_administrator_update(request_user: CmdbUser, stored_user: CmdbUser, data: dict[str, Any]) -> None:
    """
    Refuses a non-administrator moving a user into the administrator group, or changing an administrator

    Runs after ``guard_user_update``, on the completed body. A non-administrator caller may not name the administrator
    group for a user who is not in it, and may change none of an administrator's administrative fields: each is
    refused (403) when it differs from the stored value - so the frontend's edit screen, which sends the user back
    unchanged, and a body that leaves them out both pass for an administrator's profile fields

    Args:
        request_user (CmdbUser): The user issuing the request
        stored_user (CmdbUser): The user as currently stored
        data (dict[str, Any]): The completed update payload

    Raises:
        HTTPException: 403 when a non-administrator assigns the administrator group or changes an administrator
    """
    if is_administrator(request_user):
        return

    if not is_administrator(stored_user):
        if data.get(CmdbUserKey.GROUP_ID.value) == ADMIN_GROUP_ID:
            abort_unless_administrator(request_user, ASSIGN_ADMIN_GROUP_ACTION)

        return

    stored: dict[str, Any] = CmdbUser.to_json(stored_user)

    for field in sorted(ADMINISTRATIVE_FIELDS):
        _refuse_change(
            data, stored, field,
            ADMINISTRATOR_ONLY_REFUSED.format(action=CHANGE_ADMINISTRATOR_ACTION), HTTPStatus.FORBIDDEN,
        )


def guard_last_administrator(
        users_manager: UsersManager,
        stored_user: CmdbUser,
        data: dict[str, Any] | None) -> None:
    """
    Refuses a write that would leave the administrator group without an active member

    Only an active administrator can be the last one, and only a demotion, a deactivation or a delete (``data`` None)
    can remove them; every other write passes without a read. ``data`` must be the completed body
    (``complete_user_update``): a ``group_id`` the body left out would read as a demotion. Two administrators demoting
    each other at the same moment can both pass the check - the count is not a lock

    Args:
        users_manager (UsersManager): Manager bound to the request's tenant
        stored_user (CmdbUser): The user as currently stored
        data (dict[str, Any] | None): The completed update payload, or None for a delete

    Raises:
        HTTPException: 400 when the user is the last active administrator
        UsersManagerGetError: When the other administrators could not be counted
    """
    if not is_administrator(stored_user) or not stored_user.active:
        return

    if data is None:
        change: str = LAST_ADMINISTRATOR_DELETED
    elif data.get(CmdbUserKey.GROUP_ID.value) != ADMIN_GROUP_ID:
        change = LAST_ADMINISTRATOR_DEMOTED
    elif data.get(CmdbUserKey.ACTIVE.value) is False:
        change = LAST_ADMINISTRATOR_DEACTIVATED
    else:
        return

    if not users_manager.has_other_active_member(ADMIN_GROUP_ID, stored_user.public_id):
        abort(HTTPStatus.BAD_REQUEST, LAST_ADMINISTRATOR_REFUSED.format(public_id=stored_user.public_id, change=change))


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
