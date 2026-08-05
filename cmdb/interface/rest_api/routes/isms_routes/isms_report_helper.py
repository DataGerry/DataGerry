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
# -------------------------------------------------------------------------------------------------------------------- #


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
