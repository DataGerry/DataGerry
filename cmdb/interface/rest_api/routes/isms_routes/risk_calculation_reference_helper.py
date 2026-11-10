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
The checks a RiskAssessment write's risk calculation passes before anything is written

Both matrices - ``risk_calculation_before`` and ``risk_calculation_after`` - name an IsmsImpactCategory and an
IsmsImpact in every ``impacts`` row, and an IsmsLikelihood. The schema holds each to a whole number from 1 (or null
where the value may be unrated); this module checks that what they name is stored:

- an ImpactCategory is rated at most once per matrix. A category may be missing from a matrix - it reads as
  unrated - but two rows of one category would put it twice into the report and take the higher of the two impacts
- every named ImpactCategory, Impact and Likelihood exists. One 400 names every unknown id with its field path, so
  a client fixes the whole payload at once

Reads: one projected query for the named ImpactCategories, and the two scales the write is derived from anyway
(``RiskAssessmentManager.load_calculation_bases``) - which the check returns, so the caller hands them on to
``recalculate_risk_values`` and the scales are read once per write
"""
from collections import Counter
from logging import Logger, getLogger
from typing import Any, NamedTuple

from flask import abort

from cmdb.manager.isms_manager.isms_manager_helper import RiskCalculationBases
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager

from cmdb.models.isms_model.risk_calculation_constants import RISK_CALCULATION_MATRIX_KEYS, RiskCalculationKey
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    DUPLICATE_IMPACT_CATEGORIES_MSG,
    IMPACT_CATEGORY_LOOKUP_FAILED_MSG,
    MAX_ROWS_PER_IMPACT_CATEGORY,
    RISK_CALCULATION_PATH_SEPARATOR,
    RISK_CALCULATION_REASON,
    RISK_CALCULATION_REASON_SEPARATOR,
    UNKNOWN_RISK_CALCULATION_REFERENCES_MSG,
    RiskCalculationReferenceKind,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


class RiskCalculationReference(NamedTuple):
    """The ids one field path of a risk calculation names, and what they name"""
    field: str
    kind: RiskCalculationReferenceKind
    ids: frozenset[int]


def field_path(*keys: str) -> str:
    """
    The dotted path of a field inside the RiskAssessment document, as the refusals name it

    Args:
        *keys (str): The keys from the document root down

    Returns:
        str: The joined path, e.g. ``risk_calculation_before.impacts.impact_id``
    """
    return RISK_CALCULATION_PATH_SEPARATOR.join(keys)


def present_matrices(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """
    The risk-calculation matrices a payload carries, in document order

    Args:
        data (dict[str, Any]): The validated RiskAssessment payload

    Returns:
        list[tuple[str, dict[str, Any]]]: (matrix key, matrix) for each matrix that is a dict
    """
    return [
        (matrix_key.value, data[matrix_key.value])
        for matrix_key in RISK_CALCULATION_MATRIX_KEYS
        if isinstance(data.get(matrix_key.value), dict)
    ]


def impact_rows(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The ``impacts`` rows of one matrix, leaving out anything that is no row

    Args:
        matrix (dict[str, Any]): One risk-calculation matrix

    Returns:
        list[dict[str, Any]]: Its rows; empty when the matrix holds none
    """
    return [row for row in matrix.get(RiskCalculationKey.IMPACTS.value) or [] if isinstance(row, dict)]


def named_ids(values: list[Any]) -> frozenset[int]:
    """
    The ids among some field values: a null (unrated) value names nothing

    Args:
        values (list[Any]): The values of one field path, already held to the id rule by the schema

    Returns:
        frozenset[int]: The ids named
    """
    return frozenset(value for value in values if value is not None)


def duplicate_impact_categories(matrix: dict[str, Any]) -> list[int]:
    """
    The ImpactCategories one matrix rates more than once

    Args:
        matrix (dict[str, Any]): One risk-calculation matrix

    Returns:
        list[int]: Their ids, sorted; empty when every category is rated at most once
    """
    counts: Counter = Counter(
        row.get(RiskCalculationKey.IMPACT_CATEGORY_ID.value) for row in impact_rows(matrix)
    )

    return sorted(
        category_id for category_id, count in counts.items()
        if category_id is not None and count > MAX_ROWS_PER_IMPACT_CATEGORY
    )


def abort_on_duplicate_impact_categories(data: dict[str, Any]) -> None:
    """
    Refuses a RiskAssessment write that rates one ImpactCategory more than once in a matrix

    Args:
        data (dict[str, Any]): The validated RiskAssessment payload

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming, per matrix, every category rated more than once
    """
    reasons: list[str] = [
        RISK_CALCULATION_REASON.format(
            field=field_path(matrix_key, RiskCalculationKey.IMPACTS.value), ids=duplicates,
        )
        for matrix_key, matrix in present_matrices(data)
        if (duplicates := duplicate_impact_categories(matrix))
    ]

    if reasons:
        abort(400, DUPLICATE_IMPACT_CATEGORIES_MSG.format(reasons=RISK_CALCULATION_REASON_SEPARATOR.join(reasons)))


