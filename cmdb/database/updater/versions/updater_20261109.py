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
Database update 20261109: a RiskAssessment's and a ControlMeasure's reference ids name what is stored, or nothing

The RiskAssessment writes now refuse a risk-calculation id or an implementation state that is no whole number from 1,
a boolean, or an id nothing carries, and one ImpactCategory rated twice in a matrix. An assessment stored before could
hold any of them, and the frontend sends a stored assessment back as it reads it - so editing it would be refused.
This update brings every stored one in line, changing nothing a reader shows: every reader already treats such a
value as unrated.

Per RiskAssessment, in both risk-calculation matrices:

- an ``impacts`` row whose ``impact_category_id`` is no id or names no stored ImpactCategory is removed, and of two
  rows of one category the first is kept
- an ``impact_id`` or ``likelihood_id`` that is no id or names no stored Impact / Likelihood becomes null (unrated)
- a matrix that changed gets its derived values recomputed from the stored scales, as every write derives them:
  ``maximum_impact_id`` / ``maximum_impact_value`` from the rows, ``likelihood_value`` from the Likelihood

and an ``implementation_status`` that is no id or no option of the IMPLEMENTATION_STATE list becomes null. A
ControlMeasure's ``implementation_state`` is held to the same rule. A ControlMeasureAssignment's
``implementation_status`` is not touched: it may not be null, so there is no neutral value to put in its place.

Re-run safe: a second run finds every id valid and every category rated once, and writes nothing
"""
from logging import Logger, getLogger
from typing import Any, Callable, NamedTuple

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
RISK_ASSESSMENTS_COLLECTION: str = 'isms.riskAssessment'
CONTROL_MEASURES_COLLECTION: str = 'isms.controlMeasure'
IMPACT_CATEGORIES_COLLECTION: str = 'isms.impactCategory'
IMPACTS_COLLECTION: str = 'isms.impact'
LIKELIHOODS_COLLECTION: str = 'isms.likelihood'
OPTIONS_COLLECTION: str = 'framework.extendableOptions'
MONGO_ID_FIELD: str = '_id'
PUBLIC_ID_FIELD: str = 'public_id'
CALCULATION_BASIS_FIELD: str = 'calculation_basis'
OPTION_TYPE_FIELD: str = 'option_type'
IMPLEMENTATION_STATE_OPTION_TYPE: str = 'IMPLEMENTATION_STATE'
MATRIX_KEYS: tuple[str, ...] = ('risk_calculation_before', 'risk_calculation_after')
IMPACTS_FIELD: str = 'impacts'
IMPACT_CATEGORY_ID_FIELD: str = 'impact_category_id'
IMPACT_ID_FIELD: str = 'impact_id'
LIKELIHOOD_ID_FIELD: str = 'likelihood_id'
LIKELIHOOD_VALUE_FIELD: str = 'likelihood_value'
MAXIMUM_IMPACT_ID_FIELD: str = 'maximum_impact_id'
MAXIMUM_IMPACT_VALUE_FIELD: str = 'maximum_impact_value'
ASSESSMENT_STATE_FIELD: str = 'implementation_status'
CONTROL_MEASURE_STATE_FIELD: str = 'implementation_state'
MIN_PUBLIC_ID: int = 1
ID_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1}
BASIS_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1, CALCULATION_BASIS_FIELD: 1}
ASSESSMENT_PROJECTION: dict[str, int] = {
    MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, ASSESSMENT_STATE_FIELD: 1, **{key: 1 for key in MATRIX_KEYS},
}
CONTROL_MEASURE_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, CONTROL_MEASURE_STATE_FIELD: 1}

# -------------------------------------------------------------------------------------------------------------------- #

class StoredReferences(NamedTuple):
    """What the stored ids may name: the ImpactCategories, both scales with their bases, the implementation states"""
    impact_categories: set[int]
    impact_bases: dict[int, Any]
    likelihood_bases: dict[int, Any]
    implementation_states: set[int]


def is_public_id(value: Any) -> bool:
    """
    Whether a stored value is a public_id: an int from 1; a bool is none

    Args:
        value (Any): The stored value

    Returns:
        bool: True for an id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_PUBLIC_ID


