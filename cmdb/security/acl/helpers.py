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
Access decisions for one CmdbType - may this user perform this permission on objects of the Type (and, with READ,
read its definition)?

**The access engine decides** (``cmdb.framework.access_engine.type_allows``): a Type is restricted while an assigned
scope role names it, and a restricted Type allows a permission only through the user's own assignments (READ is view,
UPDATE edit, CREATE create, DELETE delete). The three functions here differ only in what they are handed - a CmdbType
model, a raw CmdbType document, or nothing to check against at all.

**Conditional assignments** (phase 9): ``type_allowed`` / ``verify_access`` / ``has_type_document_access`` answer the
full grants - a Type held only conditionally is refused (fail closed, the gates of R25). ``type_reachable_for`` /
``has_type_document_reach`` / ``verify_type_reach`` answer "on some objects" (R23: a Type definition, a write before
``can()`` judges the object), and ``verify_object_access`` judges one object (the single-object checks of R25)

``acl_grants_access`` is the **type ACL's own reading**, frozen: the database migrations that run before the access
rules exist read stored ACLs with it, and the equivalence tests compare the engine against it. No access decision
uses it any more
"""
from collections.abc import Collection
from logging import Logger, getLogger
from typing import Any

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.engine_read_errors import as_manager_read_error
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser

from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def acl_grants_access(
        acl: AccessControlList | None,
        group_ids: Collection[int],
        permission: AccessControlPermission) -> bool:
    """
    Decides whether one AccessControlList grants a user's groups a permission

    The single expression of the opt-in rule: an ACL that is absent, or present but not activated,
    grants everything. Only an activated ACL is consulted, and that decision fails closed: it grants when any of
    the groups holds the permission (the union of their entries), and no groups grant nothing - the reading
    ``builder.build_denied_types_criteria`` has for a listing

    Args:
        acl (AccessControlList | None): The ACL of the CmdbType being accessed, or None when it has none
        group_ids (Collection[int]): public_ids of the CmdbUserGroups the requesting user belongs to
        permission (AccessControlPermission): The permission one of the groups must hold

    Returns:
        bool: True when access is granted
    """
    if acl and acl.activated:
        return any(acl.verify_access(int(group_id), permission) for group_id in group_ids)

    return True


@as_manager_read_error
def type_allowed(type_id: Any, user: CmdbUser, permission: AccessControlPermission) -> bool:
    """
    Whether the access engine allows a user a permission on a Type - a Type without an id is refused (fail closed:
    a document read without its ``public_id`` must not pass as an unrestricted one)

    Args:
        type_id (Any): The Type's public_id
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        bool: True when access is granted
    """
    if not isinstance(type_id, int) or isinstance(type_id, bool):
        LOGGER.warning("[type_allowed] A Type without a public_id was judged - refused (%s)", permission.value)
        return False

    # Imported lazily: the engine reads managers, which import this module
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import permission_operations, type_allows

    return type_allows(user, permission_operations(permission), type_id)


def has_access_control(target_type: CmdbType, user: CmdbUser, permission: AccessControlPermission) -> bool:
    """
    Whether a user may perform a permission on the objects of a Type

    Args:
        target_type (CmdbType): The Type
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Returns:
        bool: True when access is granted
    """
    return type_allowed(target_type.public_id, user, permission)


def has_type_document_access(
        type_document: dict[str, Any],
        user: CmdbUser,
        permission: AccessControlPermission) -> bool:
    """
    Checks a raw CmdbType **document** against a user, without building the CmdbType model

    Same decision as ``has_access_control``, for the callers that already hold the type as it came out of Mongo. The
    document must carry its ``public_id`` - one without is refused

    Args:
        type_document (dict[str, Any]): A CmdbType document
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Returns:
        bool: True when access is granted
    """
    return type_allowed(type_document.get(TypeSchemaKey.PUBLIC_ID.value), user, permission)


def verify_access(
    target_type: CmdbType,
    user: CmdbUser | None = None,
    permission: AccessControlPermission | None = None
) -> None:
    """
    Refuses a user a permission on the objects of a Type - nothing is checked without a user or a permission (an
    internal caller)

    Args:
        target_type (CmdbType): The Type
        user (CmdbUser | None): The CmdbUser requesting access
        permission (AccessControlPermission | None): The permission

    Raises:
        AccessDeniedError: When the access is not granted
    """
    if not user or not permission:
        return

    if not has_access_control(target_type, user, permission):
        raise AccessDeniedError('Protected by ACL permission!')


@as_manager_read_error
def type_reachable_for(type_id: Any, user: CmdbUser, permission: AccessControlPermission) -> bool:
    """
    Whether the access engine allows a user a permission on at least some objects of a Type - a conditional assignment
    counts (R23); a Type without an id is refused

    Args:
        type_id (Any): The Type's public_id
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        bool: True when some objects of the Type may be accessed
    """
    if not isinstance(type_id, int) or isinstance(type_id, bool):
        return False

    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import permission_operations, type_reachable

    return type_reachable(user, permission_operations(permission), type_id)


def has_type_document_reach(type_document: dict[str, Any], user: CmdbUser,
                            permission: AccessControlPermission) -> bool:
    """
    ``type_reachable_for`` for a raw CmdbType document - the Type definition read of a user holding it conditionally

    Args:
        type_document (dict[str, Any]): A CmdbType document carrying its ``public_id``
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Returns:
        bool: True when some objects of the Type may be accessed
    """
    return type_reachable_for(type_document.get(TypeSchemaKey.PUBLIC_ID.value), user, permission)


def verify_type_reach(target_type: CmdbType, user: CmdbUser | None = None,
                      permission: AccessControlPermission | None = None) -> None:
    """
    Refuses a permission on a Type the user may not access any object of - the Type-level gate before ``can()``
    judges the object itself; nothing is checked without a user or a permission

    Args:
        target_type (CmdbType): The Type
        user (CmdbUser | None): The CmdbUser requesting access
        permission (AccessControlPermission | None): The permission

    Raises:
        AccessDeniedError: When no object of the Type may be accessed
    """
    if user and permission and not type_reachable_for(target_type.public_id, user, permission):
        raise AccessDeniedError('Protected by ACL permission!')


@as_manager_read_error
def object_access_allowed(document: dict[str, Any], user: CmdbUser, permission: AccessControlPermission) -> bool:
    """
    Whether the access engine allows a user a permission on one stored object - its conditions judged on it

    UPDATE judges the stored object as it stays (an edit's new state is the write's own ``can()``), CREATE the object
    as given

    Args:
        document (dict[str, Any]): The CmdbObject document (``type_id`` and ``fields`` read)
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission

    Raises:
        BaseManagerGetError: When the user's grants or a condition's data could not be read

    Returns:
        bool: True when access is granted
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import ScopeOperation, can, permission_operations

    for operation in permission_operations(permission):
        before: dict[str, Any] | None = None if operation is ScopeOperation.CREATE else document
        after: dict[str, Any] | None = document if operation in (ScopeOperation.CREATE, ScopeOperation.EDIT) else None

        if not can(user, operation, before, after).allowed:
            return False

    return True


def verify_object_access(document: dict[str, Any], user: CmdbUser | None = None,
                         permission: AccessControlPermission | None = None) -> None:
    """
    Refuses a permission on one stored object - nothing is checked without a user or a permission (an internal caller)

    Args:
        document (dict[str, Any]): The CmdbObject document
        user (CmdbUser | None): The CmdbUser requesting access
        permission (AccessControlPermission | None): The permission

    Raises:
        AccessDeniedError: When the access is not granted
    """
    if user and permission and not object_access_allowed(document, user, permission):
        raise AccessDeniedError('Protected by ACL permission!')
