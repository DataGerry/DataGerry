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
from flask import abort

from cmdb.manager import GroupsManager
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
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
