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
The CmdbUserGroups a CmdbType's access control list names must exist

``acl.groups.includes`` is keyed by CmdbUserGroup public_id. An entry for a group that does not exist grants nobody,
so an activated list made only of such entries locks the type - and its objects - for everyone, administrators
included. The type write routes refuse such an entry (``abort_if_unknown_acl_groups``); the type importer drops it
instead (``importer_type_repairs.clear_dangling_acl_groups``), since another installation's group ids mean nothing
here, and a group delete takes the group's entries out of every type ACL (``group_usage_helper``)
"""
from typing import Any

from cmdb.manager import GroupsManager
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.acl_groups import acl_group_ids
from cmdb.interface.rest_api.routes.routes_helper import abort_on_unknown_references
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import USER_GROUP_LABEL
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['abort_if_unknown_acl_groups']


def abort_if_unknown_acl_groups(type_data: dict[str, Any], groups_manager: GroupsManager,
                                stored_acl: Any = None) -> None:
    """
    Refuses a type write whose ``acl`` names a CmdbUserGroup that does not exist

    An entry for a group that does not exist grants nobody, so an activated list made only of such entries locks
    the type for everyone. On an update only the groups the stored list does not already name are judged: an entry
    for a missing group that the stored list already carries is inert, and refusing it would make the type
    unsaveable over an entry the editor may not even be shown. The type importer drops unknown entries instead
    (``importer_type_repairs.clear_dangling_acl_groups``) - another installation's group ids mean nothing here

    Args:
        type_data (dict[str, Any]): The type payload, already shape-checked by the write schema
        groups_manager (GroupsManager): Answers which groups exist, in one read
        stored_acl (Any): The stored type's ``acl`` on an update; None on a create

    Raises:
        HTTPException: 400 naming the group ids that do not exist
    """
    named: set[int] = set(acl_group_ids(type_data.get(TypeSchemaKey.ACL.value)))

    if stored_acl is not None:
        named -= set(acl_group_ids(stored_acl))

    abort_on_unknown_references(groups_manager, sorted(named), USER_GROUP_LABEL)
