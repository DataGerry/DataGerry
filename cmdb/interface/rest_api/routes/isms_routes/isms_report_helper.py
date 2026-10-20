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

Every stage is built with its `Builder` constructor. Stored keys are spelled through the owning model's
key enum, and the join aliases and response keys through the enums in `isms_report_constants`
"""
import re
from typing import Any

from cmdb.utils import Builder
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    CALCULATION_BASIS_SEPARATOR,
    INTERVIEWED_PERSON_VARIABLE,
    MATRIX_CELL_IMPACT_VARIABLE,
    MATRIX_CELL_LIKELIHOOD_VARIABLE,
    OBJECT_GROUP_TYPE_LABEL,
    PRIORITY_LABELS,
    PROTECTION_GOAL_VARIABLE,
    UNKNOWN_OBJECT_GROUP_LABEL,
    UNKNOWN_OBJECT_LABEL,
    ImpactCategoryRowKey,
    ReportAlias,
    ReportFacetKey,
    RiskAssessmentReportKey,
    RiskBadgeKey,
)
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsRiskClass,
    IsmsRiskMatrix,
)
from cmdb.models.isms_model.isms_impact_category_constants import ImpactCategoryKey
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.models.isms_model.isms_likelihood_constants import LikelihoodKey
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_class_constants import RiskClassKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.isms_model.isms_risk_matrix_constants import (
    RISK_MATRIX_PUBLIC_ID,
    RiskMatrixCellKey,
    RiskMatrixKey,
)
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey
from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectGroupKey, ObjectReferenceType
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey, PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

# Resolved (post-lookup) display fields the RiskAssessment report free-text search matches against.
# These are projected field names, so the search stage must run after the report's final $project.
RA_REPORT_SEARCH_FIELDS: list[str] = [
    RiskAssessmentReportKey.RISK_TITLE.value,
    RiskAssessmentReportKey.RISK_CATEGORY.value,
    RiskAssessmentReportKey.PROTECTION_GOALS.value,
]

# The report search matches case-insensitively only
RA_REPORT_SEARCH_OPTIONS: str = 'i'


def field_path(*parts: str) -> str:
    """
    Joins keys into a dotted field path

    Args:
        *parts (str): The keys, outermost first (`ReportAlias.RISK, RiskKey.NAME`)

    Returns:
        str: The plain-string path (`'risk.name'`)
    """
    return '.'.join(parts)


def field_reference(*parts: str) -> str:
    """
    Joins keys into an aggregation field reference - a dotted path behind a `$`

    Args:
        *parts (str): The keys, outermost first (`ReportAlias.RISK, RiskKey.NAME`)

    Returns:
        str: The plain-string reference (`'$risk.name'`)
    """
    return f'${field_path(*parts)}'


def variable_reference(*parts: str) -> str:
    """
    Joins a variable name and keys into an aggregation variable reference - a dotted path behind `$$`

    Args:
        *parts (str): The variable name, then the keys read off it (`'pg', ProtectionGoalKey.NAME`)

    Returns:
        str: The plain-string reference (`'$$pg.name'`)
    """
    return f'$${field_path(*parts)}'


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

    return Builder.match_(
        Builder.or_([
            Builder.regex_(field, pattern, RA_REPORT_SEARCH_OPTIONS)
            for field in RA_REPORT_SEARCH_FIELDS
        ])
    )


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
    public_id: str = RiskAssessmentKey.PUBLIC_ID.value

    if params.sort == public_id:
        sort_spec: dict[str, int] = {public_id: params.order}
    else:
        sort_spec = {params.sort: params.order, public_id: 1}

    stages: list[dict[str, Any]] = [
        Builder.sort_(sort_spec),
        Builder.skip_(params.skip),
    ]

    if params.limit:
        stages.append(Builder.limit_(params.limit))

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
    return Builder.facet_({
        ReportFacetKey.DATA.value: [
            *build_report_pagination_stages(params),
            Builder.project_({RiskAssessmentKey.PUBLIC_ID.value: 0}),
        ],
        ReportFacetKey.TOTAL.value: [Builder.count_(ReportFacetKey.TOTAL.value)],
    })


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
    rows: list[dict[str, Any]] = facet_doc.get(ReportFacetKey.DATA.value, [])
    total_bucket: list[dict[str, Any]] = facet_doc.get(ReportFacetKey.TOTAL.value, [])
    total: int = total_bucket[0][ReportFacetKey.TOTAL.value] if total_bucket else 0

    return rows, total


def risk_reference_lookup_stages() -> list[dict[str, Any]]:
    """
    Builds the stages resolving a RiskAssessment's Risk (``risk``), its category (``risk_category``) and its
    protection goals (``protection_goals``) - the same block in both risk reports

    The risk is kept when it no longer resolves: both reports then list the same assessments, and a total
    that silently drops one is worse than a row whose risk columns are blank

    Returns:
        list[dict[str, Any]]: The risk / category / protection-goal $lookup and $unwind stages
    """
    return [
        Builder.lookup_(
            IsmsRisk.COLLECTION,
            RiskAssessmentKey.RISK_ID.value,
            RiskKey.PUBLIC_ID.value,
            ReportAlias.RISK.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK), "preserveNullAndEmptyArrays": True}),
        Builder.lookup_(
            CmdbExtendableOption.COLLECTION,
            field_path(ReportAlias.RISK, RiskKey.CATEGORY_ID),
            ExtendableOptionKey.PUBLIC_ID.value,
            ReportAlias.RISK_CATEGORY.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK_CATEGORY), "preserveNullAndEmptyArrays": True}),
        Builder.lookup_(
            IsmsProtectionGoal.COLLECTION,
            field_path(ReportAlias.RISK, RiskKey.PROTECTION_GOALS),
            ProtectionGoalKey.PUBLIC_ID.value,
            ReportAlias.PROTECTION_GOALS.value,
        ),
    ]


def implementation_status_lookup_stages() -> list[dict[str, Any]]:
    """
    Builds the stages resolving a RiskAssessment's implementation status (``implementation_status``), an
    ExtendableOption - the same block in both risk reports

    Returns:
        list[dict[str, Any]]: The $lookup and the null-preserving $unwind
    """
    return [
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
    ]


def object_reference_lookup_stages() -> list[dict[str, Any]]:
    """
    Builds the $lookup stages resolving a RiskAssessment's assessed object.

    Joins the CmdbObject (``object``), the CmdbObjectGroup (``object_group``) and, for objects, the
    CmdbType (``object_type``) — ``assessed_object_projection`` / ``assessed_object_type_projection`` pick
    the right one via object_id_ref_type. Each join keeps only the one key the report reads: the object's
    ``type_id``, the group's ``name`` and the type's ``label`` - a CmdbObject carries its whole ``fields``
    array, and none of it is shown here

    Returns:
        list[dict[str, Any]]: The object / object group / type $lookup stages
    """
    return [
        Builder.lookup_(
            CmdbObject.COLLECTION,
            RiskAssessmentKey.OBJECT_ID.value,
            CmdbObjectKey.PUBLIC_ID.value,
            ReportAlias.OBJECT.value,
            pipeline=[Builder.project_({MONGO_ID_FIELD: 0, CmdbObjectKey.TYPE_ID.value: 1})],
        ),
        Builder.lookup_(
            CmdbObjectGroup.COLLECTION,
            RiskAssessmentKey.OBJECT_ID.value,
            ObjectGroupKey.PUBLIC_ID.value,
            ReportAlias.OBJECT_GROUP.value,
            pipeline=[Builder.project_({MONGO_ID_FIELD: 0, ObjectGroupKey.NAME.value: 1})],
        ),
        Builder.lookup_(
            CmdbType.COLLECTION,
            field_path(ReportAlias.OBJECT, CmdbObjectKey.TYPE_ID),
            TypeSchemaKey.PUBLIC_ID.value,
            ReportAlias.OBJECT_TYPE.value,
            pipeline=[Builder.project_({MONGO_ID_FIELD: 0, TypeSchemaKey.LABEL.value: 1})],
        ),
    ]


def is_object_group_reference() -> dict[str, Any]:
    """
    The expression telling an assessment of an object group from one of an object

    Anything but OBJECT_GROUP is an object - a legacy assessment without ``object_id_ref_type`` included,
    the same reading ``resolve_assessed_objects`` applies afterwards

    Returns:
        dict[str, Any]: An ``$eq`` expression over the assessment's ``object_id_ref_type``
    """
    return {"$eq": [field_reference(RiskAssessmentKey.OBJECT_ID_REF_TYPE), ObjectReferenceType.OBJECT_GROUP.value]}


def assessed_object_projection() -> dict[str, Any]:
    """
    The projected value of a report's object column, before ``resolve_assessed_objects`` names it

    A group row carries the group's name, absent when the group no longer exists. An object row carries
    the assessment's OWN ``object_id``, not the joined object's: the id survives the object's deletion,
    so the resolver can label the row 'Unknown object' instead of leaving it blank

    Returns:
        dict[str, Any]: A ``$cond`` expression for a ``$project``
    """
    return {
        "$cond": [
            is_object_group_reference(),
            {"$arrayElemAt": [field_reference(ReportAlias.OBJECT_GROUP, ObjectGroupKey.NAME), 0]},
            field_reference(RiskAssessmentKey.OBJECT_ID),
        ]
    }


def assessed_object_type_projection() -> dict[str, Any]:
    """
    The projected value of a report's object-type column: 'Object group', or the object's type label

    Returns:
        dict[str, Any]: A ``$cond`` expression for a ``$project``; absent for an object that no longer resolves
    """
    return {
        "$cond": [
            is_object_group_reference(),
            OBJECT_GROUP_TYPE_LABEL,
            {"$arrayElemAt": [field_reference(ReportAlias.OBJECT_TYPE, TypeSchemaKey.LABEL), 0]},
        ]
    }


def resolve_assessed_objects(rows: list[dict[str, Any]], object_key: str, objects_manager: Any) -> None:
    """
    Names every report row's assessed object, then drops the row's ``object_id_ref_type``

    An object row's id is replaced by the object's summary line, the whole page resolved in a single batch;
    an id that no longer resolves becomes 'Unknown object'. A group row whose group no longer exists - its
    name projected absent - becomes 'Unknown object group'. A row with no assessed object at all is left
    as it is. The discriminator is internal: both reports answer without it, and it stays available to
    ``?filter=`` and ``?sort=``, which run inside the aggregation

    Args:
        rows (list[dict[str, Any]]): The report page, enriched in place
        object_key (str): The key of the row's object column
        objects_manager (Any): The ObjectsManager the summary lines are read through
    """
    object_rows: list[dict[str, Any]] = [
        row for row in rows
        if row.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value) != ObjectReferenceType.OBJECT_GROUP
        and _is_object_id(row.get(object_key))
    ]

    summaries: dict[int, str] = objects_manager.get_summary_lines_lookup(
        [row[object_key] for row in object_rows], with_type=False,
    ) if object_rows else {}

    for row in object_rows:
        row[object_key] = summaries.get(row[object_key], UNKNOWN_OBJECT_LABEL)

    for row in rows:
        if row.pop(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value, None) == ObjectReferenceType.OBJECT_GROUP \
                and row.get(object_key) is None:
            row[object_key] = UNKNOWN_OBJECT_GROUP_LABEL


def _is_object_id(value: Any) -> bool:
    """
    Tells whether a projected object column still holds an object's public_id

    Args:
        value (Any): The column's value

    Returns:
        bool: True for an integer that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


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
        Builder.correlated_lookup_(
            IsmsRiskMatrix.COLLECTION,
            {
                MATRIX_CELL_LIKELIHOOD_VARIABLE: field_reference(calculation_field, RiskCalculationKey.LIKELIHOOD_ID),
                MATRIX_CELL_IMPACT_VARIABLE: field_reference(calculation_field, RiskCalculationKey.MAXIMUM_IMPACT_ID),
            },
            [
                Builder.match_({RiskMatrixKey.PUBLIC_ID.value: RISK_MATRIX_PUBLIC_ID}),
                Builder.unwind_(field_reference(RiskMatrixKey.RISK_MATRIX)),
                Builder.match_({
                    "$expr": {
                        "$and": [
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.LIKELIHOOD_ID),
                                variable_reference(MATRIX_CELL_LIKELIHOOD_VARIABLE),
                            ]},
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.IMPACT_ID),
                                variable_reference(MATRIX_CELL_IMPACT_VARIABLE),
                            ]},
                        ]
                    }
                }),
                Builder.replace_root_(field_reference(RiskMatrixKey.RISK_MATRIX)),
            ],
            cell_field,
        ),
        Builder.unwind_({"path": field_reference(cell_field), "preserveNullAndEmptyArrays": True}),
        Builder.lookup_(
            IsmsRiskClass.COLLECTION,
            field_path(cell_field, RiskMatrixCellKey.RISK_CLASS_ID),
            RiskClassKey.PUBLIC_ID.value,
            class_field,
        ),
        Builder.unwind_({"path": field_reference(class_field), "preserveNullAndEmptyArrays": True}),
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
    before: str = RiskAssessmentKey.RISK_CALCULATION_BEFORE.value
    after: str = RiskAssessmentKey.RISK_CALCULATION_AFTER.value

    return [
        # Steps 2-4: the assessed Risk, its category label and its protection goals
        *risk_reference_lookup_stages(),

        # Step 5: Lookup Implementation Status
        *implementation_status_lookup_stages(),

        # Lookup Object / ObjectGroup / type label for the assessed object
        *object_reference_lookup_stages(),

        # Step 7: Lookup the Risk Assessor (P)
        Builder.lookup_(
            CmdbPerson.COLLECTION,
            RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            PersonKey.PUBLIC_ID.value,
            ReportAlias.RISK_ASSESSOR_PERSON.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.RISK_ASSESSOR_PERSON),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step 8: Lookup Risk Owner (P or PG)
        Builder.lookup_(
            CmdbPerson.COLLECTION,
            RiskAssessmentKey.RISK_OWNER_ID.value,
            PersonKey.PUBLIC_ID.value,
            ReportAlias.RISK_OWNER_PERSON.value,
        ),
        Builder.lookup_(
            CmdbPersonGroup.COLLECTION,
            RiskAssessmentKey.RISK_OWNER_ID.value,
            PersonGroupKey.PUBLIC_ID.value,
            ReportAlias.RISK_OWNER_GROUP.value,
        ),

        # Step 9: Lookup Responsible Person (P or PG)
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

        # Step 10: Lookup Auditor (P or PG)
        Builder.lookup_(
            CmdbPerson.COLLECTION,
            RiskAssessmentKey.AUDITOR_ID.value,
            PersonKey.PUBLIC_ID.value,
            ReportAlias.AUDITOR_PERSON.value,
        ),
        Builder.lookup_(
            CmdbPersonGroup.COLLECTION,
            RiskAssessmentKey.AUDITOR_ID.value,
            PersonGroupKey.PUBLIC_ID.value,
            ReportAlias.AUDITOR_GROUP.value,
        ),

        # Step 11: Lookup Interviewed Persons (multiple P)
        Builder.lookup_(
            CmdbPerson.COLLECTION,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value,
            PersonKey.PUBLIC_ID.value,
            ReportAlias.INTERVIEWED_PERSONS_DATA.value,
        ),

        # Step 12: Lookup risk class matrix values for risk_before
        Builder.correlated_lookup_(
            IsmsRiskMatrix.COLLECTION,
            {
                MATRIX_CELL_LIKELIHOOD_VARIABLE: field_reference(before, RiskCalculationKey.LIKELIHOOD_ID),
                MATRIX_CELL_IMPACT_VARIABLE: field_reference(before, RiskCalculationKey.MAXIMUM_IMPACT_ID),
            },
            [
                Builder.match_({RiskMatrixKey.PUBLIC_ID.value: RISK_MATRIX_PUBLIC_ID}),
                Builder.unwind_(field_reference(RiskMatrixKey.RISK_MATRIX)),
                Builder.match_({
                    "$expr": {
                        "$and": [
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.LIKELIHOOD_ID),
                                variable_reference(MATRIX_CELL_LIKELIHOOD_VARIABLE),
                            ]},
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.IMPACT_ID),
                                variable_reference(MATRIX_CELL_IMPACT_VARIABLE),
                            ]},
                        ]
                    }
                }),
                Builder.replace_root_(field_reference(RiskMatrixKey.RISK_MATRIX)),
            ],
            ReportAlias.RISK_BEFORE.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK_BEFORE), "preserveNullAndEmptyArrays": True}),
        Builder.lookup_(
            IsmsRiskClass.COLLECTION,
            field_path(ReportAlias.RISK_BEFORE, RiskMatrixCellKey.RISK_CLASS_ID),
            RiskClassKey.PUBLIC_ID.value,
            ReportAlias.RISK_BEFORE_CLASS.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.RISK_BEFORE_CLASS),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step 13: Repeat for risk after treatment
        Builder.correlated_lookup_(
            IsmsRiskMatrix.COLLECTION,
            {
                MATRIX_CELL_LIKELIHOOD_VARIABLE: field_reference(after, RiskCalculationKey.LIKELIHOOD_ID),
                MATRIX_CELL_IMPACT_VARIABLE: field_reference(after, RiskCalculationKey.MAXIMUM_IMPACT_ID),
            },
            [
                Builder.match_({RiskMatrixKey.PUBLIC_ID.value: RISK_MATRIX_PUBLIC_ID}),
                Builder.unwind_(field_reference(RiskMatrixKey.RISK_MATRIX)),
                Builder.match_({
                    "$expr": {
                        "$and": [
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.LIKELIHOOD_ID),
                                variable_reference(MATRIX_CELL_LIKELIHOOD_VARIABLE),
                            ]},
                            {"$eq": [
                                field_reference(RiskMatrixKey.RISK_MATRIX, RiskMatrixCellKey.IMPACT_ID),
                                variable_reference(MATRIX_CELL_IMPACT_VARIABLE),
                            ]},
                        ]
                    }
                }),
                Builder.replace_root_(field_reference(RiskMatrixKey.RISK_MATRIX)),
            ],
            ReportAlias.RISK_AFTER.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.RISK_AFTER), "preserveNullAndEmptyArrays": True}),
        Builder.lookup_(
            IsmsRiskClass.COLLECTION,
            field_path(ReportAlias.RISK_AFTER, RiskMatrixCellKey.RISK_CLASS_ID),
            RiskClassKey.PUBLIC_ID.value,
            ReportAlias.RISK_AFTER_CLASS.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.RISK_AFTER_CLASS),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step 14: Create Impact categories before list
        # Step A: Unwind before impacts
        Builder.unwind_({
            "path": field_reference(before, RiskCalculationKey.IMPACTS),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step B: Lookup impact category
        Builder.lookup_(
            IsmsImpactCategory.COLLECTION,
            field_path(before, RiskCalculationKey.IMPACTS, RiskCalculationKey.IMPACT_CATEGORY_ID),
            ImpactCategoryKey.PUBLIC_ID.value,
            ReportAlias.IMPACT_CATEGORY_BEFORE.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.IMPACT_CATEGORY_BEFORE),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step C: Lookup impact
        Builder.lookup_(
            IsmsImpact.COLLECTION,
            field_path(before, RiskCalculationKey.IMPACTS, RiskCalculationKey.IMPACT_ID),
            ImpactKey.PUBLIC_ID.value,
            ReportAlias.IMPACT_BEFORE.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.IMPACT_BEFORE), "preserveNullAndEmptyArrays": True}),

        # Step D: Group and build new array
        Builder.group_("$_id", {
            ReportAlias.DOC.value: {"$first": "$$ROOT"},
            RiskAssessmentReportKey.IMPACT_CATEGORIES_BEFORE.value: {
                "$push": {
                    ImpactCategoryRowKey.IMPACT_CATEGORY.value: field_reference(
                        ReportAlias.IMPACT_CATEGORY_BEFORE, ImpactCategoryKey.NAME
                    ),
                    ImpactCategoryRowKey.IMPACT_VALUE.value: {
                        "$cond": {
                            "if": {"$and": [
                                {"$ne": [
                                    field_reference(ReportAlias.IMPACT_BEFORE, ImpactKey.CALCULATION_BASIS), None
                                ]},
                                {"$ne": [field_reference(ReportAlias.IMPACT_BEFORE, ImpactKey.NAME), None]}]
                            },
                            "then": {
                                "$concat": [
                                    {"$toString": field_reference(
                                        ReportAlias.IMPACT_BEFORE, ImpactKey.CALCULATION_BASIS
                                    )},
                                    CALCULATION_BASIS_SEPARATOR,
                                    field_reference(ReportAlias.IMPACT_BEFORE, ImpactKey.NAME)
                                ]
                            },
                            "else": None
                        }
                    }
                }
            }
        }),
        Builder.replace_root_({"$mergeObjects": [field_reference(ReportAlias.DOC), {
            RiskAssessmentReportKey.IMPACT_CATEGORIES_BEFORE.value: field_reference(
                RiskAssessmentReportKey.IMPACT_CATEGORIES_BEFORE
            )}]}),

        # Step 15: Create Impact categories after list
        # Step A: Unwind after impacts
        Builder.unwind_({
            "path": field_reference(after, RiskCalculationKey.IMPACTS),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step B: Lookup impact category
        Builder.lookup_(
            IsmsImpactCategory.COLLECTION,
            field_path(after, RiskCalculationKey.IMPACTS, RiskCalculationKey.IMPACT_CATEGORY_ID),
            ImpactCategoryKey.PUBLIC_ID.value,
            ReportAlias.IMPACT_CATEGORY_AFTER.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.IMPACT_CATEGORY_AFTER),
            "preserveNullAndEmptyArrays": True,
        }),

        # Step C: Lookup impact
        Builder.lookup_(
            IsmsImpact.COLLECTION,
            field_path(after, RiskCalculationKey.IMPACTS, RiskCalculationKey.IMPACT_ID),
            ImpactKey.PUBLIC_ID.value,
            ReportAlias.IMPACT_AFTER.value,
        ),
        Builder.unwind_({"path": field_reference(ReportAlias.IMPACT_AFTER), "preserveNullAndEmptyArrays": True}),

        # Step D: Group and build new array
        Builder.group_("$_id", {
            ReportAlias.DOC.value: {"$first": "$$ROOT"},
            RiskAssessmentReportKey.IMPACT_CATEGORIES_AFTER.value: {
                "$push": {
                    ImpactCategoryRowKey.IMPACT_CATEGORY.value: field_reference(
                        ReportAlias.IMPACT_CATEGORY_AFTER, ImpactCategoryKey.NAME
                    ),
                    ImpactCategoryRowKey.IMPACT_VALUE.value: {
                        "$cond": {
                            "if": {"$and": [
                                {"$ne": [
                                    field_reference(ReportAlias.IMPACT_AFTER, ImpactKey.CALCULATION_BASIS), None
                                ]},
                                {"$ne": [field_reference(ReportAlias.IMPACT_AFTER, ImpactKey.NAME), None]}]
                            },
                            "then": {
                                "$concat": [
                                    {"$toString": field_reference(
                                        ReportAlias.IMPACT_AFTER, ImpactKey.CALCULATION_BASIS
                                    )},
                                    CALCULATION_BASIS_SEPARATOR,
                                    field_reference(ReportAlias.IMPACT_AFTER, ImpactKey.NAME)
                                ]
                            },
                            "else": None
                        }
                    }
                }
            }
        }),
        Builder.replace_root_({"$mergeObjects": [field_reference(ReportAlias.DOC), {
            RiskAssessmentReportKey.IMPACT_CATEGORIES_AFTER.value: field_reference(
                RiskAssessmentReportKey.IMPACT_CATEGORIES_AFTER
            )}]}),

        # Lookup Likelihood before
        Builder.lookup_(
            IsmsLikelihood.COLLECTION,
            field_path(before, RiskCalculationKey.LIKELIHOOD_ID),
            LikelihoodKey.PUBLIC_ID.value,
            ReportAlias.LIKELIHOOD_BEFORE.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.LIKELIHOOD_BEFORE),
            "preserveNullAndEmptyArrays": True,
        }),

        # Lookup Likelihood after
        Builder.lookup_(
            IsmsLikelihood.COLLECTION,
            field_path(after, RiskCalculationKey.LIKELIHOOD_ID),
            LikelihoodKey.PUBLIC_ID.value,
            ReportAlias.LIKELIHOOD_AFTER.value,
        ),
        Builder.unwind_({
            "path": field_reference(ReportAlias.LIKELIHOOD_AFTER),
            "preserveNullAndEmptyArrays": True,
        }),

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
    return Builder.project_({
        "_id": 0,
        # Kept only as the pagination sort tiebreaker; dropped again after paging
        RiskAssessmentKey.PUBLIC_ID.value: 1,
        RiskAssessmentReportKey.RISK_TITLE.value: field_reference(ReportAlias.RISK, RiskKey.NAME),
        RiskAssessmentReportKey.RISK_CATEGORY.value: field_reference(
            ReportAlias.RISK_CATEGORY, ExtendableOptionKey.VALUE
        ),
        RiskAssessmentReportKey.PROTECTION_GOALS.value: {
            "$map": {
                "input": field_reference(ReportAlias.PROTECTION_GOALS),
                "as": PROTECTION_GOAL_VARIABLE,
                "in": variable_reference(PROTECTION_GOAL_VARIABLE, ProtectionGoalKey.NAME)
            }
        },
        RiskAssessmentReportKey.RISK_OWNER.value: {
            "$cond": [
                {"$eq": [field_reference(RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE), PersonReferenceType.PERSON.value]},
                {
                    "$ifNull": [
                        {"$arrayElemAt": [field_reference(ReportAlias.RISK_OWNER_PERSON, PersonKey.DISPLAY_NAME), 0]},
                        None
                    ]
                },
                {
                    "$ifNull": [
                        {"$arrayElemAt": [field_reference(ReportAlias.RISK_OWNER_GROUP, PersonGroupKey.NAME), 0]},
                        None
                    ]
                }
            ]
        },
        RiskAssessmentReportKey.RESPONSIBLE_PERSON.value: {
            "$cond": [
                {"$eq": [
                    field_reference(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE),
                    PersonReferenceType.PERSON.value,
                ]},
                {
                    "$ifNull": [
                        {"$arrayElemAt": [field_reference(ReportAlias.RESPONSIBLE_PERSON, PersonKey.DISPLAY_NAME), 0]},
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
        RiskAssessmentReportKey.AUDITOR.value: {
            "$cond": [
                {"$eq": [field_reference(RiskAssessmentKey.AUDITOR_ID_REF_TYPE), PersonReferenceType.PERSON.value]},
                {
                    "$ifNull": [
                        {"$arrayElemAt": [field_reference(ReportAlias.AUDITOR_PERSON, PersonKey.DISPLAY_NAME), 0]},
                        None
                    ]
                },
                {
                    "$ifNull": [
                        {"$arrayElemAt": [field_reference(ReportAlias.AUDITOR_GROUP, PersonGroupKey.NAME), 0]},
                        None
                    ]
                }
            ]
        },
        RiskAssessmentReportKey.IMPLEMENTATION_STATUS.value: {
            "$ifNull": [field_reference(ReportAlias.IMPLEMENTATION_STATUS, ExtendableOptionKey.VALUE), None]
        },
        RiskAssessmentReportKey.PRIORITY.value: {
            "$switch": {
                "branches": [
                    {"case": {"$eq": [field_reference(RiskAssessmentKey.PRIORITY), priority]}, "then": label}
                    for priority, label in PRIORITY_LABELS.items()
                ],
                "default": None
            }
        },
        RiskAssessmentReportKey.ASSIGNED_OBJECT.value: assessed_object_projection(),
        RiskAssessmentReportKey.ASSIGNED_OBJECT_TYPE.value: assessed_object_type_projection(),
        RiskAssessmentReportKey.RISK_ASSESSOR.value: {
            "$ifNull": [field_reference(ReportAlias.RISK_ASSESSOR_PERSON, PersonKey.DISPLAY_NAME), None]
        },
        RiskAssessmentReportKey.INTERVIEWED_PERSONS.value: {
            "$cond": {
                "if": {"$gt": [{"$size": field_reference(ReportAlias.INTERVIEWED_PERSONS_DATA)}, 0]},
                "then": {
                    "$map": {
                        "input": field_reference(ReportAlias.INTERVIEWED_PERSONS_DATA),
                        "as": INTERVIEWED_PERSON_VARIABLE,
                        "in": variable_reference(INTERVIEWED_PERSON_VARIABLE, PersonKey.DISPLAY_NAME)
                    }
                },
                "else": None
            }
        },
        **risk_calculation_projection_fields(),
        RiskAssessmentReportKey.IMPACT_CATEGORIES_BEFORE.value: 1,
        RiskAssessmentReportKey.IMPACT_CATEGORIES_AFTER.value: 1,
        RiskAssessmentReportKey.LIKELIHOOD_VALUE_BEFORE.value: {
            "$cond": {
                "if": {
                    "$and": [
                        {"$ne": [
                            field_reference(ReportAlias.LIKELIHOOD_BEFORE, LikelihoodKey.CALCULATION_BASIS), None
                        ]},
                        {"$ne": [field_reference(ReportAlias.LIKELIHOOD_BEFORE, LikelihoodKey.NAME), None]}
                    ]
                },
                "then": {
                    "$concat": [
                        {"$toString": field_reference(
                            ReportAlias.LIKELIHOOD_BEFORE, LikelihoodKey.CALCULATION_BASIS
                        )},
                        CALCULATION_BASIS_SEPARATOR,
                        field_reference(ReportAlias.LIKELIHOOD_BEFORE, LikelihoodKey.NAME)
                    ]
                },
                "else": None
            }
        },
        RiskAssessmentReportKey.LIKELIHOOD_VALUE_AFTER.value: {
            "$cond": {
                "if": {
                    "$and": [
                        {"$ne": [
                            field_reference(ReportAlias.LIKELIHOOD_AFTER, LikelihoodKey.CALCULATION_BASIS), None
                        ]},
                        {"$ne": [field_reference(ReportAlias.LIKELIHOOD_AFTER, LikelihoodKey.NAME), None]}
                    ]
                },
                "then": {
                    "$concat": [
                        {"$toString": field_reference(
                            ReportAlias.LIKELIHOOD_AFTER, LikelihoodKey.CALCULATION_BASIS
                        )},
                        CALCULATION_BASIS_SEPARATOR,
                        field_reference(ReportAlias.LIKELIHOOD_AFTER, LikelihoodKey.NAME)
                    ]
                },
                "else": None
            }
        },
        RiskAssessmentReportKey.RISK_TREATMENT_OPTION.value: {
            "$ifNull": [field_reference(RiskAssessmentKey.RISK_TREATMENT_OPTION), None]
        },
        RiskAssessmentKey.RISK_TREATMENT_DESCRIPTION.value: 1,
        RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: 1,
        RiskAssessmentKey.ADDITIONAL_INFO.value: 1,
        RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: 1,
        RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value: 1,
        RiskAssessmentKey.REQUIRED_RESOURCES.value: 1,
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value: 1,
        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION_CURRENCY.value: 1,
        RiskAssessmentKey.AUDIT_DONE_DATE.value: 1,
        RiskAssessmentKey.AUDIT_RESULT.value: 1,
        RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: 1,
    })

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

    return [Builder.match_(report_filter)]

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
        RiskBadgeKey.RISK_BEFORE.value: {
            RiskBadgeKey.VALUE.value: field_reference(ReportAlias.RISK_BEFORE, RiskMatrixCellKey.CALCULATED_VALUE),
            RiskBadgeKey.RISK_CLASS_ID.value: field_reference(ReportAlias.RISK_BEFORE_CLASS, RiskClassKey.PUBLIC_ID),
            RiskBadgeKey.COLOR.value: field_reference(ReportAlias.RISK_BEFORE_CLASS, RiskClassKey.COLOR)
        },
        RiskBadgeKey.RISK_AFTER.value: {
            RiskBadgeKey.VALUE.value: {
                "$ifNull": [field_reference(ReportAlias.RISK_AFTER, RiskMatrixCellKey.CALCULATED_VALUE), None]
            },
            RiskBadgeKey.RISK_CLASS_ID.value: {
                "$ifNull": [field_reference(ReportAlias.RISK_AFTER_CLASS, RiskClassKey.PUBLIC_ID), None]
            },
            RiskBadgeKey.COLOR.value: {
                "$ifNull": [field_reference(ReportAlias.RISK_AFTER_CLASS, RiskClassKey.COLOR), None]
            }
        },
    }
