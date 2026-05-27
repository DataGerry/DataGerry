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
The schema of a CmdbReport
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_report_schema() -> dict[str, Any]:
    """
    Returns the CmdbReportSchema

    Returns:
        dict: Schema of the CmdbReport
    """
    return {
        'public_id': {  # public_id of the CmdbReport
            'type': 'integer',
        },
        'report_category_id': {  # public_id of the CmdbReportCategory this report belongs to
            'type': 'integer',
            'required': True,
        },
        'name': {  # Name of the report
            'type': 'string',
            'required': True,
        },
        'type_id': {  # public_id of the CmdbType the report runs against
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'selected_fields': {  # Type field names included in the report output
            'type': 'list',
            'required': True,
        },
        'conditions': {  # Filter conditions defining which objects are included
            'type': 'dict',
        },
        'report_query': {  # Compiled MongoDB query derived from the conditions
            'type': 'dict',
        },
        'predefined': {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'default': False,
        },
        'mds_mode': {  # Multi-data-section render mode (an MdsMode value)
            'type': 'string',
        },
    }
