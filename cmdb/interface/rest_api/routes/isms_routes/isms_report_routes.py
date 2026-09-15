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
Implementation of all API routes for Isms Reports
"""
from logging import Logger, getLogger
import re
from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsProtectionGoal,
    IsmsRisk,
)
from cmdb.framework.isms import RiskMatrixReportBuilder
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.models.extendable_option_model import OptionType, CmdbExtendableOption
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    build_ra_report_search_stage,
    build_report_facet_stage,
    build_report_filter_stages,
    extract_report_page,
    object_reference_lookup_stages,
    paginate_report_rows,
    risk_assessment_report_projection_stage,
    risk_calculation_projection_fields,
    risk_assessment_report_stages,
    risk_matrix_class_lookup_stages,
)

from cmdb.errors.framework_isms import RiskMatrixReportError
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerIterationError
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# SOA rows are ordered by the fixed business rules (sort_key), so the report ignores sort/order/filter.
# These neutral values are echoed back in the response metadata instead of a client's ignored request.
SOA_FIXED_ORDER_SORT: str = 'public_id'
SOA_FIXED_ORDER_DIRECTION: int = 1

# The source whose controls the SOA lists first, matched against the RESOLVED source label
SOA_PRIMARY_SOURCE: str = 'ISO 27001:2022'

# Shown in place of an assessed object whose CmdbObject no longer resolves. The row is kept rather
# than dropped: a risk assessment naming a deleted object is exactly what a reader needs to see
UNKNOWN_OBJECT_LABEL: str = 'Unknown object'

isms_report_blueprint = APIBlueprint('isms_report', __name__)


def _replace_object_ids_with_summaries(items: list[dict], object_key: str, objects_manager: ObjectsManager) -> None:
    """
    Replaces each report item's OBJECT-referenced public_id (under ``object_key``) with the object's
    summary line, resolved in a single batch rather than one lookup per item.

    Only items whose ``object_id_ref_type`` is OBJECT are touched; an id with no resolvable object
    becomes 'Unknown object'.

    Args:
        items (list[dict]): The aggregated report rows to enrich in place
        object_key (str): The key holding the object public_id to replace
        objects_manager (ObjectsManager): Manager used to resolve the summary lines
    """
    target_items = [
        item for item in items
        if item.get(object_key) and item.get('object_id_ref_type') == ObjectReferenceType.OBJECT
    ]

    if not target_items:
        return

    summaries = objects_manager.get_summary_lines_lookup(
        [item[object_key] for item in target_items], with_type=False
    )

    for item in target_items:
        item[object_key] = summaries.get(item[object_key], UNKNOWN_OBJECT_LABEL)

# ----------------------------------------------------- REPORTS ------------------------------------------------------ #

@isms_report_blueprint.route('/risk_matrix', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
def get_isms_risk_matrix_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the IsmsRiskMatrix report

    The body carries the grid counted three ways - `risk_matrix_before_treatment`,
    `risk_matrix_current_state`, `risk_matrix_after_treatment` - plus `configured`, which is False
    while the ISMS config wizard has not produced the risk matrix yet. Before 2026-09-09 that state
    was indistinguishable from a configured matrix nothing had been assessed against

    Args:
        request_user (CmdbUser): CmdbUser requesting the RiskMatrix report

    Raises:
        HTTPException: 400 when the report could not be built from the stored data, 500 on an
                       unexpected error

    Returns:
        DefaultResponse: The RiskMatrix report as a dictionary
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)
        risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(
                                                                    ManagerType.RISK_MATRIX,
                                                                    request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
                                                                                ManagerType.EXTENDABLE_OPTIONS,
                                                                                request_user)

        report_builder = RiskMatrixReportBuilder(
            risk_assessment_manager,
            risk_matrix_manager,
            extendable_options_manager
        )

        risk_matrix_report = report_builder.build_risk_matrix_report()

        return DefaultResponse(risk_matrix_report).make_response()
    except HTTPException as http_err:
        raise http_err
    except RiskMatrixReportError as err:
        LOGGER.error("[get_isms_risk_matrix_report] RiskMatrixReportError: %s", err, exc_info=True)
        abort(400, "Failed to build the RiskMatrix report from the stored ISMS configuration!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_matrix_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the RiskMatrix report!")


@isms_report_blueprint.route('/risk_treatment_plan', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
def get_isms_risk_treatment_plan_report(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the Risk Treatment Plan report

    The report is paginated: ``limit``/``page``/``sort``/``order``/``filter`` are read from the query
    string (see CollectionParameters) and the response is wrapped in a GetMultiResponse envelope.

    **``sort`` and ``filter`` both address the report's RESOLVED display fields** - ``risk_name``,
    ``risk_category``, ``implementation_status`` and the rest of the ``$project`` below - not the raw
    IsmsRiskAssessment document. That is why the filter stages are appended after the projection: the
    pagination ``$sort`` runs inside the facet stage, i.e. after it too, and the two must not address
    different field sets. ``filter`` accepts a MongoDB query dict or a list of pipeline stages, as
    everywhere else in the backend.

    Note this report calls the risk's name ``risk_name`` while the RiskAssessment report calls the same
    value ``risk_title``. Both are frontend-visible contract, so the difference is recorded rather than
    resolved here.

    Args:
        params (CollectionParameters): Pagination, sort and filter parameters for the report
        request_user (CmdbUser): CmdbUser requesting the Risk Treatment Plan report

    Returns:
        GetMultiResponse: The paginated Risk Treatment Plan report
    """
    try:
        body: bool = request_wants_body()

        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        query_pipeline = [
            # Step 0: Start from all IsmsRiskAssessments. The column filters target this report's
            # RESOLVED display fields (risk_name, risk_category, implementation_status, ...), which do
            # not exist yet on the raw document - and the pagination $sort inside the facet stage runs
            # after the $project too, so filtering here would have addressed a different field set than
            # sorting did. params.filter is applied after the $project below, as on the sibling report.
            {"$match": {}},
            # Step 1: Lookup associated Risk
            {
                "$lookup": {
                    "from": IsmsRisk.COLLECTION,
                    "localField": "risk_id",
                    "foreignField": "public_id",
                    "as": "risk"
                }
            },
            {"$unwind": {"path": "$risk", "preserveNullAndEmptyArrays": True}},

            # Step 2: Lookup implementation status (ExtendableOption)
            {
                "$lookup": {
                    "from": CmdbExtendableOption.COLLECTION,
                    "localField": "implementation_status",
                    "foreignField": "public_id",
                    "as": "implementation_status"
                }
            },
            {"$unwind": {"path": "$implementation_status", "preserveNullAndEmptyArrays": True}},

            # Step 3: Lookup risk category label (ExtendableOption)
            {
                "$lookup": {
                    "from": CmdbExtendableOption.COLLECTION,
                    "localField": "risk.category_id",
                    "foreignField": "public_id",
                    "as": "risk_category"
                }
            },
            {"$unwind": {"path": "$risk_category", "preserveNullAndEmptyArrays": True}},

            # Lookup protection goals by IDs in risk.protection_goals
            {
                "$lookup": {
                    "from": IsmsProtectionGoal.COLLECTION,
                    "localField": "risk.protection_goals",
                    "foreignField": "public_id",
                    "as": "protection_goals"
                }
            },

            # Lookup Object / ObjectGroup / type label for the assessed object
            *object_reference_lookup_stages(),

            # Step 6: Lookup person/personGroup
            {
                "$lookup": {
                    "from": CmdbPerson.COLLECTION,
                    "localField": "responsible_persons_id",
                    "foreignField": "public_id",
                    "as": "responsible_person"
                }
            },
            {
                "$lookup": {
                    "from": CmdbPersonGroup.COLLECTION,
                    "localField": "responsible_persons_id",
                    "foreignField": "public_id",
                    "as": "responsible_person_group"
                }
            },

            # Resolve each risk_calculation matrix cell + its risk class (before and after treatment)
            *risk_matrix_class_lookup_stages("risk_calculation_before", "risk_before", "risk_before_class"),
            *risk_matrix_class_lookup_stages("risk_calculation_after", "risk_after", "risk_after_class"),

            # Step 9: Lookup assigned control measures
            {
                "$lookup": {
                    "from": IsmsControlMeasureAssignment.COLLECTION,
                    "localField": "public_id",
                    "foreignField": "risk_assessment_id",
                    "as": "control_assignments"
                }
            },
            {
                "$lookup": {
                    "from": IsmsControlMeasure.COLLECTION,
                    "localField": "control_assignments.control_measure_id",
                    "foreignField": "public_id",
                    "as": "control_measures"
                }
            },

            # Step 10: Project final fields
            {
                "$project": {
                    "_id": 0,
                    # Kept only as the pagination sort tiebreaker; dropped again after paging
                    "public_id": 1,
                    "risk_name": "$risk.name",
                    "risk_identifier": "$risk.identifier",
                    "risk_category": "$risk_category.value",
                    "protection_goals": "$protection_goals.name",

                    "object": {
                        "$cond": [
                            {"$eq": ["$object_id_ref_type", "OBJECT_GROUP"]},
                            {"$arrayElemAt": ["$object_group.name", 0]},
                            {"$arrayElemAt": ["$object.public_id", 0]}
                        ]
                    },
                    "object_type": {
                        "$cond": [
                            {"$eq": ["$object_id_ref_type", "OBJECT_GROUP"]},
                            "Object group",
                            {"$arrayElemAt": ["$object_type.label", 0]}
                        ]
                    },
                    "object_id_ref_type": 1,
                    **risk_calculation_projection_fields(),

                    "risk_treatment_option": "$risk_treatment_option",
                    "implementation_status": {
                    "$ifNull": ["$implementation_status.value", None]
                    },
                    "planned_implementation_date": 1,

                    "responsible_person": {
                        "$cond": [
                            { "$eq": ["$responsible_persons_id_ref_type", "PERSON"] },
                            {
                                "$ifNull": [
                                    { "$arrayElemAt": ["$responsible_person.display_name", 0] },
                                    None
                                ]
                            },
                            {
                                "$ifNull": [
                                    { "$arrayElemAt": ["$responsible_person_group.name", 0] },
                                    None
                                ]
                            }
                        ]
                    },

                    "control_measures": "$control_measures.title"
                }
            },
        ]

        # Column filters, applied after the $project so they target the resolved display fields - and
        # so both the returned page and the total reflect them
        query_pipeline.extend(build_report_filter_stages(params.filter))

        # Page the rows and count the full result set in a single pass
        query_pipeline.append(build_report_facet_stage(params))

        # allowDiskUse lets the pagination $sort spill to disk instead of hitting the 100MB in-memory limit
        aggregation = risk_assessment_manager.aggregate(query_pipeline, allowDiskUse=True)
        query_result, total = extract_report_page(list(aggregation))

        # Replace Object public_ids with their summary lines (batched), then drop the internal ref type
        _replace_object_ids_with_summaries(query_result, "object", objects_manager)

        for item in query_result:
            item.pop("object_id_ref_type", None)

        return GetMultiResponse(query_result, total, params, request.url, body).make_response()
    except RiskAssessmentManagerIterationError as err:
        LOGGER.error(
            "[get_isms_risk_treatment_plan_report] RiskAssessmentManagerIterationError: %s. Type: %s", err, type(err)
        )
        abort(500, "Failed to iterate components for Risk Treatment Plan report!")
    except Exception as err:
        LOGGER.error("[get_isms_risk_treatment_plan_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Risk Treatment Plan report!")


