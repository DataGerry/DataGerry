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
with no ACL, a type whose ACL is switched off, and a type that grants the permission. Because the
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


def build_denied_types_criteria(group_id: int, permission: AccessControlPermission) -> dict[str, Any]:
    """
    Builds the `framework.types` filter selecting the CmdbTypes a group may NOT access

    A type is denied when it carries an ACL, that ACL is not switched off, and the group's permission
    list does not contain the required permission. The three clauses are the exact negation of the
    three ways the previous per-document `$match` let a document through (no `acl` key / `activated`
    is False / the group holds the permission), so the filter is equivalent rather than merely
    similar - including the awkward middle case of an `acl` that carries no `activated` key at all,
    which `$ne: False` denies just as the old `{'type.acl.activated': False}` clause failed to allow

    `$all` does not match a missing field, so wrapping it in `$nor` covers both "the group has no
    entry" and "the group's entry lacks this permission" in one clause - which is why no separate
    `$exists` check on the group is needed

    Permissions are compared against `permission.value` because that is what a stored ACL holds: the
    permission's string value, which is also what the Angular ACL editor writes

    Args:
        group_id (int): public_id of the CmdbUserGroup the request is made for
        permission (AccessControlPermission): The permission the group must hold

    Returns:
        dict[str, Any]: The criteria for a `framework.types` query
    """
    acl_path = TypeSchemaKey.ACL.value
    activated_path = f'{acl_path}.{AclKey.ACTIVATED.value}'

    return {
        '$and': [
            {acl_path: {'$exists': True}},
            {activated_path: {'$ne': False}},
            {'$nor': [{build_group_permissions_path(group_id): {'$all': [permission.value]}}]},
        ]
    }


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

    return [{'$match': {CmdbObjectKey.TYPE_ID.value: {'$nin': denied_type_ids}}}]


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
