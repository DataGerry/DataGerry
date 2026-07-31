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
Constants for the CmdbReport and CmdbReportCategory REST routes

Names the report request-body / document keys and the stored report_query sub-key the routes read,
plus the route-local query-string parameters, so the routes reference the literal strings from one
place. The condition rule-tree keys and query operators are
shared with the database layer and live in cmdb.models.reports_model.report_constants
(ReportConditionKey / ReportConditionLogic / ReportQueryOperator). The shared 'public_id' key is
covered by CmdbObjectKey.PUBLIC_ID (the project-wide precedent for identity keys).

The CmdbReportCategory section adds that entity's document keys, the write whitelist its routes
sanitise a request payload against, the verbs naming a refused write on a predefined category, and
the abort messages the category routes / their helper repeat.
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


# The input parameters a report Create / Update request must carry, in the order they are named in the
# 'missing parameter' message. The three keys NOT listed here are the server-owned ones: 'public_id'
# comes from the URL, 'predefined' is set by the system and 'report_query' is built from 'conditions'
REPORT_REQUIRED_PARAMS: list[str] = [
    ReportKey.REPORT_CATEGORY_ID,
    ReportKey.NAME,
    ReportKey.TYPE_ID,
    ReportKey.SELECTED_FIELDS,
    ReportKey.CONDITIONS,
    ReportKey.MDS_MODE,
]

# The keys a client may set on a report Create / Update request. Every required parameter is writable
# and every writable key is required, so the two are kept in sync by construction; anything else in the
# request is dropped instead of being persisted as a document key
REPORT_WRITE_KEYS: frozenset[str] = frozenset(REPORT_REQUIRED_PARAMS)

# Query-string parameter that, when true, runs a report in capped 'preview' mode
PREVIEW_PARAM: str = 'preview'

# Maximum number of result rows returned when a report is run in preview mode (capped DB-side)
PREVIEW_LIMIT: int = 2

# Abort messages the report routes and their helper repeat. The named placeholders are filled by the
# caller
REPORT_NOT_FOUND_MSG: str = "The Report with ID:{public_id} was not found!"
REPORT_RETRIEVE_FAILED_MSG: str = "Failed to retrieve the Report with ID: {public_id} from the database!"
REPORT_TYPE_MISSING_MSG: str = "The Report's Type with ID:{type_id} was not found!"
REPORT_CATEGORY_MISSING_MSG: str = "The Report's Category with ID:{report_category_id} was not found!"
REPORT_QUERY_CORRUPT_MSG: str = (
    "The stored query of the Report with ID: {public_id} could not be evaluated!"
)
BOOLEAN_PARAM_INVALID_MSG: str = "The '{param}' parameter must be 'true' or 'false'!"

# ------------------------------------------ CmdbReportCategory - CONSTANTS ------------------------------------------ #


class ReportCategoryKey(BaseStrEnum):
    """
    Document keys of a CmdbReportCategory

    Use these members instead of bare string literals when reading a report-category request payload
    or building a report-category document so a typo becomes an AttributeError instead of a silently
    missing key. The identity key is not here - it is CmdbObjectKey.PUBLIC_ID
    """
    NAME = 'name'
    PREDEFINED = 'predefined'


class ReportCategoryAction(BaseStrEnum):
    """
    Past-tense verbs naming the write operation refused on a predefined CmdbReportCategory

    Filled into CATEGORY_PREDEFINED_MSG so the update and delete guards share one message template
    """
    UPDATED = 'updated'
    DELETED = 'deleted'


# The only keys a client may set on a CmdbReportCategory create / update request. 'public_id' comes
# from the URL and 'predefined' is system-owned, so both are dropped from the payload and re-applied
# by the route; anything else is not part of the document
REPORT_CATEGORY_WRITE_KEYS: frozenset[str] = frozenset({ReportCategoryKey.NAME})

# Abort messages the report-category routes and their helper repeat. '{public_id}' / '{action}' are
# filled in by the caller
CATEGORY_NOT_FOUND_MSG: str = "The ReportCategory with ID:{public_id} was not found!"
CATEGORY_RETRIEVE_FAILED_MSG: str = (
    "Failed to retrieve the ReportCategory with ID: {public_id} from the database!"
)
CATEGORY_NAME_REQUIRED_MSG: str = "A ReportCategory requires a non-empty 'name'!"
CATEGORY_PREDEFINED_MSG: str = "A predefined ReportCategory can not be {action}!"
CATEGORY_IN_USE_MSG: str = "ReportCategory with ID: {public_id} can not be deleted because it is used by Reports!"
