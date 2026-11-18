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
Access Control helper functions

An ACL lives on the **CmdbType**, never on the CmdbObject, so "may this user read this object" is
always "may this user's groups read objects of this object's type". A user in several groups holds the union of
their entries: one group granting the permission is enough. The same READ decision governs the type DEFINITION: a
user none of whose groups a type's ACL grants READ is refused that type on every type route, its export, its import
update and the category tree. Access control is opt-in: an ACL that is absent or switched off permits everything,
and an activated one fails closed.

The one decision is ``acl_grants_access``; the three functions around it differ only in what they are
handed - a CmdbType model, a raw CmdbType document as it comes out of Mongo, or nothing to check
against at all - so a caller never re-implements the "absent or deactivated permits everything" rule
"""
from collections.abc import Collection
from logging import Logger, getLogger
from typing import Any

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
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


def has_access_control(target_type: CmdbType, user: CmdbUser, permission: AccessControlPermission) -> bool:
    """Check if a user has access to object/objects for a given permission"""
    return acl_grants_access(target_type.acl, user.group_ids, permission)


def has_type_document_access(
        type_document: dict[str, Any],
        user: CmdbUser,
        permission: AccessControlPermission) -> bool:
    """
    Checks a raw CmdbType **document** against a user, without building the CmdbType model

    Same decision as ``has_access_control``, for the callers that already hold the type as it came
    out of Mongo - a bulk reader that has loaded every type in scope in one ``$in`` should not pay a
    full ``CmdbType.from_data`` per type just to look at ``acl``

    Args:
        type_document (dict[str, Any]): A CmdbType document; a missing ``acl`` key grants access
        user (CmdbUser): The CmdbUser requesting access
        permission (AccessControlPermission): The permission one of the user's groups must hold

    Returns:
        bool: True when access is granted
    """
    acl_data: Any = type_document.get(TypeSchemaKey.ACL.value) or {AclKey.ACTIVATED.value: False}

    return acl_grants_access(AccessControlList.from_data(acl_data), user.group_ids, permission)


def verify_access(
    target_type: CmdbType,
    user: CmdbUser | None = None,
    permission: AccessControlPermission | None = None
) -> None:
    """
    Validate if a user has access to objects of this type
    """
    if not user or not permission:
        return

    verify: bool = has_access_control(target_type, user, permission)

    if not verify:
        raise AccessDeniedError('Protected by ACL permission!')
