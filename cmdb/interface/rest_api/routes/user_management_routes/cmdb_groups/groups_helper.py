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
Helper methods shared by the CmdbUserGroup REST routes
"""
from typing import Any
from flask import abort

from cmdb.manager import GroupsManager
from cmdb.models.group_model import (
    CmdbUserGroup,
    GroupDeleteMode,
    GroupKey,
    ADMIN_GROUP_ID,
    MASTER_RIGHT_NAME,
)
# -------------------------------------------------------------------------------------------------------------------- #


def resolve_move_target(
    groups_manager: GroupsManager,
    action: GroupDeleteMode | None,
    target_group_id: int | None,
) -> CmdbUserGroup | None:
    """
    Validates and resolves the destination group for a MOVE-mode group deletion

    Only meaningful for the ``MOVE`` action: the caller must supply a ``target_group_id`` and that
    group must exist. For any other action (``DELETE`` or ``None``) there is no target to resolve

    Args:
        groups_manager (GroupsManager): Manager used to look up the target group
        action (GroupDeleteMode | None): The delete mode requested for the source group
        target_group_id (int | None): public_id of the group members should be moved to

    Raises:
        HTTPException: 400 if ``MOVE`` is requested without a ``target_group_id``; 404 if the target
            group does not exist

    Returns:
        CmdbUserGroup | None: The resolved target group for ``MOVE``, otherwise None
    """
    if action != GroupDeleteMode.MOVE:
        return None

    if not target_group_id:
        abort(400, "The target group for moving users was not provided!")

    target_group: CmdbUserGroup | None = groups_manager.get_group(target_group_id)

    if not target_group:
        abort(404, f"The target UserGroup for moving users with ID:{target_group_id} was not found!")

    return target_group


def ensure_admin_group_keeps_master_right(public_id: int, data: dict[str, Any]) -> None:
    """
    Refuses a CmdbUserGroup update that would strip the master right from the administrator group

    The administrator group (``ADMIN_GROUP_ID``) is seeded with the single right
    ``MASTER_RIGHT_NAME`` ('base.*'), which is what grants its members every other right. Since an
    update is always a full-object write, a payload whose ``rights`` list omits that right would
    remove it - and with it the ``base.user-management.group.edit`` right needed to hand it back,
    locking every administrator out of the system with no in-app way to recover

    The membership test deliberately mirrors ``CmdbUserGroup.from_data``, which resolves rights by
    matching right names against the raw payload list: a payload carrying full right *dicts*
    instead of name strings resolves to no rights at all, so it is rejected here as well

    Any other group, and any other change to the administrator group (its name, its label, adding
    further rights), is unaffected

    Args:
        public_id (int): public_id of the CmdbUserGroup being updated (taken from the URL)
        data (dict[str, Any]): The validated update payload for that group

    Raises:
        HTTPException: 400 if the administrator group's update payload does not keep the master right
    """
    if public_id != ADMIN_GROUP_ID:
        return

    submitted_rights: list = data.get(GroupKey.RIGHTS) or []

    if MASTER_RIGHT_NAME not in submitted_rights:
        abort(
            400,
            f"The right '{MASTER_RIGHT_NAME}' cannot be removed from the administrator group, "
            "otherwise no user could administrate DataGerry anymore!"
        )
