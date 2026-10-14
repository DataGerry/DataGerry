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
Validation schema for CmdbReport

A CmdbReport is a saved query over a CmdbType with selected fields and filter conditions
(collection ``framework.reports``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbReport.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
def get_cmdb_report_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbReport document

    The keys come from ``ReportKey`` - also the model's ``KEYS``, which the shared ``from_data`` / ``to_json`` read and
    write - so the schema and the document cannot drift apart. The import is deliberately INSIDE the builder:
    ``cmdb.models`` imports this module at class-definition time, so importing the model package at module level would
    close an import cycle

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbReport.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.reports_model.report_constants import ReportKey

    return {
        ReportKey.PUBLIC_ID.value: {  # public_id of the CmdbReport
            'type': 'integer',
        },
        ReportKey.REPORT_CATEGORY_ID.value: {  # public_id of the CmdbReportCategory this report belongs to
            'type': 'integer',
            'required': True,
        },
        ReportKey.NAME.value: {  # Name of the report
            'type': 'string',
            'required': True,
        },
        ReportKey.TYPE_ID.value: {  # public_id of the CmdbType the report runs against
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        ReportKey.SELECTED_FIELDS.value: {  # Type field names included in the report output
            'type': 'list',
            'required': True,
        },
        ReportKey.CONDITIONS.value: {  # Filter conditions defining which objects are included
            'type': 'dict',
        },
        ReportKey.REPORT_QUERY.value: {  # Compiled MongoDB query derived from the conditions
            'type': 'dict',
        },
        ReportKey.PREDEFINED.value: {  # True if provided by DataGerry rather than user-created
            'type': 'boolean',
            'default': False,
        },
        ReportKey.MDS_MODE.value: {  # Multi-data-section render mode (an MdsMode value)
            'type': 'string',
        },
    }