def known_or_none(value: Any, known: set[int] | dict[int, Any]) -> int | None:
    """
    A stored id if it names something stored, else None

    Args:
        value (Any): The stored value
        known (set[int] | dict[int, Any]): The stored ids

    Returns:
        int | None: The id, or None for a value that is no id or names nothing
    """
    return value if is_public_id(value) and value in known else None


def clean_impact_rows(rows: list[Any], references: StoredReferences) -> list[dict[str, Any]]:
    """
    The rows of one matrix with every category stored and rated once, and every impact stored or null

    Args:
        rows (list[Any]): The stored ``impacts`` rows
        references (StoredReferences): What is stored

    Returns:
        list[dict[str, Any]]: The kept rows, in their stored order
    """
    kept: list[dict[str, Any]] = []
    seen_categories: set[int] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue

        category_id: int | None = known_or_none(row.get(IMPACT_CATEGORY_ID_FIELD), references.impact_categories)

        if category_id is None or category_id in seen_categories:
            continue

        seen_categories.add(category_id)
        kept.append({**row, IMPACT_ID_FIELD: known_or_none(row.get(IMPACT_ID_FIELD), references.impact_bases)})

    return kept


def derive_matrix_values(matrix: dict[str, Any], references: StoredReferences) -> dict[str, Any]:
    """
    A matrix with its derived values recomputed, as every RiskAssessment write derives them

    The maximum impact is the row whose Impact has the highest known calculation basis (the first on a tie); the
    likelihood value is the basis of the Likelihood. Both are null when nothing rated has a basis

    Args:
        matrix (dict[str, Any]): The cleaned matrix
        references (StoredReferences): What is stored

    Returns:
        dict[str, Any]: The matrix with the three derived values set
    """
    maximum_id: int | None = None
    maximum_value: Any = None

    for row in matrix.get(IMPACTS_FIELD) or []:
        basis: Any = references.impact_bases.get(row.get(IMPACT_ID_FIELD))

        if basis is not None and (maximum_value is None or basis > maximum_value):
            maximum_id, maximum_value = row.get(IMPACT_ID_FIELD), basis

    likelihood_id: Any = matrix.get(LIKELIHOOD_ID_FIELD)

    return {
        **matrix,
        MAXIMUM_IMPACT_ID_FIELD: maximum_id,
        MAXIMUM_IMPACT_VALUE_FIELD: maximum_value,
        LIKELIHOOD_VALUE_FIELD: references.likelihood_bases.get(likelihood_id) if likelihood_id else None,
    }


def clean_matrix(matrix: dict[str, Any], references: StoredReferences) -> dict[str, Any] | None:
    """
    One matrix brought in line, or None when it already is

    Args:
        matrix (dict[str, Any]): The stored matrix
        references (StoredReferences): What is stored

    Returns:
        dict[str, Any] | None: The cleaned matrix with its derived values recomputed; None when nothing changed
    """
    cleaned: dict[str, Any] = {
        **matrix,
        LIKELIHOOD_ID_FIELD: known_or_none(matrix.get(LIKELIHOOD_ID_FIELD), references.likelihood_bases),
    }

    if isinstance(matrix.get(IMPACTS_FIELD), list):
        cleaned[IMPACTS_FIELD] = clean_impact_rows(matrix[IMPACTS_FIELD], references)

    if cleaned == matrix:
        return None

    return derive_matrix_values(cleaned, references)


def assessment_changes(assessment: dict[str, Any], references: StoredReferences) -> dict[str, Any]:
    """
    The fields of one stored RiskAssessment to rewrite

    Args:
        assessment (dict[str, Any]): The stored assessment (its matrices and implementation status)
        references (StoredReferences): What is stored

    Returns:
        dict[str, Any]: The ``$set`` document; empty when the assessment already is in line
    """
    changes: dict[str, Any] = {}

    for matrix_key in MATRIX_KEYS:
        matrix: Any = assessment.get(matrix_key)

        if isinstance(matrix, dict) and (cleaned := clean_matrix(matrix, references)) is not None:
            changes[matrix_key] = cleaned

    state: Any = assessment.get(ASSESSMENT_STATE_FIELD)

    if state is not None and known_or_none(state, references.implementation_states) is None:
        changes[ASSESSMENT_STATE_FIELD] = None

    return changes


