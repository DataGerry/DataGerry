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

# Refusal (HTTP 400) of a group write whose ``rights`` names a right the right tree does not know; {names} lists each
# unknown name once, in the order sent
GROUP_UNKNOWN_RIGHTS_MSG: str = "The UserGroup names rights that do not exist: {names}!"

# Refusal (HTTP 400) when another CmdbUserGroup already carries the name - by the route's pre-check or, under a
# concurrent write, by the unique index on name. The name is compared exactly as sent, as the index does
GROUP_NAME_TAKEN_MSG: str = "A UserGroup with the name '{name}' already exists!"

# Server error (HTTP 500) when the CmdbUserGroup the insert just reported cannot be read back - the server
# losing sight of its own write, not a missing resource the caller asked for
GROUP_CREATED_NOT_READABLE_MSG: str = "Could not retrieve the created UserGroup from the database!"

# Refusal (HTTP 400) of a DELETE-mode group delete whose members include the bootstrap admin user, who must never
# be deleted - checked before anything is written
GROUP_ADMIN_MEMBER_MSG: str = "This UserGroup cannot be deleted because the admin user is part of it!"

# Server error (HTTP 500) when a failed group delete could not be fully undone, with the writes still in effect
GROUP_DELETE_UNDO_INCOMPLETE_MSG: str = (
    "The UserGroup delete failed and could not be fully undone - still in effect: {residue}"
)
