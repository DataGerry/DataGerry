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
from typing import Any
from flask import request
from werkzeug import Response

from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.utils import Builder

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsProtectionGoal,
    IsmsRisk,
)
from cmdb.framework.isms import RiskMatrixReportBuilder
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey, PersonReferenceType
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.extendable_option_model import OptionType, CmdbExtendableOption, ExtendableOptionKey
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.object_group_model import ObjectGroupKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.type_model import TypeSchemaKey

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse, GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    build_ra_report_search_stage,
    build_report_facet_stage,
    build_report_filter_stages,
    extract_report_page,
    field_path,
    field_reference,
    object_reference_lookup_stages,
    paginate_report_rows,
    risk_assessment_report_projection_stage,
    risk_calculation_projection_fields,
    risk_assessment_report_stages,
    risk_matrix_class_lookup_stages,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    IsmsReportErrorMessage,
    OBJECT_GROUP_TYPE_LABEL,
    ReportAlias,
    RiskAssessmentReportKey,
    RiskTreatmentPlanReportKey,
)

from cmdb.errors.framework_isms import RiskMatrixReportError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
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


def _replace_object_ids_with_summaries(
        items: list[dict[str, Any]],
        object_key: str,
        objects_manager: ObjectsManager) -> None:
    """
    Replaces each report item's OBJECT-referenced public_id (under ``object_key``) with the object's
    summary line, resolved in a single batch rather than one lookup per item.

    Only items whose ``object_id_ref_type`` is OBJECT are touched; an id with no resolvable object
    becomes 'Unknown object'.

    Args:
        items (list[dict[str, Any]]): The aggregated report rows to enrich in place
        object_key (str): The key holding the object public_id to replace
        objects_manager (ObjectsManager): Manager used to resolve the summary lines
    """
    target_items = [
        item for item in items
        if item.get(object_key) and item.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) == ObjectReferenceType.OBJECT
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
@handle_route_errors("while retrieving the RiskMatrix report")
@handle_manager_errors({RiskMatrixReportError: IsmsReportErrorMessage.RISK_MATRIX.value})
def get_isms_risk_matrix_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the IsmsRiskMatrix report

    The body carries the grid counted three ways - `risk_matrix_before_treatment`,
    `risk_matrix_current_state`, `risk_matrix_after_treatment` - plus `configured`, which is False
    while the ISMS config wizard has not produced the risk matrix yet. Without that flag the state
    is indistinguishable from a configured matrix nothing has been assessed against

    Args:
        request_user (CmdbUser): CmdbUser requesting the RiskMatrix report

    Raises:
        HTTPException: 400 when the report could not be built from the stored data, 500 on an
                       unexpected error

    Returns:
        DefaultResponse: The RiskMatrix report as a dictionary
    """
    risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
        ManagerType.RISK_ASSESSMENT, request_user,
    )
    risk_matrix_manager: RiskMatrixManager = ManagerProvider.get_manager(ManagerType.RISK_MATRIX, request_user)
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
        ManagerType.EXTENDABLE_OPTIONS, request_user,
    )

    report_builder = RiskMatrixReportBuilder(
        risk_assessment_manager,
        risk_matrix_manager,
        extendable_options_manager
    )

    risk_matrix_report = report_builder.build_risk_matrix_report()

    return DefaultResponse(risk_matrix_report).make_response()


@isms_report_blueprint.route('/risk_treatment_plan', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the Risk Treatment Plan report")
@handle_manager_errors({
    BaseManagerIterationError: IsmsReportErrorMessage.RISK_TREATMENT_PLAN.value,
    RiskAssessmentManagerIterationError: IsmsReportErrorMessage.RISK_TREATMENT_PLAN.value,
    ObjectsManagerGetError: IsmsReportErrorMessage.RISK_TREATMENT_PLAN.value,
})
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

    Raises:
        HTTPException: 400 when the aggregation or the object summaries could not be read from
            the database, 500 on an unexpected error

    Returns:
        GetMultiResponse: The paginated Risk Treatment Plan report
    """
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
        Builder.match_({}),
        # Step 1: Lookup associated Risk
        Builder.lookup_(
            IsmsRisk.COLLECTION,
            RiskAssessmentKey.RISK_ID.value,
            RiskKey.PUBLIC_ID.value,
            ReportAlias.RISK.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK), "preserveNullAndEmptyArrays": True}),

        # Step 2: Lookup implementation status (ExtendableOption)
        Builder.lookup_(
            CmdbExtendableOption.COLLECTION,
            RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
            ExtendableOptionKey.PUBLIC_ID.value,
            ReportAlias.IMPLEMENTATION_STATUS.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.IMPLEMENTATION_STATUS),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step 3: Lookup risk category label (ExtendableOption)
        Builder.lookup_(
            CmdbExtendableOption.COLLECTION,
            field_path(ReportAlias.RISK, RiskKey.CATEGORY_ID),
            ExtendableOptionKey.PUBLIC_ID.value,
            ReportAlias.RISK_CATEGORY.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK_CATEGORY), "preserveNullAndEmptyArrays": True}),

        # Lookup protection goals by IDs in risk.protection_goals
        Builder.lookup_(
            IsmsProtectionGoal.COLLECTION,
            field_path(ReportAlias.RISK, RiskKey.PROTECTION_GOALS),
            ProtectionGoalKey.PUBLIC_ID.value,
            ReportAlias.PROTECTION_GOALS.value,
        ),

        # Lookup Object / ObjectGroup / type label for the assessed object
        *object_reference_lookup_stages(),

        # Step 6: Lookup person/personGroup
        Builder.lookup_(
            CmdbPerson.COLLECTION,
            RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            PersonKey.PUBLIC_ID.value,
            ReportAlias.RESPONSIBLE_PERSON.value,
        ),
        Builder.lookup_(
            CmdbPersonGroup.COLLECTION,
            RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            PersonGroupKey.PUBLIC_ID.value,
            ReportAlias.RESPONSIBLE_PERSON_GROUP.value,
        ),

        # Resolve each risk_calculation matrix cell + its risk class (before and after treatment)
        *risk_matrix_class_lookup_stages(
            RiskAssessmentKey.RISK_CALCULATION_BEFORE.value,
            ReportAlias.RISK_BEFORE.value,
            ReportAlias.RISK_BEFORE_CLASS.value,
        ),
        *risk_matrix_class_lookup_stages(
            RiskAssessmentKey.RISK_CALCULATION_AFTER.value,
            ReportAlias.RISK_AFTER.value,
            ReportAlias.RISK_AFTER_CLASS.value,
        ),

        # Step 9: Lookup assigned control measures
        Builder.lookup_(
            IsmsControlMeasureAssignment.COLLECTION,
            RiskAssessmentKey.PUBLIC_ID.value,
            ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value,
            ReportAlias.CONTROL_ASSIGNMENTS.value,
        ),
        Builder.lookup_(
            IsmsControlMeasure.COLLECTION,
            field_path(ReportAlias.CONTROL_ASSIGNMENTS, ControlMeasureAssignmentKey.CONTROL_MEASURE_ID),
            ControlMeasureKey.PUBLIC_ID.value,
            ReportAlias.CONTROL_MEASURES.value,
        ),

        # Step 10: Project final fields
        Builder.project_({
            "_id": 0,
            # Kept only as the pagination sort tiebreaker; dropped again after paging
            RiskAssessmentKey.PUBLIC_ID.value: 1,
            RiskTreatmentPlanReportKey.RISK_NAME.value: field_reference(ReportAlias.RISK, RiskKey.NAME),
            RiskTreatmentPlanReportKey.RISK_IDENTIFIER.value: field_reference(ReportAlias.RISK, RiskKey.IDENTIFIER),
            RiskTreatmentPlanReportKey.RISK_CATEGORY.value: field_reference(
                ReportAlias.RISK_CATEGORY, ExtendableOptionKey.VALUE
            ),
            RiskTreatmentPlanReportKey.PROTECTION_GOALS.value: field_reference(
                ReportAlias.PROTECTION_GOALS, ProtectionGoalKey.NAME
            ),

            RiskTreatmentPlanReportKey.OBJECT.value: {
                "$cond": [
                    {"$eq": [
                        field_reference(RiskAssessmentKey.OBJECT_ID_REF_TYPE),
                        ObjectReferenceType.OBJECT_GROUP.value,
                    ]},
                    {"$arrayElemAt": [field_reference(ReportAlias.OBJECT_GROUP, ObjectGroupKey.NAME), 0]},
                    {"$arrayElemAt": [field_reference(ReportAlias.OBJECT, CmdbObjectKey.PUBLIC_ID), 0]}
                ]
            },
            RiskTreatmentPlanReportKey.OBJECT_TYPE.value: {
                "$cond": [
                    {"$eq": [
                        field_reference(RiskAssessmentKey.OBJECT_ID_REF_TYPE),
                        ObjectReferenceType.OBJECT_GROUP.value,
                    ]},
                    OBJECT_GROUP_TYPE_LABEL,
                    {"$arrayElemAt": [field_reference(ReportAlias.OBJECT_TYPE, TypeSchemaKey.LABEL), 0]}
                ]
            },
            RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: 1,
            **risk_calculation_projection_fields(),

            RiskTreatmentPlanReportKey.RISK_TREATMENT_OPTION.value: field_reference(
                RiskAssessmentKey.RISK_TREATMENT_OPTION
            ),
            RiskTreatmentPlanReportKey.IMPLEMENTATION_STATUS.value: {
                "$ifNull": [field_reference(ReportAlias.IMPLEMENTATION_STATUS, ExtendableOptionKey.VALUE), None]
            },
            RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: 1,

            RiskTreatmentPlanReportKey.RESPONSIBLE_PERSON.value: {
                "$cond": [
                    {"$eq": [
                        field_reference(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE),
                        PersonReferenceType.PERSON.value,
                    ]},
                    {
                        "$ifNull": [
                            {"$arrayElemAt": [
                                field_reference(ReportAlias.RESPONSIBLE_PERSON, PersonKey.DISPLAY_NAME), 0
                            ]},
                            None
                        ]
                    },
                    {
                        "$ifNull": [
                            {"$arrayElemAt": [
                                field_reference(ReportAlias.RESPONSIBLE_PERSON_GROUP, PersonGroupKey.NAME), 0
                            ]},
                            None
                        ]
                    }
                ]
            },

            RiskTreatmentPlanReportKey.CONTROL_MEASURES.value: field_reference(
                ReportAlias.CONTROL_MEASURES, ControlMeasureKey.TITLE
            )
        }),
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
    _replace_object_ids_with_summaries(query_result, RiskTreatmentPlanReportKey.OBJECT.value, objects_manager)

    for item in query_result:
        item.pop(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value, None)

    return GetMultiResponse(query_result, total, params, request.url, body).make_response()