def control_measure_changes(control_measure: dict[str, Any], references: StoredReferences) -> dict[str, Any]:
    """
    The fields of one stored ControlMeasure to rewrite

    Args:
        control_measure (dict[str, Any]): The stored ControlMeasure (its implementation state)
        references (StoredReferences): What is stored

    Returns:
        dict[str, Any]: The ``$set`` document; empty when the state is null or an IMPLEMENTATION_STATE option
    """
    state: Any = control_measure.get(CONTROL_MEASURE_STATE_FIELD)

    if state is not None and known_or_none(state, references.implementation_states) is None:
        return {CONTROL_MEASURE_STATE_FIELD: None}

    return {}

# ---------------------------------------------- Update20261109 - CLASS ---------------------------------------------- #

class Update20261109(BaseDatabaseUpdate):
    """
    Nulls or removes a RiskAssessment's and a ControlMeasure's reference ids that name nothing stored

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261109


    def description(self) -> str:
        return "Nulls or removes RiskAssessment and ControlMeasure reference ids that name nothing stored"


    def start_update(self) -> None:
        """
        Reads what is stored once, rewrites every assessment and ControlMeasure that is out of line, then bumps the
        version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            references: StoredReferences = self.read_stored_references()

            assessments: int = self.rewrite(
                RISK_ASSESSMENTS_COLLECTION, ASSESSMENT_PROJECTION, assessment_changes, references,
            )
            control_measures: int = self.rewrite(
                CONTROL_MEASURES_COLLECTION, CONTROL_MEASURE_PROJECTION, control_measure_changes, references,
            )

            LOGGER.info("[updater_20261109] Rewrote %s RiskAssessment(s) and %s ControlMeasure(s)",
                        assessments, control_measures)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def read_stored_references(self) -> StoredReferences:
        """
        Reads every id a RiskAssessment or ControlMeasure may name, one projected query per collection

        Returns:
            StoredReferences: What is stored
        """
        return StoredReferences(
            impact_categories=set(self.read_bases(IMPACT_CATEGORIES_COLLECTION, {})),
            impact_bases=self.read_bases(IMPACTS_COLLECTION, {}),
            likelihood_bases=self.read_bases(LIKELIHOODS_COLLECTION, {}),
            implementation_states=set(self.read_bases(
                OPTIONS_COLLECTION, {OPTION_TYPE_FIELD: IMPLEMENTATION_STATE_OPTION_TYPE},
            )),
        )


    def read_bases(self, collection: str, criteria: dict[str, Any]) -> dict[int, Any]:
        """
        The public_ids of a collection's documents, each with its calculation basis (None where it has none)

        Args:
            collection (str): The collection to read
            criteria (dict[str, Any]): The filter

        Returns:
            dict[int, Any]: public_id -> calculation_basis, for every document with a public_id
        """
        documents: list[dict[str, Any]] = list(self.dbm.find(
            collection=collection, db_name=self.db_name, filter=criteria, projection=BASIS_PROJECTION,
        ))

        return {
            document[PUBLIC_ID_FIELD]: document.get(CALCULATION_BASIS_FIELD)
            for document in documents if is_public_id(document.get(PUBLIC_ID_FIELD))
        }


    def rewrite(self,
                collection: str,
                projection: dict[str, int],
                changes_of: Callable[[dict[str, Any], StoredReferences], dict[str, Any]],
                references: StoredReferences) -> int:
        """
        Rewrites the documents of one collection whose changes are not empty, in one bulk write

        Args:
            collection (str): The collection
            projection (dict[str, int]): What to read of each document
            changes_of (Callable[[dict[str, Any], StoredReferences], dict[str, Any]]): The function answering a
                document's ``$set`` document
            references (StoredReferences): What is stored

        Returns:
            int: How many documents were rewritten
        """
        operations: list[UpdateOne] = []

        for document in self.dbm.find(collection=collection, db_name=self.db_name, filter={}, projection=projection):
            changes: dict[str, Any] = changes_of(document, references)

            if changes:
                operations.append(UpdateOne({MONGO_ID_FIELD: document[MONGO_ID_FIELD]}, {'$set': changes}))
                LOGGER.warning("[updater_20261109] %s ID:%s - rewrote %s", collection,
                               document.get(PUBLIC_ID_FIELD), sorted(changes))

        if operations:
            self.dbm.bulk_write(collection, self.db_name, operations)

        return len(operations)
