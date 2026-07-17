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
from typing import Any

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
# -------------------------------------------------------------------------------------------------------------------- #


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
                "from": "isms.riskMatrix",
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
                "from": "isms.riskClass",
                "localField": f"{cell_field}.risk_class_id",
                "foreignField": "public_id",
                "as": class_field
            }
        },
        {"$unwind": {"path": f"${class_field}", "preserveNullAndEmptyArrays": True}},
    ]
