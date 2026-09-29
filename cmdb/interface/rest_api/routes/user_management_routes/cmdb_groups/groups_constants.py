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
Constants used by the CmdbUserGroup REST routes

Centralises the ACL right strings each endpoint guards on and the URL segments the blueprint
registers, so the route module carries no magic strings (matching the per-section folder convention
used by cmdb_categories / cmdb_section_templates / cmdb_license). The right values must match the
``base.user-management.group.*`` rights registered in the right tree
"""
# Base prefix of the CmdbUserGroup ACL rights (as registered in the right tree)
GROUP_RIGHT_PREFIX: str = 'base.user-management.group'

# Per-endpoint ACL rights checked by the route ``protect`` decorators
GROUP_ADD_RIGHT: str = f'{GROUP_RIGHT_PREFIX}.add'
GROUP_VIEW_RIGHT: str = f'{GROUP_RIGHT_PREFIX}.view'
GROUP_EDIT_RIGHT: str = f'{GROUP_RIGHT_PREFIX}.edit'
GROUP_DELETE_RIGHT: str = f'{GROUP_RIGHT_PREFIX}.delete'

# URL segments registered by the groups blueprint
GROUPS_COLLECTION_ROUTE: str = '/'
GROUP_ITEM_ROUTE: str = '/<int:public_id>'

# A delete that names no action for a group that still has members: those members would be left holding a
# group_id that resolves to nothing - authenticated, and refused every right
GROUP_MEMBERS_NEED_ACTION_MSG: str = (
    "The UserGroup with ID:{public_id} still has members - choose action=MOVE (with a target group_id) "
    "or action=DELETE for them!"
)

# A MOVE whose target is the group being deleted moves the members into a group that is about to be gone
GROUP_MOVE_TARGET_IS_SOURCE_MSG: str = (
    "The users of the UserGroup with ID:{public_id} cannot be moved into the group that is being deleted!"
)
