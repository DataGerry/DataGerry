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
Shared MongoDB aggregation-pipeline fragments for the ISMS reports

The Risk Treatment Plan and Risk Assessments reports build large aggregation pipelines that share
two identical fragments: resolving the assessed object (object / object group / type label) and
resolving each risk_calculation matrix cell to its risk class. These builders keep both reports in
sync from a single definition.
"""
import re
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsRiskClass,
    IsmsRiskMatrix,
)
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
# -------------------------------------------------------------------------------------------------------------------- #

# Resolved (post-lookup) display fields the RiskAssessment report free-text search matches against.
# These are projected field names, so the search stage must run after the report's final $project.
RA_REPORT_SEARCH_FIELDS: list[str] = ["risk_title", "risk_category", "protection_goals"]


def build_ra_report_search_stage(search: str) -> dict[str, Any]:
    """
    Builds a $match stage for a free-text search over the RiskAssessment report's display fields.

    The term is matched case-insensitively as a literal substring (it is regex-escaped) against each
    field in ``RA_REPORT_SEARCH_FIELDS``, OR'd together. ``protection_goals`` is an array of names, so
    the regex matches when any element contains the term. The stage must be appended after the
    report's final $project (so the display fields exist) and before the paging facet, so that both
    the returned page and the reported total reflect the search.

    Args:
        search (str): The free-text search term (already stripped of surrounding whitespace)

    Returns:
        dict[str, Any]: The $match stage matching the term across the searchable display fields
    """
    pattern: str = re.escape(search)

    return {
        "$match": {
            "$or": [
                {field: {"$regex": pattern, "$options": "i"}}
                for field in RA_REPORT_SEARCH_FIELDS
            ]
        }
    }


def build_report_pagination_stages(params: CollectionParameters) -> list[dict[str, Any]]:
    """
    Builds the trailing $sort / $skip / $limit stages that paginate a report pipeline.

    The stages are meant to be appended after the report's final $project so the sort can target the
    projected (display) field names. ``public_id`` is added as a stable tiebreaker whenever it is not
    already the primary sort key, keeping pagination deterministic when two rows share the same sort
    value - the caller must therefore keep ``public_id`` on the documents until after these stages.

    A ``limit`` of ``0`` is the codebase convention for "no limit" (used by the export flow), so no
    ``$limit`` stage is emitted in that case (``{'$limit': 0}`` is rejected by MongoDB).

    Args:
        params (CollectionParameters): Parsed collection parameters (sort, order, skip, limit)

    Returns:
        list[dict[str, Any]]: The $sort / $skip / $limit stages, in pipeline order
    """
    if params.sort == "public_id":
        sort_spec: dict[str, int] = {"public_id": params.order}
    else:
        sort_spec = {params.sort: params.order, "public_id": 1}

    stages: list[dict[str, Any]] = [
        {"$sort": sort_spec},
        {"$skip": params.skip},
    ]

    if params.limit:
        stages.append({"$limit": params.limit})

    return stages


def build_report_facet_stage(params: CollectionParameters) -> dict[str, Any]:
    """
    Builds the final $facet stage that both pages a report pipeline and counts its full result set.

    The ``data`` branch sorts / skips / limits the rows (see ``build_report_pagination_stages``) and
    then drops the ``public_id`` tiebreaker so the row shape stays unchanged. The ``total`` branch
    counts every row that survived the pipeline - deriving the total from the pipeline (rather than a
    plain collection count) keeps it accurate even when an earlier stage drops rows, e.g. a hard
    ``$unwind`` on a lookup that did not resolve.

    The caller must keep ``public_id`` on the documents (project it in the report's own $project) so
    the sort tiebreaker resolves before it is dropped here.

    Args:
        params (CollectionParameters): Pagination, sort and filter parameters for the report

    Returns:
        dict[str, Any]: The $facet stage to append as the report pipeline's final stage
    """
    return {
        "$facet": {
            "data": [
                *build_report_pagination_stages(params),
                {"$project": {"public_id": 0}},
            ],
            "total": [{"$count": "total"}],
        }
    }


def paginate_report_rows(
    rows: list[dict[str, Any]],
    params: CollectionParameters,
) -> tuple[list[dict[str, Any]], int]:
    """
    Slices an already-sorted list of report rows into the requested page.

    Used by reports whose ordering is computed in Python and therefore cannot be expressed as a
    MongoDB ``$sort`` (the SOA report sorts by a resolved label and a natural identifier sort). The
    caller sorts the full list first; this returns the current page plus the total row count. A
    ``limit`` of 0 (the export "all" convention) returns every row.

    Args:
        rows (list[dict[str, Any]]): The full, already-sorted set of report rows
        params (CollectionParameters): Pagination parameters (skip, limit)

    Returns:
        tuple[list[dict[str, Any]], int]: The current page's rows and the total row count
    """
    total: int = len(rows)

    if not params.limit:
        return rows, total

    return rows[params.skip:params.skip + params.limit], total


def extract_report_page(aggregation_result: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Splits the single document produced by a ``build_report_facet_stage`` pipeline into its parts.

    Args:
        aggregation_result (list[dict[str, Any]]): Materialised result of the faceted report pipeline

    Returns:
        tuple[list[dict[str, Any]], int]: The current page's rows and the total number of matching rows
    """
    if not aggregation_result:
        return [], 0

    facet_doc = aggregation_result[0]
    rows: list[dict[str, Any]] = facet_doc.get("data", [])
    total_bucket: list[dict[str, Any]] = facet_doc.get("total", [])
    total: int = total_bucket[0]["total"] if total_bucket else 0

    return rows, total


def object_reference_lookup_stages() -> list[dict[str, Any]]:
    """
    Builds the $lookup stages resolving a RiskAssessment's assessed object.

    Joins the CmdbObject (``object``), the CmdbObjectGroup (``object_group``) and, for objects, the
    CmdbType (``object_type``) — the caller's projection picks the right one via object_id_ref_type.

    Returns:
        list[dict[str, Any]]: The object / object group / type $lookup stages
    """
    return [
        {
            "$lookup": {
                "from": CmdbObject.COLLECTION,
                "localField": "object_id",
                "foreignField": "public_id",
                "as": "object"
            }
        },
        {
            "$lookup": {
                "from": CmdbObjectGroup.COLLECTION,
                "localField": "object_id",
                "foreignField": "public_id",
                "as": "object_group"
            }
        },
        {
            "$lookup": {
                "from": CmdbType.COLLECTION,
                "localField": "object.type_id",
                "foreignField": "public_id",
                "as": "object_type"
            }
        },
    ]


def risk_matrix_class_lookup_stages(calculation_field: str, cell_field: str, class_field: str) -> list[dict[str, Any]]:
    """
    Builds the stages resolving one risk_calculation matrix to its matrix cell and risk class.

    For the given ``risk_calculation_before``/``risk_calculation_after`` field it joins the
    RiskMatrix singleton (public_id 1) on (likelihood_id, maximum_impact_id) to the matching cell
    (``cell_field``) and then that cell's IsmsRiskClass (``class_field``).

    Args:
        calculation_field (str): 'risk_calculation_before' or 'risk_calculation_after'
        cell_field (str): Output field for the matched matrix cell (e.g. 'risk_before')
        class_field (str): Output field for the cell's risk class (e.g. 'risk_before_class')

    Returns:
        list[dict[str, Any]]: The matrix-cell + risk-class $lookup / $unwind stages
    """
    return [
        {
            "$lookup": {
                "from": IsmsRiskMatrix.COLLECTION,
                "let": {
                    "likelihood_id": f"${calculation_field}.likelihood_id",
                    "impact_id": f"${calculation_field}.maximum_impact_id"
                },
                "pipeline": [
                    {"$match": {"public_id": 1}},
                    {"$unwind": "$risk_matrix"},
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$risk_matrix.likelihood_id", "$$likelihood_id"]},
                                    {"$eq": ["$risk_matrix.impact_id", "$$impact_id"]}
                                ]
                            }
                        }
                    },
                    {"$replaceRoot": {"newRoot": "$risk_matrix"}}
                ],
                "as": cell_field
            }
        },
        {"$unwind": {"path": f"${cell_field}", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": IsmsRiskClass.COLLECTION,
                "localField": f"{cell_field}.risk_class_id",
                "foreignField": "public_id",
                "as": class_field
            }
        },
        {"$unwind": {"path": f"${class_field}", "preserveNullAndEmptyArrays": True}},
    ]

