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
The schema of a CmdbUserGroup
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_user_group_schema() -> dict[str, Any]:
    """
    Returns the CmdbUserGroupSchema

    Returns:
        dict: Schema of the CmdbUserGroup
    """
    return {
        'public_id': {  # public_id of the CmdbUserGroup
            'type': 'integer',
            'required': False,
        },
        'name': {  # Unique name of the user group
            'type': 'string',
            'required': True,
        },
        'label': {  # Displayed label of the user group
            'type': 'string',
            'required': False,
        },
        'rights': {  # Right identifiers granted to members of this group
            'type': 'list',
            'required': False,
            'default': [],
        },
    }