def collect_risk_calculation_references(data: dict[str, Any]) -> list[RiskCalculationReference]:
    """
    Every id the risk calculation of a payload names, by field path, in document order

    Per matrix: the ImpactCategories and the Impacts of its ``impacts`` rows, then its Likelihood. A field path that
    names nothing is left out

    Args:
        data (dict[str, Any]): The validated RiskAssessment payload

    Returns:
        list[RiskCalculationReference]: One entry per field path naming at least one id
    """
    references: list[RiskCalculationReference] = []

    for matrix_key, matrix in present_matrices(data):
        rows: list[dict[str, Any]] = impact_rows(matrix)
        candidates: list[RiskCalculationReference] = [
            RiskCalculationReference(
                field_path(matrix_key, RiskCalculationKey.IMPACTS.value, RiskCalculationKey.IMPACT_CATEGORY_ID.value),
                RiskCalculationReferenceKind.IMPACT_CATEGORY,
                named_ids([row.get(RiskCalculationKey.IMPACT_CATEGORY_ID.value) for row in rows]),
            ),
            RiskCalculationReference(
                field_path(matrix_key, RiskCalculationKey.IMPACTS.value, RiskCalculationKey.IMPACT_ID.value),
                RiskCalculationReferenceKind.IMPACT,
                named_ids([row.get(RiskCalculationKey.IMPACT_ID.value) for row in rows]),
            ),
            RiskCalculationReference(
                field_path(matrix_key, RiskCalculationKey.LIKELIHOOD_ID.value),
                RiskCalculationReferenceKind.LIKELIHOOD,
                named_ids([matrix.get(RiskCalculationKey.LIKELIHOOD_ID.value)]),
            ),
        ]
        references.extend(reference for reference in candidates if reference.ids)

    return references


def ids_of_kind(references: list[RiskCalculationReference], kind: RiskCalculationReferenceKind) -> set[int]:
    """
    Every id the references name of one kind, across all their field paths

    Args:
        references (list[RiskCalculationReference]): The collected references
        kind (RiskCalculationReferenceKind): The kind to gather

    Returns:
        set[int]: The ids
    """
    return {public_id for reference in references if reference.kind == kind for public_id in reference.ids}


def unknown_reference_reasons(
        references: list[RiskCalculationReference],
        unknown: dict[RiskCalculationReferenceKind, set[int]]) -> list[str]:
    """
    The refusal reasons for every field path naming an unknown id, in the order of the references

    Args:
        references (list[RiskCalculationReference]): The collected references
        unknown (dict[RiskCalculationReferenceKind, set[int]]): The ids of each kind that are not stored

    Returns:
        list[str]: One reason per field path naming at least one unknown id; empty when every id is stored
    """
    reasons: list[str] = []

    for reference in references:
        unknown_ids: set[int] = reference.ids & unknown.get(reference.kind, set())

        if unknown_ids:
            reasons.append(RISK_CALCULATION_REASON.format(field=reference.field, ids=sorted(unknown_ids)))

    return reasons


def read_missing_impact_categories(risk_assessment_manager: RiskAssessmentManager, category_ids: set[int]) -> set[int]:
    """
    The named ImpactCategories that are not stored, a failed read answering its own 400

    The read raises the base ``BaseManagerGetError``, so - like ``abort_on_unknown_control_measures`` - it is
    answered here instead of in a route's error table

    Args:
        risk_assessment_manager (RiskAssessmentManager): The manager to read through
        category_ids (set[int]): The ImpactCategory ids the write names

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 and ``IMPACT_CATEGORY_LOOKUP_FAILED_MSG`` when the read fails

    Returns:
        set[int]: The ids no ImpactCategory carries
    """
    try:
        return risk_assessment_manager.get_missing_impact_category_ids(category_ids)
    except BaseManagerGetError as err:
        LOGGER.error("[read_missing_impact_categories] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, IMPACT_CATEGORY_LOOKUP_FAILED_MSG)


def check_risk_calculation_references(
        risk_assessment_manager: RiskAssessmentManager,
        data: dict[str, Any]) -> RiskCalculationBases:
    """
    Refuses a RiskAssessment write whose risk calculation rates a category twice or names what is not stored

    Called by the create, update and duplicate routes before their first write. Returns the scales it read, which
    the caller passes to ``RiskAssessmentManager.recalculate_risk_values`` - so the derived values come from the
    same read the ids were checked against

    Args:
        risk_assessment_manager (RiskAssessmentManager): The manager to read through
        data (dict[str, Any]): The validated RiskAssessment payload

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when a matrix rates an ImpactCategory more than once, when an
            ImpactCategory, Impact or Likelihood is not stored (every one named with its field path), or when the
            ImpactCategories could not be read
        RiskAssessmentManagerScaleReadError: If the Impact or Likelihood scale could not be read

    Returns:
        RiskCalculationBases: The Impact and Likelihood scales
    """
    abort_on_duplicate_impact_categories(data)

    references: list[RiskCalculationReference] = collect_risk_calculation_references(data)

    missing_categories: set[int] = read_missing_impact_categories(
        risk_assessment_manager, ids_of_kind(references, RiskCalculationReferenceKind.IMPACT_CATEGORY),
    )
    bases: RiskCalculationBases = risk_assessment_manager.load_calculation_bases()

    reasons: list[str] = unknown_reference_reasons(references, {
        RiskCalculationReferenceKind.IMPACT_CATEGORY: missing_categories,
        RiskCalculationReferenceKind.IMPACT: (
            ids_of_kind(references, RiskCalculationReferenceKind.IMPACT) - bases.impact.keys()
        ),
        RiskCalculationReferenceKind.LIKELIHOOD: (
            ids_of_kind(references, RiskCalculationReferenceKind.LIKELIHOOD) - bases.likelihood.keys()
        ),
    })

    if reasons:
        abort(400, UNKNOWN_RISK_CALCULATION_REFERENCES_MSG.format(
            reasons=RISK_CALCULATION_REASON_SEPARATOR.join(reasons),
        ))

    return bases
