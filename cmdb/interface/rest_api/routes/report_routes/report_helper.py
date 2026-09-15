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

Holds what the Create / Read / Update / Run / Delete routes share:

* request-payload sanitising and normalisation - the write whitelist (a client may set only the six
  required parameters; 'public_id' comes from the URL, 'predefined' is system-owned and
  'report_query' is built server-side), the required-parameter check and the type coercions
* the load-or-404 lookup and the two foreign-key guards (the report's CmdbType and its
  CmdbReportCategory must exist)
* the Ref-Section-Field guard, the report-query builder and the safe evaluation of a stored query
* the two write-payload builders the Create / Update routes hand to the manager

Validation helpers abort with HTTP 400 (404 for a missing report, 500 for an unusable stored query)
so the routes stay focused on orchestration.
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from flask import abort

from cmdb.database import MongoDBQueryBuilder
from cmdb.manager import ReportsManager

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.reports_model.report_constants import ReportConditionKey, ReportQueryKey
from cmdb.utils import str_to_bool

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    BOOLEAN_PARAM_INVALID_MSG,
    REPORT_CATEGORY_MISSING_MSG,
    REPORT_NOT_FOUND_MSG,
    REPORT_QUERY_CORRUPT_MSG,
    REPORT_REQUIRED_PARAMS,
    REPORT_TYPE_MISSING_MSG,
    REPORT_WRITE_KEYS,
    ReportKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Locked-down namespace for evaluating a stored report query: only 'datetime' is exposed and
# builtins are removed, so the evaluation cannot reach arbitrary imports / builtins
_EVAL_GLOBALS: dict[str, Any] = {'datetime': datetime, '__builtins__': {}}


def strip_unknown_report_keys(params: dict[str, Any]) -> dict[str, Any]:
    """
    Keeps only the client-settable keys of a report write payload

    Everything outside REPORT_WRITE_KEYS is dropped instead of rejected, mirroring the 'purge_unknown'
    behaviour of the Cerberus-validated write routes: the request parameters are read straight off the
    query string, so an unknown parameter would otherwise be persisted verbatim as a document key. The
    server-owned keys are dropped here too and re-applied by the payload builders

    Args:
        params (dict[str, Any]): The raw request parameters

    Returns:
        dict[str, Any]: A new dict holding only the whitelisted keys
    """
    return {key: value for key, value in params.items() if key in REPORT_WRITE_KEYS}


