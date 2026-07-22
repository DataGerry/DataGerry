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
Constants for the CmdbReport REST routes

Names the report request-body / document keys and the stored report_query sub-key the routes read,
plus the route-local query-string parameters, so the routes reference the literal strings from one
place. The condition rule-tree keys and query operators are
shared with the database layer and live in cmdb.models.reports_model.report_constants
(ReportConditionKey / ReportConditionLogic / ReportQueryOperator). The shared 'public_id' key is
covered by CmdbObjectKey.PUBLIC_ID (the project-wide precedent for identity keys).
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ReportKey(BaseStrEnum):
    """
    Request-body / document keys of a CmdbReport

    Use these members instead of bare string literals when reading the report request payload or
    building a report document so a typo becomes an AttributeError instead of a silently missing key
    """
    REPORT_CATEGORY_ID = 'report_category_id'
    NAME = 'name'
    TYPE_ID = 'type_id'
    SELECTED_FIELDS = 'selected_fields'
    CONDITIONS = 'conditions'
    REPORT_QUERY = 'report_query'
    PREDEFINED = 'predefined'
    MDS_MODE = 'mds_mode'


class ReportQueryKey(BaseStrEnum):
    """
    Keys of a CmdbReport's stored 'report_query'

    DATA holds the serialized Mongo query string rebuilt from the report's conditions
    """
    DATA = 'data'


# The required input parameters a report Create / Update request must carry (report_query is built
# server-side, so it is not an input parameter)
REPORT_REQUIRED_PARAMS: list[str] = [
    ReportKey.REPORT_CATEGORY_ID,
    ReportKey.NAME,
    ReportKey.TYPE_ID,
    ReportKey.SELECTED_FIELDS,
    ReportKey.CONDITIONS,
    ReportKey.PREDEFINED,
    ReportKey.MDS_MODE,
]

# Query-string parameter that, when true, runs a report in capped 'preview' mode
PREVIEW_PARAM: str = 'preview'

# Maximum number of result rows returned when a report is run in preview mode (capped DB-side)
PREVIEW_LIMIT: int = 2
