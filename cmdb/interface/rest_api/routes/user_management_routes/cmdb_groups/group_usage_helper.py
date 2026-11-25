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
each mapping row) and by the access assignments granting to it. Deleting a group the LDAP settings still name would
provision or move directory users into a group that no longer exists - the delete refuses it
(``abort_if_group_in_use``). The group's assignments go with it: the census answers which they are and the Types
their removal would lock (no group may view them any more - refused) or open (no assigned role restricts them any
more - refused unless confirmed), as ``access_change_guard.group_delete_effect`` judges them. The pre-check route
answers the whole census (``read_group_usage`` + ``add_access_usage``)
"""
from dataclasses import dataclass, field
from typing import Any

from flask import abort

from cmdb.manager import SettingsManager, UsersManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.models.user_model import CmdbUserKey
from cmdb.security.auth.providers.ldap_group_references import as_group_id, ldap_group_references
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import GroupDeleteEffect
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_IN_USE_MSG,
    GROUP_USE_LDAP_DEFAULT,
    GROUP_USE_LDAP_MAPPING,
    GROUP_USE_SEPARATOR,
    GroupUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'GroupUsage',
    'abort_if_group_in_use',
    'add_access_usage',
    'read_group_usage',
]


@dataclass
class GroupUsage:
    """
    Where one CmdbUserGroup is used

    Attributes:
        members (int): How many users belong to it - each loses it on a delete
        sole_members (int): How many of them have no other group - the delete's ``action`` decides about them
        ldap_default_group (bool): Whether it is the LDAP provider's default group
        ldap_group_mappings (list[str]): The directory group DNs whose mapping row names it
        locked_type_ids (list[int]): The Types the delete would leave viewable by no group - it is refused
        opened_type_ids (list[int]): The Types the delete would leave restricted by no assigned role - it needs
            ``unrestrict=true``
        assignment_ids (list[int]): The access assignments granting to it - they are deleted with it
    """
    members: int = 0
    sole_members: int = 0
    ldap_default_group: bool = False
    ldap_group_mappings: list[str] = field(default_factory=list)
    locked_type_ids: list[int] = field(default_factory=list)
    opened_type_ids: list[int] = field(default_factory=list)
    assignment_ids: list[int] = field(default_factory=list)

    @property
    def ldap_holds(self) -> bool:
        """Whether the LDAP settings name the group"""
        return self.ldap_default_group or bool(self.ldap_group_mappings)

    @property
    def blocks_delete(self) -> bool:
        """Whether something other than the members keeps the group from being deleted, whatever is confirmed"""
        return self.ldap_holds or bool(self.locked_type_ids)

    def holders(self) -> list[str]:
        """
        Spells each LDAP holder that blocks the delete, as the refusal names it

        Returns:
            list[str]: One part per blocking holder, in a fixed order; empty when nothing blocks
        """
        parts: list[str] = []

        if self.ldap_default_group:
            parts.append(GROUP_USE_LDAP_DEFAULT)

        if self.ldap_group_mappings:
            parts.append(GROUP_USE_LDAP_MAPPING.format(group_dns=self.ldap_group_mappings))

        return parts

    def to_json(self) -> dict[str, Any]:
        """
        The census as ``GET /groups/<id>/usage`` answers it

        Returns:
            dict[str, Any]: One ``GroupUsageKey`` per fact, plus whether they block the delete
        """
        return {
            GroupUsageKey.MEMBERS.value: self.members,
            GroupUsageKey.SOLE_MEMBERS.value: self.sole_members,
            GroupUsageKey.LDAP_DEFAULT_GROUP.value: self.ldap_default_group,
            GroupUsageKey.LDAP_GROUP_MAPPINGS.value: list(self.ldap_group_mappings),
            GroupUsageKey.LOCKED_TYPE_IDS.value: list(self.locked_type_ids),
            GroupUsageKey.OPENED_TYPE_IDS.value: list(self.opened_type_ids),
            GroupUsageKey.ASSIGNMENT_IDS.value: list(self.assignment_ids),
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


def read_group_usage(group_id: int, managers: tuple[UsersManager, SettingsManager]) -> GroupUsage:
    """
    Answers where a CmdbUserGroup is used by its members and the LDAP settings

    Args:
        group_id (int): The group in question
        managers (tuple[UsersManager, SettingsManager]): The managers of the request

    Returns:
        GroupUsage: The census, its access part still empty (``add_access_usage``)
    """
    users_manager, settings_manager = managers
    usage = GroupUsage(
        members=users_manager.count_documents({CmdbUserKey.GROUP_IDS.value: group_id}),
        sole_members=users_manager.count_documents(users_manager.sole_member_criteria(group_id)),
    )

    read_ldap_usage(usage, group_id, settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default={}))

    return usage


def add_access_usage(usage: GroupUsage, effect: GroupDeleteEffect) -> None:
    """
    Adds what the delete would do to the access rules to the group's census

    Args:
        usage (GroupUsage): The census, extended in place
        effect (GroupDeleteEffect): The group's assignments and the Types their removal locks and opens
    """
    usage.assignment_ids = list(effect.assignment_ids)
    usage.locked_type_ids = list(effect.locked)
    usage.opened_type_ids = list(effect.opened)


def abort_if_group_in_use(usage: GroupUsage, group_id: int) -> None:
    """
    Refuses a group delete while the LDAP settings name the group

    The Types the delete would lock or open are judged by ``access_change_guard.guard_group_delete``, with the
    access rules' own messages

    Args:
        usage (GroupUsage): The census of the group
        group_id (int): The group being deleted

    Raises:
        HTTPException: 400 naming every LDAP holder
    """
    if usage.ldap_holds:
        abort(400, GROUP_IN_USE_MSG.format(public_id=group_id, holders=GROUP_USE_SEPARATOR.join(usage.holders())))
