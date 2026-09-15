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
Validation schema for CmdbObjectGroup

A CmdbObjectGroup is a static or dynamic grouping of CmdbObjects
(collection ``framework.objectGroups``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbObjectGroup.SCHEMA.

``group_type`` is constrained to the ``ObjectGroupMode`` members, and that is not cosmetic: both
cleanup paths select the groups they maintain by mode (``objects_helper`` pulls deleted objects out of
the STATIC ones, ``types_helper`` pulls a deleted type out of the DYNAMIC ones), so a group stored with
any third value is reachable by neither and keeps dead ids for the rest of its life

``assigned_ids`` is required and must not be empty - a group of nothing has no meaning here - so it is
the one list key that is not nullable
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_object_group_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbObjectGroup document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbObjectGroup.SCHEMA
    """
    # Imported inside the builder: both live in the model layer, which imports this module
    # pylint: disable=import-outside-toplevel
    from cmdb.models.object_group_model.object_group_constants import ObjectGroupKey
    from cmdb.models.object_group_model.object_group_mode_enum import ObjectGroupMode

    return {
        ObjectGroupKey.PUBLIC_ID.value: {  # public_id of the CmdbObjectGroup
            'type': 'integer',
            'min': 1,
        },
        ObjectGroupKey.NAME.value: {  # Name of the object group
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ObjectGroupKey.GROUP_TYPE.value: {  # STATIC or DYNAMIC membership mode
            'type': 'string',
            'required': True,
            'empty': False,
            'allowed': [mode.value for mode in ObjectGroupMode],
        },
        ObjectGroupKey.ASSIGNED_IDS.value: {  # STATIC: member CmdbObject ids; DYNAMIC: CmdbType ids
            'type': 'list',
            'required': True,
            'empty': False,
        },
        ObjectGroupKey.CATEGORIES.value: {  # public_ids of the OBJECT_GROUP CmdbExtendableOptions
            'type': 'list',
            'nullable': True,
        },
    }
