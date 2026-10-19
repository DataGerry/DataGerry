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
their complexity: the ``registration_time`` coercion and the field guard used on update, and the
cloud-mode preparation used on create.

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
from datetime import datetime

from flask import abort

from cmdb.utils import coerce_mongo_datetime

from cmdb.manager import UsersManager, GroupsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey
from cmdb.models.group_model import ADMIN_GROUP_ID, CmdbUserGroup
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


def parse_registration_time(raw: Any) -> Any:
    """
    Coerces a registration_time value into a datetime

    Accepts the shapes the frontend / BSON round-trip can produce - a ``{'$date': ...}`` wrapper
    (timestamp string or epoch milliseconds) and a bare timestamp string - through the shared
    ``coerce_mongo_datetime`` caster, so a user's registration_time is read exactly like every other
    date in the API. Any value the caster cannot read (an unexpected shape, None) is returned
    unchanged, which keeps this route's "pass through what you do not understand" behaviour

    Note the bare-string branch is not reachable through the two write routes: ``CmdbUser.SCHEMA``
    types ``registration_time`` as a ``dict``, so a body carrying a plain timestamp string is
    refused with a 400 before the handler runs. It is kept because this helper is also the shape
    other callers would use, and because widening or narrowing that rule is a schema decision

    Args:
        raw (Any): The incoming registration_time value

    Returns:
        Any: A datetime for the recognised shapes, otherwise the original value
    """
    coerced: datetime | None = coerce_mongo_datetime(raw)

    return coerced if coerced is not None else raw


def apply_registration_time(data: dict[str, Any]) -> None:
    """
    Normalises ``data['registration_time']`` in place, when the key is present

    Args:
        data (dict[str, Any]): The update payload to normalise
    """
    if 'registration_time' in data:
        data['registration_time'] = parse_registration_time(data['registration_time'])


def holds_right(request_user: CmdbUser, right: str, groups_manager: GroupsManager) -> bool:
    """
    Answers whether the request user's CmdbUserGroup holds a right, directly or through a broader one

    The same question `APIBlueprint.protect` asks before it falls back to the ``excepted`` carve-out,
    answered from the already-resolved request user: a route that let a user through by the carve-out
    can tell that apart from a user who holds the right. A group that cannot be found holds nothing

    Args:
        request_user (CmdbUser): The user issuing the request
        right (str): The right to check, e.g. ``base.user-management.user.edit``
        groups_manager (GroupsManager): Manager bound to the request user's tenant

    Raises:
        GroupsManagerGetError: When the group cannot be read - the caller fails closed rather than
            guessing either way

    Returns:
        bool: True when the user's group holds the right or an extended right covering it
    """
    group: CmdbUserGroup | None = groups_manager.get_group(request_user.group_id)

    if group is None:
        return False

    return group.has_right(right) or group.has_extended_right(right)


def guard_user_update(stored_user: CmdbUser, data: dict[str, Any], may_administer: bool) -> None:
    """
    Refuses the fields an update may not change, and pins every field it must not reset

    The update route rebuilds the whole user from the body, so a field the body leaves out would fall
    back to its default. Every guarded field is therefore compared with the stored value when the
    body carries it and COPIED from the stored user when it does not. Mutates ``data`` in place:

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
        data (dict[str, Any]): The validated update payload
        may_administer (bool): Whether the request user holds the user edit right

    Raises:
        HTTPException: 400 naming the first field the caller may not change
    """
    stored: dict[str, Any] = CmdbUser.to_json(stored_user)

    for field in sorted(SERVER_OWNED_FIELDS - {CmdbUserKey.PASSWORD}):
        _pin_or_refuse(data, stored, field, SERVER_OWNED_FIELD_REFUSED)

    if data.get(CmdbUserKey.PASSWORD.value) is not None:
        abort(400, PASSWORD_FIELD_REFUSED)

    data[CmdbUserKey.PASSWORD.value] = stored[CmdbUserKey.PASSWORD.value]

    if not may_administer:
        for field in sorted(ADMINISTRATIVE_FIELDS):
            _pin_or_refuse(data, stored, field, ADMINISTRATIVE_FIELD_REFUSED)


def _pin_or_refuse(
        data: dict[str, Any],
        stored: dict[str, Any],
        field: CmdbUserKey,
        refusal: str,
        status: int = HTTPStatus.BAD_REQUEST) -> None:
    """
    Copies a stored field into an absent body key, or refuses a body value that differs from it

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

    if key not in data:
        data[key] = stored[key]
    elif data[key] != stored[key]:
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

    Runs after ``guard_user_update``. A non-administrator caller may not name the administrator group for a user who
    is not in it, and may change none of an administrator's administrative fields: each is pinned to the stored
    value when the body leaves it out and refused (403) when it differs - so the frontend's edit screen, which sends
    the user back unchanged, still passes for an administrator's profile fields

    Args:
        request_user (CmdbUser): The user issuing the request
        stored_user (CmdbUser): The user as currently stored
        data (dict[str, Any]): The validated update payload, mutated in place

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
        _pin_or_refuse(
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
    can remove them; every other write passes without a read. Two administrators demoting each other at the same
    moment can both pass the check - the count is not a lock

    Args:
        users_manager (UsersManager): Manager bound to the request's tenant
        stored_user (CmdbUser): The user as currently stored
        data (dict[str, Any] | None): The validated update payload, or None for a delete

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
