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
Validation schema for CmdbReportCategory

A CmdbReportCategory groups CmdbReports (collection ``framework.reportCategories``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbReportCategory.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_report_category_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbReportCategory document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbReportCategory.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbReportCategory
            'type': 'integer',
        },
        'name': {  # Name of the report category
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'predefined': {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'default': False,
        },
    }