@isms_report_blueprint.route('/soa', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the SOA report")
@handle_manager_errors({BaseManagerGetError: IsmsReportErrorMessage.SOA.value})
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

    Raises:
        HTTPException: 400 when the ControlMeasures or their option labels could not be read
            from the database, 500 on an unexpected error

    Returns:
        GetMultiResponse: The paginated SOA report
    """
    # This route resolves two option-label maps and paginates the sorted result, so the local count
    # legitimately exceeds the default
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


@isms_report_blueprint.route('/risk_assessments', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
@isms_report_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the RiskAssessment report")
@handle_manager_errors({
    BaseManagerIterationError: IsmsReportErrorMessage.RISK_ASSESSMENTS.value,
    ObjectsManagerGetError: IsmsReportErrorMessage.RISK_ASSESSMENTS.value,
})
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

    Raises:
        HTTPException: 400 when the aggregation or the object summaries could not be read from
            the database, 500 on an unexpected error

    Returns:
        GetMultiResponse: The paginated RiskAssessment report
    """
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
        Builder.match_({}),

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
    _replace_object_ids_with_summaries(
        query_result, RiskAssessmentReportKey.ASSIGNED_OBJECT.value, objects_manager
    )

    return GetMultiResponse(query_result, total, params, request.url, body).make_response()

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def sort_key(cm: dict[str, Any]) -> tuple[int, int, list[tuple[int, object]]]:
    """
    Sort key function for Control Measures
    - First, prioritize sources where source = "ISO 27001:2022"
    - Then, sort by the identifier
    - If identifier is empty, place it last
    
    Args:
        cm (dict[str, Any]): Control Measure data containing 'source' and 'identifier'.

    Returns:
        tuple[int, int, list[tuple[int, object]]]: A tuple that will be used for sorting:
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
