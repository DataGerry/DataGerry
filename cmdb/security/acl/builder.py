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
Access-control filtering for CmdbObject queries and CmdbType listings

**The access engine decides** (``cmdb.framework.access_engine``): a Type is restricted while an assigned scope role
names it, and a restricted Type is read only through the user's own assignments. The user-facing functions here -
``resolve_denied_type_ids``, ``build_scope_criteria``, ``build_acl_pipeline``, ``build_permitted_types_criteria`` - keep
their names and shapes
for their many callers and delegate to it; each asks in type ACL permissions, read as scope operations
(``permission_operations``: READ is view, UPDATE edit).

``build_denied_types_criteria`` and ``normalize_permissions`` are the **type ACL's own reading**, frozen: the database
migrations that run before the access rules exist read stored ACLs with them, and the equivalence tests compare the
engine against them. No access decision uses them any more
"""
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.engine_read_errors import as_manager_read_error
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder

if TYPE_CHECKING:
    # Imported for type checking only; importing the model at runtime would pull the manager package
    # back into this module and close an import cycle
    from cmdb.models.user_model import CmdbUser
    from cmdb.framework.access_engine import DeniedTypes
# -------------------------------------------------------------------------------------------------------------------- #


def build_group_permissions_path(group_id: int) -> str:
    """
    Builds the dotted path to one group's permission list inside a stored CmdbType's ACL

    Args:
        group_id (int): public_id of the CmdbUserGroup

    Returns:
        str: The path, e.g. `acl.groups.includes.1`
    """
    return (
        f'{TypeSchemaKey.ACL.value}'
        f'.{AclKey.GROUPS.value}'
        f'.{AclKey.INCLUDES.value}'
        f'.{group_id}'
    )


def normalize_permissions(
        permission: AccessControlPermission | list[AccessControlPermission]) -> list[AccessControlPermission]:
    """
    Accepts one permission or several and answers the list form, de-duplicated in the given order

    The single-permission form is the special case of the list form, so every caller of the rule can
    pass either and only this function has to know the difference

    Args:
        permission (AccessControlPermission | list[AccessControlPermission]): One permission, or the
            permissions that must **all** be held

    Raises:
        ValueError: When the list is empty. An empty `$all` matches no document at all, so an empty
            permission list would deny every ACL-carrying type rather than restrict nothing - a
            silently wrong answer, not a harmless one

    Returns:
        list[AccessControlPermission]: The permissions, in order, without repeats
    """
    permissions = [permission] if isinstance(permission, AccessControlPermission) else list(permission)

    if not permissions:
        raise ValueError('At least one AccessControlPermission is required to build an ACL criteria!')

    return list(dict.fromkeys(permissions))


def build_denied_types_criteria(
        group_ids: Collection[int],
        permission: AccessControlPermission | list[AccessControlPermission]) -> dict[str, Any]:
    """
    Builds the `framework.types` filter selecting the CmdbTypes a user's groups may NOT access

    A type is denied when it carries an ACL, that ACL is switched **on**, and the groups taken together lack a
    required permission: some permission is listed by none of the groups. Everything else passes: no `acl` key, an
    `acl` that is switched off, and groups that between them hold every required permission.

    **"Switched on" is `activated: true`, and nothing else.** The type write schema stores the flag only as a
    boolean, and `updater_20261001` rewrote every older non-boolean value to the boolean the model reads it as -
    so an equality test is the model's reading exactly: an `acl` with no `activated` key, or a null one, is off
    here as it is in `acl/helpers.acl_grants_access` (where `AccessControlList.from_data` defaults the flag to
    False), and a single object read and a listing cannot disagree on a type

    **The groups combine.** A user in several groups holds the union of their entries, the same reading the rights
    have (`EffectiveRights`). So the rule is per permission: one `$nor` over the groups' entries matches a type no
    group lists that permission for - a missing entry included, since an equality test on an array field matches
    only an array holding the value. The type is denied when that is true for **any** required permission (`$or`)

    **Several permissions mean ALL of them** - held between the groups. Asking for `[READ, CREATE]` denies groups
    that hold only READ; one group holding READ and another CREATE pass. With a single group this is the
    conjunction the Angular `getAclFilter` has always applied to an array

    **No groups grant nothing**: an empty collection denies every activated ACL (fail closed) - and an empty `$nor`
    is not a query MongoDB accepts. A stored user always has at least one group

    Permissions are compared against `permission.value` because that is what a stored ACL holds: the
    permission's string value, which is also what the Angular ACL editor writes

    Args:
        group_ids (Collection[int]): public_ids of the CmdbUserGroups the request is made for - the user's
            ``group_ids``
        permission (AccessControlPermission | list[AccessControlPermission]): The permission, or
            every permission, the groups must hold between them

    Raises:
        ValueError: When an empty permission list is given (see `normalize_permissions`)

    Returns:
        dict[str, Any]: The criteria for a `framework.types` query
    """
    activated_path = f'{TypeSchemaKey.ACL.value}.{AclKey.ACTIVATED.value}'
    required = [entry.value for entry in normalize_permissions(permission)]
    groups: list[int] = sorted({int(group_id) for group_id in group_ids})

    if not groups:
        return {activated_path: True}

    missing_permission: list[dict[str, Any]] = [
        {'$nor': [{build_group_permissions_path(group_id): required_value} for group_id in groups]}
        for required_value in required
    ]

    return {
        '$and': [
            {activated_path: True},
            missing_permission[0] if len(missing_permission) == 1 else {'$or': missing_permission},
        ]
    }


@as_manager_read_error
def build_permitted_types_criteria(
        user: 'CmdbUser',
        permission: AccessControlPermission | list[AccessControlPermission]) -> dict[str, Any]:
    """
    Builds the ``framework.types`` filter selecting the CmdbTypes the user MAY access - for a query of the Types
    themselves

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission | list[AccessControlPermission]): The permission, or every permission,
            the user must hold

    Raises:
        ValueError: When an empty permission list is given
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        dict[str, Any]: The criteria for a ``framework.types`` query; empty when nothing is denied
    """
    # Imported lazily: the engine reads managers, which import this module through the query builders
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import permission_operations, permitted_types_criteria

    return permitted_types_criteria(user, permission_operations(permission))


def build_denied_types_condition(denied_type_ids: list[int]) -> dict[str, Any]:
    """
    Builds the filter excluding an already-resolved set of denied CmdbTypes

    The one expression of "exclude these types" - as a filter document, so a caller can put it
    wherever its query needs it: as its own `$match` stage, merged into a criteria, or `$and`-ed onto
    one. Every caller that excludes denied types goes through here, so the exclusion cannot drift
    into two spellings

    Args:
        denied_type_ids (list[int]): public_ids of the CmdbTypes the user's groups may not access

    Returns:
        dict[str, Any]: The filter document
    """
    return {CmdbObjectKey.TYPE_ID.value: {'$nin': denied_type_ids}}


@as_manager_read_error
def resolve_denied_type_ids(user: 'CmdbUser', permission: AccessControlPermission) -> list[int]:
    """
    Reads the CmdbType ids the user may not access

    The user's grants are read once per request; the Types and the objects' Type ids only when every Type is restricted
    (see ``access_engine.denied_type_ids``) - a gone Type an object still carries is listed then. A record stamping a
    gone Type no object carries (history) is judged by ``resolve_denied_types`` instead

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the user must hold

    Raises:
        BaseManagerGetError: When the user's grants or the Types could not be read

    Returns:
        list[int]: public_ids of the denied CmdbTypes, ascending; empty when the user may access every type
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import denied_type_ids, permission_operations

    return denied_type_ids(user, permission_operations(permission))


