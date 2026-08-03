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

from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.risk_matrix_manager import RiskMatrixManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder.builder_parameters import BuilderParameters

from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsReportBuilder
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
    extract_report_page,
    object_reference_lookup_stages,
    paginate_report_rows,
    risk_matrix_class_lookup_stages,
)

from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# SOA rows are ordered by the fixed business rules (sort_key), so the report ignores sort/order/filter.
# These neutral values are echoed back in the response metadata instead of a client's ignored request.
SOA_FIXED_ORDER_SORT: str = 'public_id'
SOA_FIXED_ORDER_DIRECTION: int = 1

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
        item[object_key] = summaries.get(item[object_key], 'Unknown object')

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@isms_report_blueprint.route('/risk_matrix', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
def get_isms_risk_matrix_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the IsmsRiskMatrix report

    Args:
        request_user (CmdbUser): CmdbUser requesting the RiskMatrix report

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

        isms_report_builder = IsmsReportBuilder(
            risk_assessment_manager,
            risk_matrix_manager,
            extendable_options_manager
        )

        risk_matrix_report = isms_report_builder.build_risk_matrix_report()

        return DefaultResponse(risk_matrix_report).make_response()
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

    Args:
        params (CollectionParameters): Pagination, sort and filter parameters for the report
        request_user (CmdbUser): CmdbUser requesting the Risk Treatment Plan report

    Returns:
        GetMultiResponse: The paginated Risk Treatment Plan report
    """
    try:
        body: bool = request.method == 'HEAD'

        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        query_pipeline = [
            # Step 0: Get all IsmsRiskAssessments matching the filter
            {
                "$match": params.filter
            },
            # Step 1: Lookup associated Risk
            {
                "$lookup": {
                    "from": "isms.risk",
                    "localField": "risk_id",
                    "foreignField": "public_id",
                    "as": "risk"
                }
            },
            {"$unwind": {"path": "$risk", "preserveNullAndEmptyArrays": True}},

            # Step 2: Lookup implementation status (ExtendableOption)
            {
                "$lookup": {
                    "from": "framework.extendableOptions",
                    "localField": "implementation_status",
                    "foreignField": "public_id",
                    "as": "implementation_status"
                }
            },
            {"$unwind": {"path": "$implementation_status", "preserveNullAndEmptyArrays": True}},

            # Step 3: Lookup risk category label (ExtendableOption)
            {
                "$lookup": {
                    "from": "framework.extendableOptions",
                    "localField": "risk.category_id",
                    "foreignField": "public_id",
                    "as": "risk_category"
                }
            },
            {"$unwind": {"path": "$risk_category", "preserveNullAndEmptyArrays": True}},

            # Lookup protection goals by IDs in risk.protection_goals
            {
                "$lookup": {
                    "from": "isms.protectionGoal",
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
                    "from": "management.person",
                    "localField": "responsible_persons_id",
                    "foreignField": "public_id",
                    "as": "responsible_person"
                }
            },
            {
                "$lookup": {
                    "from": "management.personGroup",
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
                    "from": "isms.controlMeasureAssignment",
                    "localField": "public_id",
                    "foreignField": "risk_assessment_id",
                    "as": "control_assignments"
                }
            },
            {
                "$lookup": {
                    "from": "isms.controlMeasure",
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
                    "risk_before": {
                        "value": "$risk_before.calculated_value",
                        "risk_class_id": "$risk_before_class.public_id",
                        "color": "$risk_before_class.color"
                    },
                    "risk_after": {
                        "value": {
                            "$ifNull": ["$risk_after.calculated_value", None]
                        },
                        "risk_class_id": {
                            "$ifNull": ["$risk_after_class.public_id", None]
                        },
                        "color": {
                            "$ifNull": ["$risk_after_class.color", None]
                        }
                    },

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

            # Step 11: Page the rows and count the full result set in a single pass
            build_report_facet_stage(params),
        ]

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
        body: bool = request.method == 'HEAD'

        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE,
                                                                            request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
                                                                                ManagerType.EXTENDABLE_OPTIONS,
                                                                                request_user)

        # Fetch both the implementation-state and source options in a single query, then split them
        # by option_type into their lookup maps
        options = extendable_options_manager.iterate_items(BuilderParameters(
            {'option_type': {'$in': [OptionType.IMPLEMENTATION_STATE, OptionType.CONTROL_MEASURE]}}
        ))

        implementation_state_lookup: dict[int, str] = {}
        source_lookup: dict[int, str] = {}

        for option in options.results:
            option_json = CmdbExtendableOption.to_json(option)

            if option_json['option_type'] == OptionType.IMPLEMENTATION_STATE:
                implementation_state_lookup[option_json['public_id']] = option_json['value']
            else:
                source_lookup[option_json['public_id']] = option_json['value']

        all_control_measures = control_measure_manager.get_many()

        # Single pass: replace the implementation_state and source public_ids with their values
        for cm in all_control_measures:
            state_id = cm.get('implementation_state')
            if state_id in implementation_state_lookup:
                cm['implementation_state'] = implementation_state_lookup[state_id]

            source_id = cm.get('source')
            if source_id in source_lookup:
                cm['source'] = source_lookup[source_id]

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

    Args:
        params (CollectionParameters): Pagination, sort and filter parameters for the report
        request_user (CmdbUser): CmdbUser requesting the RiskAssessment report

    Returns:
        GetMultiResponse: The paginated RiskAssessment report
    """
    try:
        body: bool = request.method == 'HEAD'

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

            # Step 2: Lookup assigned Risk
            {"$lookup": {
                "from": "isms.risk",
                "localField": "risk_id",
                "foreignField": "public_id",
                "as": "risk"
            }},
            {"$unwind": "$risk"},

            # Step 3: Lookup risk category label (ExtendableOption)
            {
                "$lookup": {
                    "from": "framework.extendableOptions",
                    "localField": "risk.category_id",
                    "foreignField": "public_id",
                    "as": "risk_category"
                }
            },
            {"$unwind": {"path": "$risk_category", "preserveNullAndEmptyArrays": True}},

            # Step 4: Lookup Protection Goals
            {"$lookup": {
                "from": "isms.protectionGoal",
                "localField": "risk.protection_goals",
                "foreignField": "public_id",
                "as": "protection_goals"
            }},

            # Step 5: Lookup Implementation Status
            {
                "$lookup": {
                    "from": "framework.extendableOptions",
                    "localField": "implementation_status",
                    "foreignField": "public_id",
                    "as": "implementation_status"
                }
            },
            {"$unwind": {"path": "$implementation_status", "preserveNullAndEmptyArrays": True}},

            # Lookup Object / ObjectGroup / type label for the assessed object
            *object_reference_lookup_stages(),

            # Step 7: Lookup the Risk Assessor (P)
            {
                "$lookup": {
                    "from": "management.person",
                    "localField": "risk_assessor_id",
                    "foreignField": "public_id",
                    "as": "risk_assessor_person"
                }
            },
            {
                "$unwind": {
                    "path": "$risk_assessor_person",
                    "preserveNullAndEmptyArrays": True
                }
            },

            # Step 8: Lookup Risk Owner (P or PG)
            {
                "$lookup": {
                    "from": "management.person",
                    "localField": "risk_owner_id",
                    "foreignField": "public_id",
                    "as": "risk_owner_person"
                }
            },
            {
                "$lookup": {
                    "from": "management.personGroup",
                    "localField": "risk_owner_id",
                    "foreignField": "public_id",
                    "as": "risk_owner_group"
                }
            },

            # Step 9: Lookup Responsible Person (P or PG)
            {
                "$lookup": {
                    "from": "management.person",
                    "localField": "responsible_persons_id",
                    "foreignField": "public_id",
                    "as": "responsible_person"
                }
            },
            {
                "$lookup": {
                    "from": "management.personGroup",
                    "localField": "responsible_persons_id",
                    "foreignField": "public_id",
                    "as": "responsible_person_group"
                }
            },

            # Step 10: Lookup Auditor (P or PG)
            {
                "$lookup": {
                    "from": "management.person",
                    "localField": "auditor_id",
                    "foreignField": "public_id",
                    "as": "auditor_person"
                }
            },
            {
                "$lookup": {
                    "from": "management.personGroup",
                    "localField": "auditor_id",
                    "foreignField": "public_id",
                    "as": "auditor_group"
                }
            },

            # Step 11: Lookup Interviewed Persons (multiple P)
            {"$lookup": {
                "from": "management.person",
                "localField": "interviewed_persons",
                "foreignField": "public_id",
                "as": "interviewed_persons_data"
            }},

            # Step 12: Lookup risk class matrix values for risk_before
            {
                "$lookup": {
                    "from": "isms.riskMatrix",
                    "let": {
                        "likelihood_id": "$risk_calculation_before.likelihood_id",
                        "impact_id": "$risk_calculation_before.maximum_impact_id"
                    },
                    "pipeline": [
                        { "$match": { "public_id": 1 } },
                        { "$unwind": "$risk_matrix" },
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        { "$eq": ["$risk_matrix.likelihood_id", "$$likelihood_id"] },
                                        { "$eq": ["$risk_matrix.impact_id", "$$impact_id"] }
                                    ]
                                }
                            }
                        },
                        { "$replaceRoot": { "newRoot": "$risk_matrix" } }
                    ],
                    "as": "risk_before"
                }
            },
            { "$unwind": { "path": "$risk_before", "preserveNullAndEmptyArrays": True } },
            {
                "$lookup": {
                    "from": "isms.riskClass",
                    "localField": "risk_before.risk_class_id",
                    "foreignField": "public_id",
                    "as": "risk_before_class"
                }
            },
            { "$unwind": { "path": "$risk_before_class", "preserveNullAndEmptyArrays": True } },

            # Step 13: Repeat for risk after treatment
            {
                "$lookup": {
                    "from": "isms.riskMatrix",
                    "let": {
                        "likelihood_id": "$risk_calculation_after.likelihood_id",
                        "impact_id": "$risk_calculation_after.maximum_impact_id"
                    },
                    "pipeline": [
                        { "$match": { "public_id": 1 } },
                        { "$unwind": "$risk_matrix" },
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        { "$eq": ["$risk_matrix.likelihood_id", "$$likelihood_id"] },
                                        { "$eq": ["$risk_matrix.impact_id", "$$impact_id"] }
                                    ]
                                }
                            }
                        },
                        { "$replaceRoot": { "newRoot": "$risk_matrix" } }
                    ],
                    "as": "risk_after"
                }
            },
            { "$unwind": { "path": "$risk_after", "preserveNullAndEmptyArrays": True } },
            {
                "$lookup": {
                    "from": "isms.riskClass",
                    "localField": "risk_after.risk_class_id",
                    "foreignField": "public_id",
                    "as": "risk_after_class"
                }
            },
            { "$unwind": { "path": "$risk_after_class", "preserveNullAndEmptyArrays": True } },

            # Step 14: Create Impact categories before list
            # Step A: Unwind before impacts
            { "$unwind": { "path": "$risk_calculation_before.impacts", "preserveNullAndEmptyArrays": True } },

            # Step B: Lookup impact category
            {
            "$lookup": {
                "from": "isms.impactCategory",
                "localField": "risk_calculation_before.impacts.impact_category_id",
                "foreignField": "public_id",
                "as": "impact_category_before"
            }
            },
            { "$unwind": { "path": "$impact_category_before", "preserveNullAndEmptyArrays": True } },

            # Step C: Lookup impact
            {
            "$lookup": {
                "from": "isms.impact",
                "localField": "risk_calculation_before.impacts.impact_id",
                "foreignField": "public_id",
                "as": "impact_before"
            }
            },
            { "$unwind": { "path": "$impact_before", "preserveNullAndEmptyArrays": True } },

            # Step D: Group and build new array
            {
            "$group": {
                "_id": "$_id",
                "doc": { "$first": "$$ROOT" },
                "impact_categories_before": {
                "$push": {
                    "impact_category": "$impact_category_before.name",
                    "impact_value": {
                    "$cond": {
                        "if": { "$and": [
                            { "$ne": ["$impact_before.calculation_basis", None] },
                            { "$ne": ["$impact_before.name", None]}]
                        },
                        "then": {
                        "$concat": [
                            { "$toString": "$impact_before.calculation_basis" },
                            " - ",
                            "$impact_before.name"
                        ]
                        },
                        "else": None
                    }
                    }
                }
                }
            }
            },
            { "$replaceRoot": { "newRoot": { "$mergeObjects": ["$doc", {
                                            "impact_categories_before": "$impact_categories_before" }] } } },

            # Step 15: Create Impact categories after list
            # Step A: Unwind after impacts
            { "$unwind": { "path": "$risk_calculation_after.impacts", "preserveNullAndEmptyArrays": True } },

            # Step B: Lookup impact category
            {
            "$lookup": {
                "from": "isms.impactCategory",
                "localField": "risk_calculation_after.impacts.impact_category_id",
                "foreignField": "public_id",
                "as": "impact_category_after"
            }
            },
            { "$unwind": { "path": "$impact_category_after", "preserveNullAndEmptyArrays": True } },

            # Step C: Lookup impact
            {
            "$lookup": {
                "from": "isms.impact",
                "localField": "risk_calculation_after.impacts.impact_id",
                "foreignField": "public_id",
                "as": "impact_after"
            }
            },
            { "$unwind": { "path": "$impact_after", "preserveNullAndEmptyArrays": True } },

            # Step D: Group and build new array
            {
            "$group": {
                "_id": "$_id",
                "doc": { "$first": "$$ROOT" },
                "impact_categories_after": {
                "$push": {
                    "impact_category": "$impact_category_after.name",
                    "impact_value": {
                    "$cond": {
                        "if": { "$and": [
                            { "$ne": ["$impact_after.calculation_basis", None] },
                            { "$ne": ["$impact_after.name", None]}]
                        },
                        "then": {
                        "$concat": [
                            { "$toString": "$impact_after.calculation_basis" },
                            " - ",
                            "$impact_after.name"
                        ]
                        },
                        "else": None
                    }
                    }
                }
                }
            }
            },
            { "$replaceRoot": { "newRoot": { "$mergeObjects": ["$doc", {
                                            "impact_categories_after": "$impact_categories_after" }] } } },

            # Lookup Likelihood before
            {
            "$lookup": {
                "from": "isms.likelihood",
                "localField": "risk_calculation_before.likelihood_id",
                "foreignField": "public_id",
                "as": "likelihood_before"
            }
            },
            { "$unwind": { "path": "$likelihood_before", "preserveNullAndEmptyArrays": True } },

            # Lookup Likelihood after
            {
            "$lookup": {
                "from": "isms.likelihood",
                "localField": "risk_calculation_after.likelihood_id",
                "foreignField": "public_id",
                "as": "likelihood_after"
            }
            },
            { "$unwind": { "path": "$likelihood_after", "preserveNullAndEmptyArrays": True } },

            # Last Step: Project the Fields
            {"$project": {
                "_id": 0,
                # Kept only as the pagination sort tiebreaker; dropped again after paging
                "public_id": 1,
                "risk_title": "$risk.name",
                "risk_category": "$risk_category.value",
                "protection_goals": {
                    "$map": {
                        "input": "$protection_goals",
                        "as": "pg",
                        "in": "$$pg.name"
                    }
                },
                "risk_owner": {
                    "$cond": [
                        { "$eq": ["$risk_owner_id_ref_type", "PERSON"] },
                        {
                            "$ifNull": [
                                { "$arrayElemAt": ["$risk_owner_person.display_name", 0] },
                                None
                            ]
                        },
                        {
                            "$ifNull": [
                                { "$arrayElemAt": ["$risk_owner_group.name", 0] },
                                None
                            ]
                        }
                    ]
                },
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
                "auditor": {
                    "$cond": [
                        { "$eq": ["$auditor_id_ref_type", "PERSON"] },
                        {
                            "$ifNull": [
                                { "$arrayElemAt": ["$auditor_person.display_name", 0] },
                                None
                            ]
                        },
                        {
                            "$ifNull": [
                                { "$arrayElemAt": ["$auditor_group.name", 0] },
                                None
                            ]
                        }
                    ]
                },
                "implementation_status": {
                    "$ifNull": ["$implementation_status.value", None]
                },
                "priority": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": ["$priority", 1]}, "then": "Low"},
                            {"case": {"$eq": ["$priority", 2]}, "then": "Medium"},
                            {"case": {"$eq": ["$priority", 3]}, "then": "High"},
                            {"case": {"$eq": ["$priority", 4]}, "then": "Very High"}
                        ],
                        "default": None
                    }
                },
                "assigned_object": {
                    "$cond": [
                        {"$eq": ["$object_id_ref_type", "OBJECT_GROUP"]},
                        {"$arrayElemAt": ["$object_group.name", 0]},
                        {"$arrayElemAt": ["$object.public_id", 0]}
                    ]
                },
                "assigned_object_type": {
                    "$cond": [
                        {"$eq": ["$object_id_ref_type", "OBJECT_GROUP"]},
                        "Object group",
                        {"$arrayElemAt": ["$object_type.label", 0]}
                    ]
                },
                "risk_assessor": {
                    "$ifNull": ["$risk_assessor_person.display_name", None]
                },
                "interviewed_persons": {
                    "$cond": {
                        "if": { "$gt": [{ "$size": "$interviewed_persons_data" }, 0] },
                        "then": {
                            "$map": {
                                "input": "$interviewed_persons_data",
                                "as": "person",
                                "in": "$$person.display_name"
                            }
                        },
                        "else": None
                    }
                },
                "risk_before": {
                    "value": "$risk_before.calculated_value",
                    "risk_class_id": "$risk_before_class.public_id",
                    "color": "$risk_before_class.color"
                },
                "risk_after": {
                    "value": {
                        "$ifNull": ["$risk_after.calculated_value", None]
                    },
                    "risk_class_id": {
                        "$ifNull": ["$risk_after_class.public_id", None]
                    },
                    "color": {
                        "$ifNull": ["$risk_after_class.color", None]
                    }
                },
                "impact_categories_before": 1,
                "impact_categories_after": 1,
                "likelihood_value_before": {
                    "$cond": {
                        "if": {
                        "$and": [
                            { "$ne": ["$likelihood_before.calculation_basis", None] },
                            { "$ne": ["$likelihood_before.name", None] }
                        ]
                        },
                        "then": {
                        "$concat": [
                            { "$toString": "$likelihood_before.calculation_basis" },
                            " - ",
                            "$likelihood_before.name"
                        ]
                        },
                        "else": None
                    }
                },
                "likelihood_value_after": {
                    "$cond": {
                        "if": {
                        "$and": [
                            { "$ne": ["$likelihood_after.calculation_basis", None] },
                            { "$ne": ["$likelihood_after.name", None] }
                        ]
                        },
                        "then": {
                        "$concat": [
                            { "$toString": "$likelihood_after.calculation_basis" },
                            " - ",
                            "$likelihood_after.name"
                        ]
                        },
                        "else": None
                    }
                },
                "additional_information": 1,
                "risk_treatment_option": {
                    "$ifNull": ["$risk_treatment_option", None]
                },
                "risk_treatment_description": 1,
                "risk_assessment_date": 1,
                "additional_info": 1,
                "planned_implementation_date": 1,
                "finished_implementation_date": 1,
                "implementation_finished_on": 1,
                "required_resources": 1,
                "costs_for_implementation": 1,
                "costs_for_implementation_currency": 1,
                "audit_done_date": 1,
                "audit_result": 1,
                "object_id_ref_type": 1,
            }},
        ]

        # Optional free-text search over the resolved display fields (risk name / category /
        # protection goals). Applied after the $project and before the paging facet, so both the
        # returned page and the total count reflect the search.
        search: str = request.args.get('search', default='', type=str).strip()
        if search:
            pipeline.append(build_ra_report_search_stage(search))

        # Optional column filters. params.filter is a standard MongoDB query (the general filter
        # convention used across the backend / by the sibling reports), applied as a $match. It runs
        # after the $project - like the search - so it can target the resolved display fields, and so
        # both the returned page and the total reflect it; it composes with the search as an implicit AND.
        if params.filter:
            pipeline.append({"$match": params.filter})

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
    source_priority: int = 0 if cm.get('source') == 'ISO 27001:2022' else 1

    # 2. Identifiers that are empty or missing should come last
    identifier = cm.get('identifier')
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
