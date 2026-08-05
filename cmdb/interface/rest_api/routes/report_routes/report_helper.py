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
Helper methods for the CmdbReport API routes

Request-payload validation / normalisation, the Ref-Section-Field guard, the report-type lookup,
the report-query builder and the safe evaluation of a stored report query, shared by the report
Create / Update / Run routes. Validation helpers abort with HTTP 400 so the routes stay focused on
orchestration.
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from flask import abort

from cmdb.database import MongoDBQueryBuilder
from cmdb.manager import ReportsManager

from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.reports_model.report_constants import ReportConditionKey
from cmdb.utils.helpers import str_to_bool

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    ReportKey,
    ReportQueryKey,
    REPORT_REQUIRED_PARAMS,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Locked-down namespace for evaluating a stored report query: only 'datetime' is exposed and
# builtins are removed, so the evaluation cannot reach arbitrary imports / builtins
_EVAL_GLOBALS: dict[str, Any] = {'datetime': datetime, '__builtins__': {}}


def normalize_report_params(params: dict[str, Any]) -> None:
    """
    Validates the required report parameters and normalises their types in place

    Aborts 400 when a required parameter is missing, or when a value is malformed (a non-integer
    id, a non-boolean 'predefined', or 'conditions' / 'selected_fields' that are not valid JSON) -
    so a bad request surfaces as 400 instead of crashing into an internal 500. An unrecognised
    'mds_mode' falls back to MdsMode.ROWS

    Args:
        params (dict[str, Any]): The parsed request parameters (mutated in place)

    Raises:
        HTTPException: 400 when a required parameter is missing or a value is malformed
    """
    missing: list[str] = [key for key in REPORT_REQUIRED_PARAMS if key not in params]

    if missing:
        abort(400, f"Missing required Report parameter(s): {', '.join(missing)}!")

    try:
        params[ReportKey.REPORT_CATEGORY_ID] = int(params[ReportKey.REPORT_CATEGORY_ID])
        params[ReportKey.TYPE_ID] = int(params[ReportKey.TYPE_ID])
        params[ReportKey.PREDEFINED] = str_to_bool(params[ReportKey.PREDEFINED])
        # The frontend JSON-encodes both, so a single parser keeps them consistent
        params[ReportKey.CONDITIONS] = json.loads(params[ReportKey.CONDITIONS])
        params[ReportKey.SELECTED_FIELDS] = json.loads(params[ReportKey.SELECTED_FIELDS])
    except (ValueError, TypeError) as err:
        LOGGER.error("[normalize_report_params] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(400, "One or more Report parameters are malformed!")

    params[ReportKey.MDS_MODE] = (
        params[ReportKey.MDS_MODE]
        if params[ReportKey.MDS_MODE] in (MdsMode.ROWS, MdsMode.COLUMNS)
        else MdsMode.ROWS
    )


def resolve_report_type(reports_manager: ReportsManager, type_id: int) -> CmdbType:
    """
    Loads the report's CmdbType, aborting 400 when the type_id does not resolve

    Args:
        reports_manager (ReportsManager): db interface used to read the CmdbType collection
        type_id (int): public_id of the report's CmdbType

    Raises:
        HTTPException: 400 when no CmdbType with that public_id exists

    Returns:
        CmdbType: The resolved CmdbType
    """
    report_type: dict[str, Any] | None = reports_manager.get_one_from_other_collection(CmdbType.COLLECTION, type_id)

    if not report_type:
        abort(400, f"The Report's Type with ID:{type_id} was not found!")

    return CmdbType.from_data(report_type)


def collect_condition_field_names(conditions: dict[str, Any] | None) -> set[str]:
    """
    Recursively collects every field name referenced by a report's conditions rule tree

    A conditions node is a group ``{'condition': ..., 'rules': [...]}`` whose rules are either
    nested groups (carrying their own 'condition') or leaf rules carrying a 'field' name

    Args:
        conditions (dict[str, Any] | None): The report's conditions structure (or None)

    Returns:
        set[str]: Every field name referenced by a leaf rule, at any nesting depth
    """
    field_names: set[str] = set()

    if not conditions:
        return field_names

    for a_rule in conditions.get(ReportConditionKey.RULES, []):
        if ReportConditionKey.CONDITION in a_rule:
            field_names |= collect_condition_field_names(a_rule)
        elif ReportConditionKey.FIELD in a_rule:
            field_names.add(a_rule[ReportConditionKey.FIELD])

    return field_names


def abort_if_ref_section_fields(
    report_type: CmdbType,
    selected_fields: list[str],
    conditions: dict[str, Any] | None,
) -> None:
    """
    Rejects a report that references a Ref-Section-Field of its CmdbType

    Ref-Section-Fields are not supported in Reports. This is the early-out guard for the Create /
    Update routes: it aborts with HTTP 400 before any query is built or the document is written when
    a 'ref-section-field' of the report's CmdbType appears either among the selected columns or in a
    condition (filter) rule at any nesting depth

    Args:
        report_type (CmdbType): The report's CmdbType
        selected_fields (list[str]): The field names selected for the report
        conditions (dict[str, Any] | None): The report's conditions (filter) rule tree

    Raises:
        HTTPException: 400 when a selected column or a condition rule references a Ref-Section-Field
    """
    ref_section_field_names: set[str] = set(report_type.get_all_fields_of_type(FieldType.REF_SECTION))
    referenced: set[str] = set(selected_fields) | collect_condition_field_names(conditions)
    offending: list[str] = sorted(referenced & ref_section_field_names)

    if offending:
        abort(400, f"Ref-Section-Fields are not allowed in Reports: {', '.join(offending)}!")


def build_report_query(conditions: dict[str, Any] | None, report_type: CmdbType) -> dict[str, str]:
    """
    Builds a report's persisted ``report_query`` from its conditions

    Args:
        conditions (dict[str, Any] | None): The report's conditions rule tree
        report_type (CmdbType): The report's CmdbType (drives field resolution in the query builder)

    Returns:
        dict[str, str]: ``{'data': <serialized Mongo query>}``
    """
    return {ReportQueryKey.DATA: str(MongoDBQueryBuilder(conditions, report_type).build())}


def eval_report_query(query_str: str) -> dict[str, Any]:
    """
    Safely evaluates a stored report query string back into a Mongo query dict

    A report's query is persisted as the repr of a Python dict - ``datetime.datetime(...)`` calls and
    all (see build_report_query). That stored shape is deliberately kept; reconstruction normalises
    the ``datetime.datetime`` calls to ``datetime`` and evaluates the string in a locked-down
    namespace exposing only ``datetime`` with an empty ``__builtins__``, so the evaluation cannot
    reach arbitrary builtins / imports - mitigating the code-execution risk of eval'ing a stored
    string. Because the namespace already binds ``datetime``, the normalised string evaluates
    directly: no regex pre-processing of the datetime calls is required

    Args:
        query_str (str): The stored report query string

    Returns:
        dict[str, Any]: The reconstructed Mongo query
    """
    # pylint: disable=eval-used
    return eval(query_str.replace('datetime.datetime', 'datetime'), _EVAL_GLOBALS)
