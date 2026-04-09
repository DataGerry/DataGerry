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
from flask import abort
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

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

isms_report_blueprint = APIBlueprint('isms_report', __name__)

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
def get_isms_risk_treatment_plan_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the Risk Treatment Plan report

    Args:
        request_user (CmdbUser): CmdbUser requesting the Risk Treatment Plan report

    Returns:
        DefaultResponse: The Risk Treatment Plan report as a dictionary
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        query_pipeline = [
            # Step 0: Get all IsmsRiskAssessments
            {
                "$match": {}
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

            # Step 4: Lookup Object or ObjectGroup based on object_id_ref_type
            {
                "$lookup": {
                    "from": "framework.objects",
                    "localField": "object_id",
                    "foreignField": "public_id",
                    "as": "object"
                }
            },
            {
                "$lookup": {
                    "from": "framework.objectGroups",
                    "localField": "object_id",
                    "foreignField": "public_id",
                    "as": "object_group"
                }
            },

            # Step 5: Lookup type label if object is used
            {
                "$lookup": {
                    "from": "framework.types",
                    "localField": "object.type_id",
                    "foreignField": "public_id",
                    "as": "object_type"
                }
            },

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

            # Step 7: Lookup risk class matrix values for risk_before
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

            # Step 8: Repeat for risk after treatment
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
            }
        ]

        query_result: list[dict] = list(risk_assessment_manager.aggregate(query_pipeline))

        # Replace Object public_id with Summary line
        for item in query_result:
            if item.get("object") and item.get("object_id_ref_type") == "OBJECT":
                try:
                    object_summary = objects_manager.get_summary_line(item["object"], with_type=False)
                    item["object"] = object_summary
                except Exception:
                    item["object"] = "Unknown object"

            # Clean up unnecessary internal fields
            item.pop("object_id_ref_type", None)

        return DefaultResponse(query_result).make_response()
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
def get_isms_soa_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the Statement of Applicability(SOA) report

    Args:
        request_user (CmdbUser): CmdbUser requesting the SOA report

    Returns:
        DefaultResponse: The SOA report as a dictionary
    """
    try:
        control_measure_manager: ControlMeasureManager = ManagerProvider.get_manager(
                                                                            ManagerType.CONTROL_MEASURE,
                                                                            request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
                                                                                ManagerType.EXTENDABLE_OPTIONS,
                                                                                request_user)

        # Get all implementation states for IsmsControlMeasures
        implementation_states = extendable_options_manager.iterate_items(BuilderParameters(
                                                                    {'option_type':OptionType.IMPLEMENTATION_STATE}
                                                                ))
        all_implementation_states = [CmdbExtendableOption.to_json(imp_state) for
                                     imp_state in implementation_states.results]

        # Create a lookup map from public_id to value for implementation states
        implementation_state_lookup = {
            option['public_id']: option['value'] for option in all_implementation_states
        }

        all_control_meassures = control_measure_manager.get_many()

        # Replace implementation_state public_id with its corresponding value
        for cm in all_control_meassures:
            original_id = cm.get('implementation_state')
            if original_id in implementation_state_lookup:
                cm['implementation_state'] = implementation_state_lookup[original_id]


        cm_sources = extendable_options_manager.iterate_items(BuilderParameters(
                                                                    {'option_type':OptionType.CONTROL_MEASURE}
                                                                ))
        all_sources = [CmdbExtendableOption.to_json(source) for source in cm_sources.results]

        # Create a lookup map from public_id to value for sources
        source_lookup = {
            option['public_id']: option['value'] for option in all_sources
        }

        # Replace source public_id with its corresponding value
        for cm in all_control_meassures:
            source_id = cm.get('source')
            if source_id in source_lookup:
                cm['source'] = source_lookup[source_id]

        # Order all control measures
        all_control_meassures.sort(key=sort_key)

        return DefaultResponse(all_control_meassures).make_response()
    except Exception as err:
        LOGGER.error("[get_isms_soa_report] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the SOA report!")


@isms_report_blueprint.route('/risk_assessments', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@isms_report_blueprint.protect(auth=True, right='base.isms.report.view')
def get_isms_risk_assessments_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve the Statement of Applicability(SOA) report

    Args:
        request_user (CmdbUser): CmdbUser requesting the SOA report

    Returns:
        DefaultResponse: The SOA report as a dictionary
    """
    try:
        risk_assessment_manager: RiskAssessmentManager = ManagerProvider.get_manager(
                                                                            ManagerType.RISK_ASSESSMENT,
                                                                            request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        pipeline = [
            # Step 1: Get all RiskAssessments
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

            # Step 6: Lookup Object or ObjectGroup based on object_id_ref_type
            {
                "$lookup": {
                    "from": "framework.objects",
                    "localField": "object_id",
                    "foreignField": "public_id",
                    "as": "object"
                }
            },
            {
                "$lookup": {
                    "from": "framework.objectGroups",
                    "localField": "object_id",
                    "foreignField": "public_id",
                    "as": "object_group"
                }
            },
            {
                "$lookup": {
                    "from": "framework.types",
                    "localField": "object.type_id",
                    "foreignField": "public_id",
                    "as": "object_type"
                }
            },

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
            }}
        ]

        query_result: list[dict] = list(risk_assessment_manager.aggregate(pipeline))

        # Replace Object public_id with Summary line
        for item in query_result:
            if item.get("assigned_object") and item.get("object_id_ref_type") == "OBJECT":
                try:
                    object_summary = objects_manager.get_summary_line(item["assigned_object"], with_type=False)
                    item["assigned_object"] = object_summary
                except Exception:
                    item["assigned_object"] = "Unknown object"


        return DefaultResponse(query_result).make_response()
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

    # 3. Convert the identifier into a list of integers for numeric sorting
    identifier_sort_value: list[int] = [int(part) if part.isdigit() else part
                                        for part in re.split(r'(\D+|\d+)', identifier or '')]

    return (source_priority, empty_priority, identifier_sort_value)
