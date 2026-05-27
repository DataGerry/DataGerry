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
The schema of a CmdbObjectGroup
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_object_group_schema() -> dict[str, Any]:
    """
    Returns the CmdbObjectGroupSchema

    Returns:
        dict: Schema of the CmdbObjectGroup
    """
    return {
        'public_id': {  # public_id of the CmdbObjectGroup
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the object group
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'group_type': {  # STATIC or DYNAMIC membership mode (an ObjectGroupMode value)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'assigned_ids': {  # STATIC: explicit member public_ids; DYNAMIC: the matching category ids
            'type': 'list',
            'required': True,
            'empty': False,
        },
        'categories': {  # public_ids of the CmdbCategories associated with this group
            'type': 'list',
        },
    }
