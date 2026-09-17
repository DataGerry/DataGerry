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
Access-control filtering for CmdbObject aggregation pipelines

An ACL lives on the CmdbType, not on the CmdbObject, so "may this group read this object" is really
"may this group read objects of this object's type". The filter is therefore built by resolving,
once per query, the small set of CmdbTypes the requesting group may NOT access, and excluding those
type_ids from the pipeline:

    [{'$match': {'type_id': {'$nin': [<denied type ids>]}}}]

A type is denied when its ACL is activated AND the group's entry does not carry the required
permission - a missing entry denies just as an incomplete one does. Everything else passes: a type
with no ACL, a type whose ACL is switched off - including one carrying no `activated` key at all,
which is the model's reading of that shape (T208) - and a type that grants the permission. Because the
filter is an exclusion, an object whose type_id resolves to no CmdbType at all (an orphan) also
passes, which is the behaviour the previous `$lookup`-based implementation had through its
`preserveNullAndEmptyArrays` unwind

When nothing is denied - the common case, since most installations activate an ACL on few types or
none - `build_acl_pipeline` returns no stages at all and the query runs unfiltered
"""
from typing import TYPE_CHECKING, Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.permission import AccessControlPermission

if TYPE_CHECKING:
    # Imported for type checking only; importing the model at runtime would pull the manager package
    # back into this module and close an import cycle
    from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

#: Projection used when resolving denied types - only the identity is needed, never the document
DENIED_TYPES_PROJECTION: dict[str, int] = {TypeSchemaKey.PUBLIC_ID.value: 1}


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
            permissions the group must hold **all** of

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
        group_id: int,
        permission: AccessControlPermission | list[AccessControlPermission]) -> dict[str, Any]:
    """
    Builds the `framework.types` filter selecting the CmdbTypes a group may NOT access

    A type is denied when it carries an ACL, that ACL is switched **on**, and the group's permission
    list does not contain the required permission. Everything else passes: no `acl` key, an `acl`
    that is switched off, and a group that holds the permission.

    **What "switched on" means is the model's reading, since 2026-09-17** (tier 2 **T208**). An `acl`
    carrying no `activated` key at all is **not** activated and therefore grants - which is what
    `acl/helpers.acl_grants_access` has always answered for the same document, because
    `AccessControlList.from_data` defaults the flag to False. This criteria used to read
    `activated $ne False`, which denied that shape, so a single object read and a listing disagreed
    on it. `$exists` plus `$nin: [False, None]` is the closest expression of Python truthiness a
    query can give: its one remaining divergence from the model is a stored `0`, which the model
    reads as off and this reads as on - a listing stricter than the single read, which is the safe
    direction for the two to differ in

    `$all` does not match a missing field, so wrapping it in `$nor` covers both "the group has no
    entry" and "the group's entry lacks this permission" in one clause - which is why no separate
    `$exists` check on the group is needed

    **Several permissions mean ALL of them.** `$all` is a conjunction, so asking for
    `[READ, CREATE]` denies a group that holds only one of the two. That is the same reading the
    Angular `getAclFilter` has always had for an array, so the two agree by construction

    Permissions are compared against `permission.value` because that is what a stored ACL holds: the
    permission's string value, which is also what the Angular ACL editor writes

    Args:
        group_id (int): public_id of the CmdbUserGroup the request is made for
        permission (AccessControlPermission | list[AccessControlPermission]): The permission, or
            every permission, the group must hold

    Raises:
        ValueError: When an empty permission list is given (see `normalize_permissions`)

    Returns:
        dict[str, Any]: The criteria for a `framework.types` query
    """
    acl_path = TypeSchemaKey.ACL.value
    activated_path = f'{acl_path}.{AclKey.ACTIVATED.value}'
    required = [entry.value for entry in normalize_permissions(permission)]

    return {
        '$and': [
            {acl_path: {'$exists': True}},
            {activated_path: {'$exists': True, '$nin': [False, None]}},
            {'$nor': [{build_group_permissions_path(group_id): {'$all': required}}]},
        ]
    }


def build_permitted_types_criteria(
        group_id: int,
        permission: AccessControlPermission | list[AccessControlPermission]) -> dict[str, Any]:
    """
    Builds the `framework.types` filter selecting the CmdbTypes a group MAY access

    The negation of ``build_denied_types_criteria``, for the callers that are querying
    `framework.types` **itself**. A listing of types has its access-control rule stored on the very
    documents it is listing, so it never needs the two-step ``resolve_denied_type_ids`` recipe an
    object listing does - that one exists only because an object's ACL lives on another collection.
    One `$nor` over the same criteria costs **no extra query at all**

    Both functions are the same rule, so a change to the denial criteria reaches every caller of
    either - including what it says about an ``acl`` carrying no ``activated`` key, which grants,
    the same answer ``acl/helpers.acl_grants_access`` gives (**T208**)

    Args:
        group_id (int): public_id of the CmdbUserGroup the request is made for
        permission (AccessControlPermission | list[AccessControlPermission]): The permission, or
            every permission, the group must hold

    Raises:
        ValueError: When an empty permission list is given (see `normalize_permissions`)

    Returns:
        dict[str, Any]: The criteria for a `framework.types` query
    """
    return {'$nor': [build_denied_types_criteria(group_id, permission)]}


def build_denied_types_condition(denied_type_ids: list[int]) -> dict[str, Any]:
    """
    Builds the filter excluding an already-resolved set of denied CmdbTypes

    The one expression of "exclude these types" - as a filter document, so a caller can put it
    wherever its query needs it: as its own `$match` stage, merged into a criteria, or `$and`-ed onto
    one. Every caller that excludes denied types goes through here, so the exclusion cannot drift
    into two spellings

    Args:
        denied_type_ids (list[int]): public_ids of the CmdbTypes the group may not access

    Returns:
        dict[str, Any]: The filter document
    """
    return {CmdbObjectKey.TYPE_ID.value: {'$nin': denied_type_ids}}


def build_acl_stages(denied_type_ids: list[int]) -> list[dict[str, Any]]:
    """
    Builds the pipeline stages excluding the denied CmdbTypes

    Args:
        denied_type_ids (list[int]): public_ids of the CmdbTypes the group may not access

    Returns:
        list[dict[str, Any]]: A single `$match` stage, or no stages at all when nothing is denied
    """
    if not denied_type_ids:
        return []

    return [{'$match': build_denied_types_condition(denied_type_ids)}]


def resolve_denied_type_ids(user: 'CmdbUser', permission: AccessControlPermission) -> list[int]:
    """
    Reads the CmdbTypes the user's group may not access

    One projected query against `framework.types`, which holds tens of documents rather than the
    thousands the object collection does - so this is far cheaper than the per-document `$lookup`
    join this replaced, and it keeps the object query on the indexed `type_id` path

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the group must hold

    Returns:
        list[int]: public_ids of the denied CmdbTypes; empty when the group may access everything
    """
    # Imported lazily: the manager package imports this module through the query builders, so a
    # module-level import would close an import cycle
    # pylint: disable=import-outside-toplevel
    from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

    types_manager = ManagerProvider.get_manager(ManagerType.TYPES, user)

    denied_types = types_manager.find(
        criteria=build_denied_types_criteria(int(user.group_id), permission),
        projection=DENIED_TYPES_PROJECTION,
    )

    return [
        denied_type[TypeSchemaKey.PUBLIC_ID.value]
        for denied_type in denied_types
        if denied_type.get(TypeSchemaKey.PUBLIC_ID.value) is not None
    ]


def build_acl_pipeline(user: 'CmdbUser', permission: AccessControlPermission) -> list[dict[str, Any]]:
    """
    Builds the access-control stages restricting a CmdbObject pipeline to what a user may see

    Append these stages as early as possible - before sorting and paginating - so that the skipped
    and limited document set is the one the user is actually allowed to read

    Args:
        user (CmdbUser): The CmdbUser the request is made for
        permission (AccessControlPermission): The permission the group must hold

    Returns:
        list[dict[str, Any]]: The filter stages, empty when the group may access every type
    """
    return build_acl_stages(resolve_denied_type_ids(user, permission))