@isms_report_blueprint.route('/soa', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
def get_isms_soa_report(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the Statement of Applicability(SOA) report

    The report is paginated (``limit``/``page``) and wrapped in a GetMultiResponse envelope. Its
    ordering is fixed by the SOA business rules (see ``sort_key``: ISO 27001:2022 source first, then a
    natural identifier sort), so ``sort``/``order``/``filter`` query params are not applied here.

    **This is the one report that pages in Python**, and deliberately so: its two sibling reports append
    ``build_report_facet_stage`` and let MongoDB sort, skip and count in a single pass, which this one
    cannot. ``sort_key`` orders by the source label only AFTER it has been resolved from a
    CmdbExtendableOption, and then by a natural identifier sort that splits an identifier into digit and
    non-digit runs and compares variable-length tuples - neither is expressible as a ``$sort``. So the
    whole (bounded, catalogue-sized) control-measure set is read, ordered, and only then sliced by
    ``paginate_report_rows``. Do not fold this into the shared facet helpers without first changing the
    ordering contract that the certifier-facing document depends on.

    Args:
        params (CollectionParameters): Pagination parameters for the report
        request_user (CmdbUser): CmdbUser requesting the SOA report

    Returns:
        GetMultiResponse: The paginated SOA report
    """
    # This route resolves two option-label maps and paginates the sorted result, so the local count
    # legitimately exceeds the default
    # pylint: disable=too-many-locals
    try:
        body: bool = request_wants_body()

        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE,
                                                                            request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
                                                                                ManagerType.EXTENDABLE_OPTIONS,
                                                                                request_user)

        # Both option lists in a single projected query, already split by option_type. No model is
        # built per option: three keys are read and only the value is kept, so building a
        # CmdbExtendableOption per document just to convert it straight back was pure overhead
        option_value_maps: dict[str, dict[int, str]] = extendable_options_manager.get_option_values_by_id(
            [OptionType.IMPLEMENTATION_STATE.value, OptionType.CONTROL_MEASURE.value]
        )

        implementation_state_lookup: dict[int, str] = option_value_maps.get(
            OptionType.IMPLEMENTATION_STATE.value, {}
        )
        source_lookup: dict[int, str] = option_value_maps.get(OptionType.CONTROL_MEASURE.value, {})

        all_control_measures = control_measure_manager.get_many()

        # Single pass over the raw documents: replace the implementation_state and source public_ids
        # with their values, and normalise the SoA answer. The rows are read documents, not model
        # instances, so IsmsControlMeasure.from_data does not run over them - and a null is rendered as
        # an empty cell here rather than as the "No" a False gets, which is what a document written
        # before the insert route started normalising still holds
        for cm in all_control_measures:
            state_id = cm.get(ControlMeasureKey.IMPLEMENTATION_STATE.value)
            if state_id in implementation_state_lookup:
                cm[ControlMeasureKey.IMPLEMENTATION_STATE.value] = implementation_state_lookup[state_id]

            source_id = cm.get(ControlMeasureKey.SOURCE.value)
            if source_id in source_lookup:
                cm[ControlMeasureKey.SOURCE.value] = source_lookup[source_id]

            IsmsControlMeasure.normalize_is_applicable(cm)

        # Order all control measures by the SOA business rules, then slice the requested page. The
        # sort keys off the resolved source label, so it must run over the full set before paging
        all_control_measures.sort(key=sort_key)
        page_measures, total = paginate_report_rows(all_control_measures, params)

        # SOA honors only limit/page; reset the ignored params so the echoed metadata never reflects a
        # sort/filter that was not actually applied
        params.sort = SOA_FIXED_ORDER_SORT
        params.order = SOA_FIXED_ORDER_DIRECTION
        params.filter = {}

        return GetMultiResponse(page_measures, total, params, request.url, body).make_response()
    except Exception as err:
        LOGGER.error("[get_isms_soa_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the SOA report!")


@isms_report_blueprint.route('/risk_assessments', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
def get_isms_risk_assessments_report(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the RiskAssessment report

    The report is paginated: ``limit``/``page``/``sort``/``order``/``filter`` are read from the query
    string (see CollectionParameters) and the response is wrapped in a GetMultiResponse envelope.

    It also accepts **``?search=``**, a free-text term matched case-insensitively as a literal substring
    (the term is regex-escaped) across the resolved risk name, category and protection goals. Search and
    ``filter`` are both applied after the ``$project``, so they target the display fields the frontend
    reads and both the returned page and the total reflect them; together they compose as an implicit
    AND. ``filter`` accepts a MongoDB query dict or a list of pipeline stages.

    Note this report calls the risk's name ``risk_title`` while the Risk Treatment Plan calls the same
    value ``risk_name`` - both are frontend-visible contract, so the difference is recorded rather than
    resolved here.

    Args:
        params (CollectionParameters): Pagination, sort and filter parameters for the report
        request_user (CmdbUser): CmdbUser requesting the RiskAssessment report

    Returns:
        GetMultiResponse: The paginated RiskAssessment report
    """
    try:
        body: bool = request_wants_body()

        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        pipeline = [
            # Step 1: Start from all RiskAssessments. Column filters target the report's RESOLVED display
            # fields (risk_category, protection_goals, priority label, risk-class ids, ...) which do not
            # exist yet on the raw document, so params.filter is applied after the final $project below,
            # not here.
            {"$match": {}},

            # Step 2: Resolve every reference the report displays - risk, category, protection goals,
            # implementation status, the assessed object, the four person references, the risk classes,
            # the impact-category rollups and the likelihood levels
            *risk_assessment_report_stages(),

            # Last Step: Project the display fields the frontend reads
            risk_assessment_report_projection_stage(),
        ]

        # Optional free-text search over the resolved display fields (risk name / category /
        # protection goals). Applied after the $project and before the paging facet, so both the
        # returned page and the total count reflect the search.
        search: str = request.args.get('search', default='', type=str).strip()
        if search:
            pipeline.append(build_ra_report_search_stage(search))

        # Optional column filters. params.filter is a standard MongoDB query - a dict, or a list of
        # pipeline stages, which is the convention the whole backend reads it by. It runs after the
        # $project - like the search - so it can target the resolved display fields, and so both the
        # returned page and the total reflect it; it composes with the search as an implicit AND.
        pipeline.extend(build_report_filter_stages(params.filter))

        # Page the rows and count the full result set in a single pass
        pipeline.append(build_report_facet_stage(params))

        # allowDiskUse lets the pagination $sort and the $group stages spill to disk instead of
        # hitting the 100MB in-memory limit
        aggregation = risk_assessment_manager.aggregate(pipeline, allowDiskUse=True)
        query_result, total = extract_report_page(list(aggregation))

        # Replace Object public_ids with their summary lines (batched)
        _replace_object_ids_with_summaries(query_result, "assigned_object", objects_manager)

        return GetMultiResponse(query_result, total, params, request.url, body).make_response()
    except Exception as err:
        LOGGER.error("[get_isms_risk_assessments_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the RiskAssessment report!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def sort_key(cm: dict) -> tuple:
    """
    Sort key function for Control Measures
    - First, prioritize sources where source = "ISO 27001:2022"
    - Then, sort by the identifier
    - If identifier is empty, place it last
    
    Args:
        cm (dict): Control Measure data containing 'source' and 'identifier'.

    Returns:
        tuple: A tuple that will be used for sorting:
            (priority_for_source, priority_for_empty_identifier, sorted_identifier)
    """
    # 1. Put ISO 27001:2022 first
    source_priority: int = 0 if cm.get(ControlMeasureKey.SOURCE.value) == SOA_PRIMARY_SOURCE else 1

    # 2. Identifiers that are empty or missing should come last
    identifier = cm.get(ControlMeasureKey.IDENTIFIER.value)
    identifier_is_empty = not identifier or not identifier.strip()

    # This ensures that empty identifiers get a higher "penalty"
    empty_priority: int = 1 if identifier_is_empty else 0

    # 3. Split the identifier into numeric / non-numeric parts for natural sorting. Each part is
    #    wrapped as (type_rank, value) so numeric and string parts never compare against each other
    #    (which would raise a TypeError) - digit groups (rank 0) sort before non-digit groups (rank 1)
    identifier_sort_value: list[tuple[int, object]] = [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r'(\D+|\d+)', identifier or '')
    ]

    return (source_priority, empty_priority, identifier_sort_value)
