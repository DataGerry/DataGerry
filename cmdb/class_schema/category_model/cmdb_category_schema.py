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
The schema of a CmdbCategory
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_category_schema() -> dict[str, Any]:
    """
    Returns the CmdbCategorySchema

    Returns:
        dict: Schema of the CmdbCategory
    """
    return {
        'public_id': { # public_id of the CmdbCategory
            'type': 'integer'
        },
        'name': { # Unique name of the CmdbCategory
            'type': 'string',
            'required': True,
            'empty': False,
            'regex': r'(\w+)-*(\w)([\w-]*)'  # kebab case validation,
        },
        'label': { # Label of the CmdbCategory (visible to users)
            'type': 'string',
            'required': False
        },
        'parent': { # public_id of the parent CmdbCategory if any
            'type': 'integer',
            'nullable': True,
            'default': None
        },
        'types': { # public_ids of assigned CmdbTypes to this CmdbCategory
            'type': 'list',
            'default': []
        },
        'meta': { # Additional information about the CmdbCategory
            'type': 'dict',
            'schema': {
                'icon': { # The icon assigned to this CmdbCategory
                    'type': 'string',
                    'empty': True
                },
                'order': { # The order of this CmdbCategory
                    'type': 'integer',
                    'nullable': True
                }
            },
            'default': { # Default values
                'icon': '',
                'order': None,
            }
        }
    }