@as_manager_read_error
def resolve_denied_types(user: 'CmdbUser', permission: AccessControlPermission) -> 'DeniedTypes':
    """
    Reads the user's denial of a permission as the access engine holds it - the denied Types, or every Type but the
    admitted ones - for a reader of history: a record stamped with a Type that no longer exists, or with none, is
    judged by ``denies()`` like every other (denied when every Type is restricted, else readable), and its filter is
    ``access_engine.id_criteria`` on the stamped key. Reads no Type and no object

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the user must hold

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        DeniedTypes: The denial
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import denied_types, permission_operations

    return denied_types(user, permission_operations(permission))


@as_manager_read_error
def build_scope_criteria(user: 'CmdbUser', permission: AccessControlPermission) -> dict[str, Any]:
    """
    Builds the CmdbObject filter for the objects the user may access - to merge into a query's own criteria

    Unlike an exclusion by ``resolve_denied_type_ids``, it keeps an object of a gone Type out when every Type is
    restricted (it then admits the granted Types instead of excluding the denied ones), and it lets in the objects a
    conditional assignment's condition matches (phase 9) - for CmdbObject queries only; a record's query takes
    ``build_record_scope_criteria``

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the user must hold

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        dict[str, Any]: The filter; empty when the user may access every type
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import permission_operations, scope_filter

    return scope_filter(user, permission_operations(permission))


@as_manager_read_error
def build_record_scope_criteria(user: 'CmdbUser', permission: AccessControlPermission) -> dict[str, Any]:
    """
    Builds the Type-only filter on a record's ``type_id`` - for what is no CmdbObject (history, other collections): a
    Type the user holds only through conditional assignments is denied, since a record carries no object state to
    judge a condition on (phase 9, R26)

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the user must hold

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        dict[str, Any]: The filter; empty when the user may access every type
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.framework.access_engine import permission_operations, record_scope_filter

    return record_scope_filter(user, permission_operations(permission))


@as_manager_read_error
def build_acl_pipeline(user: 'CmdbUser', permission: AccessControlPermission) -> list[dict[str, Any]]:
    """
    Builds the access-control stage restricting a CmdbObject pipeline to what a user may see

    Append it as early as possible - before sorting and paginating - so that the skipped and limited document set is
    the one the user is actually allowed to read

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the user must hold

    Raises:
        BaseManagerGetError: When the user's grants could not be read

    Returns:
        list[dict[str, Any]]: One ``$match`` stage, none when the user may access every type
    """
    criteria: dict[str, Any] = build_scope_criteria(user, permission)

    return [Builder.match_(criteria)] if criteria else []