def normalize_report_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the sanitised, type-normalised write payload of a report Create / Update request

    Drops every key a client may not set, then aborts 400 when a required parameter is missing or when
    a value is malformed (a non-integer id, or 'conditions' / 'selected_fields' that are not valid
    JSON) - so a bad request surfaces as 400 instead of crashing into an internal 500. An unrecognised
    'mds_mode' falls back to MdsMode.ROWS

    Args:
        params (dict[str, Any]): The raw request parameters (left untouched)

    Raises:
        HTTPException: 400 when a required parameter is missing or a value is malformed

    Returns:
        dict[str, Any]: The normalised payload, holding the whitelisted keys only
    """
    payload: dict[str, Any] = strip_unknown_report_keys(params)

    missing: list[str] = [key for key in REPORT_REQUIRED_PARAMS if key not in payload]

    if missing:
        abort(400, f"Missing required Report parameter(s): {', '.join(missing)}!")

    try:
        payload[ReportKey.REPORT_CATEGORY_ID] = int(payload[ReportKey.REPORT_CATEGORY_ID])
        payload[ReportKey.TYPE_ID] = int(payload[ReportKey.TYPE_ID])
        # The frontend JSON-encodes both, so a single parser keeps them consistent
        payload[ReportKey.CONDITIONS] = json.loads(payload[ReportKey.CONDITIONS])
        payload[ReportKey.SELECTED_FIELDS] = json.loads(payload[ReportKey.SELECTED_FIELDS])
    except (ValueError, TypeError) as err:
        LOGGER.error("[normalize_report_params] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(400, "One or more Report parameters are malformed!")

    payload[ReportKey.MDS_MODE] = (
        payload[ReportKey.MDS_MODE]
        if payload[ReportKey.MDS_MODE] in (MdsMode.ROWS, MdsMode.COLUMNS)
        else MdsMode.ROWS
    )

    return payload


def parse_boolean_param(raw_value: Any, param_name: str) -> bool:
    """
    Coerces a query-string flag into a bool, aborting 400 on anything unrecognised

    ``str_to_bool`` raises ValueError for values other than 'true' / 'false', which inside a route's
    try-block would surface as an internal 500 - a malformed query parameter is a bad request

    Args:
        raw_value (Any): The raw query-string value
        param_name (str): Name of the parameter, used in the error message

    Raises:
        HTTPException: 400 when the value is neither 'true' nor 'false'

    Returns:
        bool: The parsed flag
    """
    try:
        return str_to_bool(raw_value)
    except ValueError:
        abort(400, BOOLEAN_PARAM_INVALID_MSG.format(param=param_name))


def load_report_or_404(reports_manager: ReportsManager, public_id: int) -> dict[str, Any]:
    """
    Retrieves a CmdbReport document by its public_id, aborting when it does not exist

    Always returns the raw document (no model is built): every caller either echoes it, reads a single
    key off it or only needs the existence check

    Args:
        reports_manager (ReportsManager): Manager used for the lookup
        public_id (int): public_id of the requested CmdbReport

    Raises:
        ReportsManagerGetError: If the lookup itself fails
        HTTPException: 404 when no CmdbReport carries the given public_id

    Returns:
        dict[str, Any]: The stored CmdbReport document
    """
    requested_report: dict[str, Any] | None = reports_manager.get_item(public_id, as_dict=True)

    if not requested_report:
        abort(404, REPORT_NOT_FOUND_MSG.format(public_id=public_id))

    return requested_report


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
        abort(400, REPORT_TYPE_MISSING_MSG.format(type_id=type_id))

    return CmdbType.from_data(report_type)


def abort_if_report_category_missing(reports_manager: ReportsManager, report_category_id: int) -> None:
    """
    Rejects a report whose CmdbReportCategory does not exist

    The category is the report's other foreign key (next to its CmdbType) and the reporting UI groups
    by it, so a report pointing at a deleted / never-existing category would never surface. Only the
    existence is checked - no category document is built

    Args:
        reports_manager (ReportsManager): db interface used to read the report-category collection
        report_category_id (int): public_id of the report's CmdbReportCategory

    Raises:
        HTTPException: 400 when no CmdbReportCategory with that public_id exists
    """
    report_category: dict[str, Any] | None = reports_manager.get_one_from_other_collection(
                                                                                    CmdbReportCategory.COLLECTION,
                                                                                    report_category_id)

    if not report_category:
        abort(400, REPORT_CATEGORY_MISSING_MSG.format(report_category_id=report_category_id))


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


def resolve_report_query(report: dict[str, Any], public_id: int) -> dict[str, Any]:
    """
    Returns a stored report's executable Mongo query

    A report written through the Create / Update routes always carries a ``report_query``, but a
    document that was imported or inserted directly may not - that is answered with an empty query
    (the same result as a report without conditions) instead of a KeyError surfacing as a 500. A query
    that IS stored but cannot be evaluated is a corrupted document, so it aborts with a message that
    names the report instead of a bare internal error

    Args:
        report (dict[str, Any]): The stored CmdbReport document
        public_id (int): public_id of the report, used in the error message

    Raises:
        HTTPException: 500 when the stored query string cannot be evaluated

    Returns:
        dict[str, Any]: The reconstructed Mongo query, or an empty dict when the report stores none
    """
    stored_query: Any = report.get(ReportKey.REPORT_QUERY)
    query_str: Any = stored_query.get(ReportQueryKey.DATA) if isinstance(stored_query, dict) else None

    if not isinstance(query_str, str) or not query_str.strip():
        return {}

    try:
        return eval_report_query(query_str)
    except Exception as err:
        LOGGER.error("[resolve_report_query] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, REPORT_QUERY_CORRUPT_MSG.format(public_id=public_id))


def build_report_payload(reports_manager: ReportsManager, params: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the validated report document a Create / Update writes, minus the identity

    The shared write chain of both routes: sanitise and normalise the request parameters, verify both
    foreign keys (the CmdbReportCategory and the CmdbType), reject any referenced Ref-Section-Field and
    build the persisted report query - all before anything is written

    Args:
        reports_manager (ReportsManager): Manager used for the foreign-key lookups
        params (dict[str, Any]): The raw request parameters

    Raises:
        HTTPException: 400 on a missing / malformed parameter, an unresolved category or type, or a
                       referenced Ref-Section-Field

    Returns:
        dict[str, Any]: The payload to persist, without 'public_id' and 'predefined'
    """
    payload: dict[str, Any] = normalize_report_params(params)

    abort_if_report_category_missing(reports_manager, payload[ReportKey.REPORT_CATEGORY_ID])

    report_type: CmdbType = resolve_report_type(reports_manager, payload[ReportKey.TYPE_ID])

    # Ref-Section-Fields are not allowed in Reports - early out before building the query / writing
    abort_if_ref_section_fields(report_type, payload[ReportKey.SELECTED_FIELDS], payload[ReportKey.CONDITIONS])

    payload[ReportKey.REPORT_QUERY] = build_report_query(payload[ReportKey.CONDITIONS], report_type)

    return payload


def build_report_create_payload(reports_manager: ReportsManager, params: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the document a report Create writes

    'predefined' is forced to False: it marks a report as provided by DataGerry, so a client can never
    create one. The public_id is assigned by the insert

    Args:
        reports_manager (ReportsManager): Manager used for the foreign-key lookups
        params (dict[str, Any]): The raw request parameters

    Raises:
        HTTPException: 400 on a missing / malformed parameter, an unresolved category or type, or a
                       referenced Ref-Section-Field

    Returns:
        dict[str, Any]: The full document to insert
    """
    payload: dict[str, Any] = build_report_payload(reports_manager, params)
    payload[ReportKey.PREDEFINED] = False

    return payload


def build_report_update_payload(
        reports_manager: ReportsManager,
        params: dict[str, Any],
        public_id: int,
        current_report: dict[str, Any],
    ) -> dict[str, Any]:
    """
    Builds the document a report Update writes for an existing CmdbReport

    Pins the two server-owned keys: the identity is taken from the URL (never from the payload, which
    would silently rewrite the document's identity) and 'predefined' is carried over from the stored
    report

    Args:
        reports_manager (ReportsManager): Manager used for the foreign-key lookups
        params (dict[str, Any]): The raw request parameters
        public_id (int): public_id of the CmdbReport being updated, taken from the URL
        current_report (dict[str, Any]): The stored CmdbReport document being updated

    Raises:
        HTTPException: 400 on a missing / malformed parameter, an unresolved category or type, or a
                       referenced Ref-Section-Field

    Returns:
        dict[str, Any]: The full document to persist
    """
    payload: dict[str, Any] = build_report_payload(reports_manager, params)
    payload[CmdbObjectKey.PUBLIC_ID] = public_id
    payload[ReportKey.PREDEFINED] = current_report.get(ReportKey.PREDEFINED, False)

    return payload
