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
Where a CmdbUserGroup is still used - the census behind the group delete and its pre-check route

Besides its members a group is named by the LDAP provider's settings (its ``default_group`` and the ``group_id`` of
each mapping row) and by the ``acl.groups.includes`` of CmdbTypes. Deleting a group the LDAP settings still name
would provision or move directory users into a group that no longer exists; deleting the only existing group an
activated type ACL grants would leave the list granting nobody, and the type - with its objects - unreadable,
uneditable and undeletable for everyone, administrators included. The delete refuses both (``abort_if_group_in_use``)
and the pre-check route answers the same census (``read_group_usage``). A type whose ACL names the group next to
other granted groups loses only the group's entry, inside the delete's write ledger (``remove_group_from_type_acls``)
"""
from dataclasses import dataclass, field
from typing import Any

from flask import abort

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import GroupsManager, SettingsManager, TypesManager, UsersManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUserKey
from cmdb.security.acl.acl_groups import acl_includes, granting_group_ids, is_sole_grantee
from cmdb.security.acl.builder import build_group_permissions_path
from cmdb.security.auth.providers.ldap_group_references import as_group_id, ldap_group_references
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_ACL_ENTRIES_REMOVAL,
    GROUP_IN_USE_MSG,
    GROUP_USE_LDAP_DEFAULT,
    GROUP_USE_LDAP_MAPPING,
    GROUP_USE_SEPARATOR,
    GROUP_USE_SOLE_GRANTEE,
    GroupUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['GroupUsage', 'abort_if_group_in_use', 'read_group_usage', 'remove_group_from_type_acls']


@dataclass
class GroupUsage:
    """
    Where one CmdbUserGroup is used

    Attributes:
        members (int): How many users belong to it - the delete's ``action`` decides about them
        ldap_default_group (bool): Whether it is the LDAP provider's default group
        ldap_group_mappings (list[str]): The directory group DNs whose mapping row names it
        sole_grantee_type_ids (list[int]): The types whose activated ACL grants no other existing group
        acl_entries (dict[int, Any]): Every type whose ACL names it -> the group's stored permission entry
    """
    members: int = 0
    ldap_default_group: bool = False
    ldap_group_mappings: list[str] = field(default_factory=list)
    sole_grantee_type_ids: list[int] = field(default_factory=list)
    acl_entries: dict[int, Any] = field(default_factory=dict)

    @property
    def blocks_delete(self) -> bool:
        """Whether a holder other than the members keeps the group from being deleted"""
        return self.ldap_default_group or bool(self.ldap_group_mappings) or bool(self.sole_grantee_type_ids)

    def holders(self) -> list[str]:
        """
        Spells each holder that blocks the delete, as the refusal names it

        Returns:
            list[str]: One part per blocking holder, in a fixed order; empty when nothing blocks
        """
        parts: list[str] = []

        if self.ldap_default_group:
            parts.append(GROUP_USE_LDAP_DEFAULT)

        if self.ldap_group_mappings:
            parts.append(GROUP_USE_LDAP_MAPPING.format(group_dns=self.ldap_group_mappings))

        if self.sole_grantee_type_ids:
            parts.append(GROUP_USE_SOLE_GRANTEE.format(type_ids=self.sole_grantee_type_ids))

        return parts

    def to_json(self) -> dict[str, Any]:
        """
        The census as ``GET /groups/<id>/usage`` answers it

        Returns:
            dict[str, Any]: One ``GroupUsageKey`` per fact, plus whether they block the delete
        """
        return {
            GroupUsageKey.MEMBERS.value: self.members,
            GroupUsageKey.LDAP_DEFAULT_GROUP.value: self.ldap_default_group,
            GroupUsageKey.LDAP_GROUP_MAPPINGS.value: list(self.ldap_group_mappings),
            GroupUsageKey.SOLE_GRANTEE_TYPE_IDS.value: list(self.sole_grantee_type_ids),
            GroupUsageKey.ACL_TYPE_IDS.value: sorted(self.acl_entries),
            GroupUsageKey.BLOCKS_DELETE.value: self.blocks_delete,
        }


def read_ldap_usage(usage: GroupUsage, group_id: int, auth_settings: Any) -> None:
    """
    Fills in where the stored LDAP settings name the group

    Args:
        usage (GroupUsage): The census being built, changed in place
        group_id (int): The group in question
        auth_settings (Any): The stored auth settings section
    """
    for reference in ldap_group_references(auth_settings):
        if as_group_id(reference.value) != group_id:
            continue

        if reference.is_default:
            usage.ldap_default_group = True
        else:
            usage.ldap_group_mappings.append(reference.group_dn)


def read_acl_usage(usage: GroupUsage, group_id: int, types_manager: TypesManager,
                   groups_manager: GroupsManager) -> None:
    """
    Fills in which types' ACL names the group, and for which of them it is the only existing grantee

    Two reads whatever the number of types: the types whose ACL carries the group's key (projected to the ACL), and
    which of the groups those ACLs grant still exist

    Args:
        usage (GroupUsage): The census being built, changed in place
        group_id (int): The group in question
        types_manager (TypesManager): Reads the types
        groups_manager (GroupsManager): Answers which granted groups exist
    """
    documents: list[dict[str, Any]] = types_manager.find(
        criteria={build_group_permissions_path(group_id): {'$exists': True}},
        projection={TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.ACL.value: 1},
    )

    if not documents:
        return

    granted: set[int] = set()

    for document in documents:
        granted |= granting_group_ids(document.get(TypeSchemaKey.ACL.value))

    existing: set[int] = groups_manager.find_existing_public_ids(sorted(granted - {group_id})) | {group_id}

    for document in documents:
        type_id: int = document[TypeSchemaKey.PUBLIC_ID.value]
        acl: Any = document.get(TypeSchemaKey.ACL.value)
        usage.acl_entries[type_id] = acl_includes(acl).get(str(group_id))

        if is_sole_grantee(acl, group_id, existing):
            usage.sole_grantee_type_ids.append(type_id)

    usage.sole_grantee_type_ids.sort()


def read_group_usage(
        group_id: int,
        managers: tuple[UsersManager, SettingsManager, TypesManager, GroupsManager]) -> GroupUsage:
    """
    Answers where a CmdbUserGroup is used: its members, the LDAP settings, and the type ACLs

    Args:
        group_id (int): The group in question
        managers (tuple[UsersManager, SettingsManager, TypesManager, GroupsManager]): The managers of the request

    Returns:
        GroupUsage: The census
    """
    users_manager, settings_manager, types_manager, groups_manager = managers
    usage = GroupUsage(members=users_manager.count_documents({CmdbUserKey.GROUP_ID.value: group_id}))

    read_ldap_usage(usage, group_id, settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default={}))
    read_acl_usage(usage, group_id, types_manager, groups_manager)

    return usage


def abort_if_group_in_use(usage: GroupUsage, group_id: int) -> None:
    """
    Refuses a group delete while the LDAP settings name the group or a type's ACL grants only it

    Args:
        usage (GroupUsage): The census of the group
        group_id (int): The group being deleted

    Raises:
        HTTPException: 400 naming every blocking holder
    """
    if usage.blocks_delete:
        abort(400, GROUP_IN_USE_MSG.format(public_id=group_id, holders=GROUP_USE_SEPARATOR.join(usage.holders())))


def remove_group_from_type_acls(ledger: WriteLedger, types_manager: TypesManager, group_id: int,
                                usage: GroupUsage) -> None:
    """
    Removes the group's entry from every type ACL that names it, recorded so a failed delete puts it back

    Only reached for types where other groups are granted too (a sole grantee refuses the delete). One update for
    all of them; the undo writes each type's own entry back

    Args:
        ledger (WriteLedger): The delete's ledger
        types_manager (TypesManager): Writes the types
        group_id (int): The group being deleted
        usage (GroupUsage): Its census, carrying each type's stored entry
    """
    entries: dict[int, Any] = dict(usage.acl_entries)

    if not entries:
        return

    path: str = build_group_permissions_path(group_id)
    type_ids: list[int] = sorted(entries)

    def _undo() -> None:
        for type_id, entry in entries.items():
            types_manager.update({TypeSchemaKey.PUBLIC_ID.value: type_id}, {'$set': {path: entry}})

    def _verify() -> bool:
        restored: int = types_manager.count_documents({
            TypeSchemaKey.PUBLIC_ID.value: {'$in': type_ids}, path: {'$exists': True},
        })

        return restored == len(type_ids)

    ledger.compensated(types_manager.collection, GROUP_ACL_ENTRIES_REMOVAL.format(type_ids=type_ids),
                       undo=_undo, verify=_verify)
    types_manager.update_many_raw({TypeSchemaKey.PUBLIC_ID.value: {'$in': type_ids}}, {'$unset': {path: ''}})
