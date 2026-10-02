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
String constants used by the CmdbLocation REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class LocationRight(BaseStrEnum):
    """The ``base.framework.location.*`` ACL rights enforced by the CmdbLocation routes."""
    VIEW = 'base.framework.location.view'
    ADD = 'base.framework.location.add'
    EDIT = 'base.framework.location.edit'
    DELETE = 'base.framework.location.delete'


# Fallback name template applied when a CmdbLocation has no explicit name and the linked
# CmdbObject yields no usable summary line. Format with the object's public_id.
OBJECT_ID_NAME_TEMPLATE: str = 'ObjectID: {object_id}'

# Not found (HTTP 404) when the CmdbObject a CmdbLocation is written for does not exist. Format with its public_id
LINKED_OBJECT_NOT_FOUND_MSG: str = "The linked Object with ID:{object_id} was not found in the database!"

# Forbidden (HTTP 403) when the caller may not read the CmdbObject a CmdbLocation is written for: the node carries
# the object's summary as its name, so writing one is a read of the object. Format with its public_id
LINKED_OBJECT_DENIED_MSG: str = "No permission to read the linked Object with ID:{object_id}!"

# Bad request (HTTP 400) when POST /locations/ names a type the linked CmdbObject does not have. The node's type
# fields are the object's own type's. Format with both ids
LINKED_OBJECT_TYPE_MISMATCH_MSG: str = (
    "The Object with ID:{object_id} is of Type ID:{object_type_id}, not of the requested Type ID:{type_id}!"
)

# Response-only key added to each lazy location-tree node signalling whether it can be expanded
LOCATION_TREE_HAS_CHILDREN_KEY: str = 'has_children'

# Request/response body key carrying the objects of a bulk placement move. Not a CmdbLocation document
# key (those live in LocationKey) - it exists only in the PATCH /parents payload
BULK_MOVE_OBJECT_IDS_KEY: str = 'object_ids'


# Server error (HTTP 500) when a CmdbLocation delete failed part-way and undoing what it had already written did
# not finish either: the named writes - promoted children, the removed node, re-pointed object fields - are still in
# effect and need a look by hand
LOCATION_DELETE_UNDO_INCOMPLETE_MSG: str = (
    "Deleting the Location failed, and undoing what it had already written did not finish. "
    "These writes are still in effect and have to be checked by hand: {residue}"
)