def risk_assessment_report_stages() -> list[dict[str, Any]]:
    """
    Builds the RiskAssessment report's resolve phase: every $lookup, $unwind and rollup stage

    Extracted verbatim from ``get_isms_risk_assessments_report``, which was a ~570-line function that
    was almost entirely this literal. The block is one phase and is kept as one builder on purpose:
    the two impact-category rollups are `$unwind` / `$lookup` / `$group` / `$replaceRoot` sequences
    whose stages only mean anything adjacent to each other, so splitting them further would invite a
    reordering that MongoDB would accept and answer wrongly.

    Runs after the report's opening ``$match`` and before
    ``risk_assessment_report_projection_stage()``.

    Returns:
        list[dict[str, Any]]: The lookup / unwind / rollup stages, in pipeline order
    """
    return [
        # Step 2: Lookup assigned Risk
        {"$lookup": {
            "from": IsmsRisk.COLLECTION,
            "localField": "risk_id",
            "foreignField": "public_id",
            "as": "risk"
        }},
        {"$unwind": "$risk"},

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

        # Step 4: Lookup Protection Goals
        {"$lookup": {
            "from": IsmsProtectionGoal.COLLECTION,
            "localField": "risk.protection_goals",
            "foreignField": "public_id",
            "as": "protection_goals"
        }},

        # Step 5: Lookup Implementation Status
        {
            "$lookup": {
                "from": CmdbExtendableOption.COLLECTION,
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
                "from": CmdbPerson.COLLECTION,
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
                "from": CmdbPerson.COLLECTION,
                "localField": "risk_owner_id",
                "foreignField": "public_id",
                "as": "risk_owner_person"
            }
        },
        {
            "$lookup": {
                "from": CmdbPersonGroup.COLLECTION,
                "localField": "risk_owner_id",
                "foreignField": "public_id",
                "as": "risk_owner_group"
            }
        },

        # Step 9: Lookup Responsible Person (P or PG)
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

        # Step 10: Lookup Auditor (P or PG)
        {
            "$lookup": {
                "from": CmdbPerson.COLLECTION,
                "localField": "auditor_id",
                "foreignField": "public_id",
                "as": "auditor_person"
            }
        },
        {
            "$lookup": {
                "from": CmdbPersonGroup.COLLECTION,
                "localField": "auditor_id",
                "foreignField": "public_id",
                "as": "auditor_group"
            }
        },

        # Step 11: Lookup Interviewed Persons (multiple P)
        {"$lookup": {
            "from": CmdbPerson.COLLECTION,
            "localField": "interviewed_persons",
            "foreignField": "public_id",
            "as": "interviewed_persons_data"
        }},

        # Step 12: Lookup risk class matrix values for risk_before
        {
            "$lookup": {
                "from": IsmsRiskMatrix.COLLECTION,
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
                "from": IsmsRiskClass.COLLECTION,
                "localField": "risk_before.risk_class_id",
                "foreignField": "public_id",
                "as": "risk_before_class"
            }
        },
        { "$unwind": { "path": "$risk_before_class", "preserveNullAndEmptyArrays": True } },

        # Step 13: Repeat for risk after treatment
        {
            "$lookup": {
                "from": IsmsRiskMatrix.COLLECTION,
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
                "from": IsmsRiskClass.COLLECTION,
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
            "from": IsmsImpactCategory.COLLECTION,
            "localField": "risk_calculation_before.impacts.impact_category_id",
            "foreignField": "public_id",
            "as": "impact_category_before"
        }
        },
        { "$unwind": { "path": "$impact_category_before", "preserveNullAndEmptyArrays": True } },

        # Step C: Lookup impact
        {
        "$lookup": {
            "from": IsmsImpact.COLLECTION,
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
            "from": IsmsImpactCategory.COLLECTION,
            "localField": "risk_calculation_after.impacts.impact_category_id",
            "foreignField": "public_id",
            "as": "impact_category_after"
        }
        },
        { "$unwind": { "path": "$impact_category_after", "preserveNullAndEmptyArrays": True } },

        # Step C: Lookup impact
        {
        "$lookup": {
            "from": IsmsImpact.COLLECTION,
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
            "from": IsmsLikelihood.COLLECTION,
            "localField": "risk_calculation_before.likelihood_id",
            "foreignField": "public_id",
            "as": "likelihood_before"
        }
        },
        { "$unwind": { "path": "$likelihood_before", "preserveNullAndEmptyArrays": True } },

        # Lookup Likelihood after
        {
        "$lookup": {
            "from": IsmsLikelihood.COLLECTION,
            "localField": "risk_calculation_after.likelihood_id",
            "foreignField": "public_id",
            "as": "likelihood_after"
        }
        },
        { "$unwind": { "path": "$likelihood_after", "preserveNullAndEmptyArrays": True } },

    ]


