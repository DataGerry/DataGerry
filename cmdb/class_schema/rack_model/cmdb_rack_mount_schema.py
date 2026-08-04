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
Validation schema for CmdbRackMount

A CmdbRackMount binds one CmdbObject to one Rack (collection ``framework.rackMounts``). The row's
existence is the object's MEMBERSHIP of the rack; its geometry is the object's PLACEMENT within it,
which is optional - an UNASSIGNED row is a member with no placement.

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbRackMount.SCHEMA. Note this schema only describes the document's SHAPE; which geometry keys an
area actually requires, and whether a placement collides with another, is decided by
cmdb.framework.rack.mount_validator - a per-field schema cannot express a cross-field or
cross-document rule
"""
from typing import Any

from cmdb.models.rack_model.rack_mount_constants import RackArea
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_rack_mount_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbRackMount document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbRackMount.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbRackMount
            'type': 'integer',
        },
        'rack_id': {  # public_id of the Rack CmdbObject this mount belongs to
            'type': 'integer',
            'required': True,
        },
        'object_id': {  # public_id of the mounted CmdbObject (unique - one rack per object)
            'type': 'integer',
            'required': True,
        },
        'area': {  # Where in the rack the object sits; UNASSIGNED means "member, not placed"
            'type': 'string',
            'required': True,
            'allowed': [area.value for area in RackArea],
        },
        'start_slot': {  # TOPMOST occupied U (a mount grows downward); null for sides / unassigned
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        'height': {  # Occupied U count; required for a main area, kept as a hint when unplaced
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        'position': {  # Order index inside a side list or the unassigned bucket; null in a main area
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        'author_id': {  # public_id of the CmdbUser who created the mount
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        'creation_time': {  # When the mount was created
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        'last_edit_time': {  # When the mount was last changed
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
    }