def risk_assessment_report_projection_stage() -> dict[str, Any]:
    """
    Builds the RiskAssessment report's final $project - the report's display contract

    Every key here is a field the frontend's table and its exports read, which is why the search and
    the column filters are applied AFTER this stage: they target these resolved names, not the raw
    document's. ``public_id`` is kept only as the pagination sort tiebreaker and dropped again by the
    facet stage.

    Returns:
        dict[str, Any]: The $project stage
    """
    return {"$project": {
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
        **risk_calculation_projection_fields(),
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

def build_report_filter_stages(report_filter: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """
    Turns a ``?filter=`` value into pipeline stages, accepting both shapes the API supports

    ``CollectionParameters`` documents the filter as ``dict | list[dict]``, and that is how the rest of
    the backend reads it: ``BaseQueryBuilder.__init_query`` treats a dict as one ``$match`` and a list
    as stages to splice in, and ``objects_routes`` branches on both. The report routes used to wrap the
    value in ``{"$match": ...}`` unconditionally, so a list produced ``{"$match": [...]}``, which
    MongoDB rejects - a documented filter shape answered 500.

    Args:
        report_filter (dict | list[dict] | None): The parsed ``?filter=`` value

    Returns:
        list[dict[str, Any]]: Zero, one or many stages to append to a report pipeline
    """
    if not report_filter:
        return []

    if isinstance(report_filter, list):
        return list(report_filter)

    return [{"$match": report_filter}]

def risk_calculation_projection_fields() -> dict[str, Any]:
    """
    Builds the ``risk_before`` / ``risk_after`` projection fields both risk reports display

    The two reports show the same pair of risk-class badges - value, class id and colour, before and
    after treatment - and carried byte-identical copies of this block, which only became visible to
    pylint when the RiskAssessment projection moved out of its route.

    Only ``risk_after`` is wrapped in ``$ifNull``: an assessment that has not been treated yet has no
    after-calculation, and the frontend renders those nulls as an empty badge rather than as a zero.

    Splice it into a ``$project`` with ``**`` - it is a fragment, not a stage.

    Returns:
        dict[str, Any]: The two projection fields
    """
    return {
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
    }
