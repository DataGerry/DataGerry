# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of the RiskAssessmentManager
"""
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import (
    RiskCalculationBases,
    load_risk_calculation_bases,
    recompute_max_impact,
)

from cmdb.models.isms_model import (
    IsmsRisk,
    IsmsRiskAssessment,
    IsmsControlMeasureAssignment,
    IsmsImpactCategory,
)
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_impact_category_constants import ImpactCategoryKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectGroupKey, ObjectReferenceType

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.risk_assessment_manager import (
    RISK_ASSESMENT_MANAGER_ERRORS,
    RiskAssessmentManagerDeleteError,
    RiskAssessmentManagerRiskReadError,
    RiskAssessmentManagerScaleReadError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                             RiskAssessmentManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskAssessmentManager(GenericManager):
    """
    The RiskAssessmentManager manages the interaction between IsmsRiskAssessments and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the RiskAssessmentManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsRiskAssessment, RISK_ASSESMENT_MANAGER_ERRORS, database)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def load_calculation_bases(self) -> RiskCalculationBases:
        """
        Reads the IsmsImpact and IsmsLikelihood calculation bases a RiskAssessment write is checked and derived from

        Raises:
            RiskAssessmentManagerScaleReadError: If the IsmsImpact or IsmsLikelihood scale could not be read

        Returns:
            RiskCalculationBases: Both scales as public_id -> calculation_basis maps
        """
        try:
            return load_risk_calculation_bases(self)
        except BaseManagerGetError as err:
            raise RiskAssessmentManagerScaleReadError(err) from err


    def recalculate_risk_values(self, data: dict[str, Any], bases: RiskCalculationBases | None = None) -> None:
        """
        Derives the risk-calculation values on both matrices server-side, in place.

        The maximum_impact_id / maximum_impact_value and likelihood_value of risk_calculation_before
        and risk_calculation_after are recomputed from the current IsmsImpact / IsmsLikelihood
        calculation bases, overwriting any client-supplied values so the backend is the single source
        of truth for them.

        Args:
            data (dict[str, Any]): The RiskAssessment payload to normalise in place
            bases (RiskCalculationBases | None): The scales the caller already read (``load_calculation_bases``),
                so a write that checked its ids against them reads them once. Defaults to None (read here)

        Raises:
            RiskAssessmentManagerScaleReadError: If the scales are read here and could not be
        """
        if bases is None:
            bases = self.load_calculation_bases()

        for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
            matrix = data.get(matrix_key.value)

            if not isinstance(matrix, dict):
                continue

            impacts = matrix.get(RiskCalculationKey.IMPACTS.value, [])
            max_id, max_value = recompute_max_impact(impacts, bases.impact)
            matrix[RiskCalculationKey.MAXIMUM_IMPACT_ID.value] = max_id
            matrix[RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value] = max_value

            likelihood_id = matrix.get(RiskCalculationKey.LIKELIHOOD_ID.value)
            matrix[RiskCalculationKey.LIKELIHOOD_VALUE.value] = (
                bases.likelihood.get(likelihood_id) if likelihood_id else None
            )


    def get_missing_impact_category_ids(self, impact_category_ids: set[int]) -> set[int]:
        """
        Answers which of the IsmsImpactCategories a write names do not exist

        One query for all of them, projected to their public_ids

        Args:
            impact_category_ids (set[int]): The public_ids of the IsmsImpactCategories the write names

        Raises:
            BaseManagerGetError: If the IsmsImpactCategories could not be read

        Returns:
            set[int]: The named ids no IsmsImpactCategory carries; empty when every one exists, or when none is
                named (nothing is read then)
        """
        if not impact_category_ids:
            return set()

        stored: list[dict[str, Any]] = self.get_many_from_other_collection(
            IsmsImpactCategory.COLLECTION,
            projection={ImpactCategoryKey.PUBLIC_ID.value: 1},
            criteria={ImpactCategoryKey.PUBLIC_ID.value: {'$in': sorted(impact_category_ids)}},
        )

        return impact_category_ids - {category[ImpactCategoryKey.PUBLIC_ID.value] for category in stored}

    def get_missing_risk_ids(self, risk_ids: set[int]) -> set[int]:
        """
        Answers which of the IsmsRisks a write names do not exist

        One query for all of them, projected to their public_ids - no Risk document is read

        Args:
            risk_ids (set[int]): The public_ids of the IsmsRisks the write names

        Raises:
            RiskAssessmentManagerRiskReadError: If the IsmsRisks could not be read (a BaseManagerGetError)

        Returns:
            set[int]: The named ids no IsmsRisk carries; empty when every one exists, or when none is named
        """
        if not risk_ids:
            return set()

        try:
            stored: list[dict[str, Any]] = self.get_many_from_other_collection(
                IsmsRisk.COLLECTION,
                projection={RiskKey.PUBLIC_ID.value: 1},
                criteria={RiskKey.PUBLIC_ID.value: {'$in': sorted(risk_ids)}},
            )
        except BaseManagerGetError as err:
            raise RiskAssessmentManagerRiskReadError(err) from err

        return risk_ids - {risk[RiskKey.PUBLIC_ID.value] for risk in stored}


    def get_missing_assessed_ids(
            self,
            reference_type: ObjectReferenceType,
            public_ids: set[int],
            denied_type_ids: list[int]) -> set[int]:
        """
        Answers which of the CmdbObjects or CmdbObjectGroups a write assesses are not there for the caller

        An object of a type in ``denied_type_ids`` counts as missing, so the caller's answer is the same for an object
        it may not READ and one that does not exist. A CmdbObjectGroup carries no ACL: only its existence is judged.
        One query for all the ids, projected to their public_ids

        Args:
            reference_type (ObjectReferenceType): What the ids name - OBJECT or OBJECT_GROUP
            public_ids (set[int]): The public_ids the write assesses
            denied_type_ids (list[int]): The CmdbTypes the caller may not READ; ignored for OBJECT_GROUP

        Raises:
            BaseManagerGetError: If the objects or groups could not be read

        Returns:
            set[int]: The ids that are missing (or hidden); empty when every one is there, or when none is named
                (nothing is read then)
        """
        if not public_ids:
            return set()

        if reference_type == ObjectReferenceType.OBJECT_GROUP:
            collection: str = CmdbObjectGroup.COLLECTION
            id_key: str = ObjectGroupKey.PUBLIC_ID.value
            criteria: dict[str, Any] = {id_key: {'$in': sorted(public_ids)}}
        else:
            collection = CmdbObject.COLLECTION
            id_key = CmdbObjectKey.PUBLIC_ID.value
            criteria = {id_key: {'$in': sorted(public_ids)}}

            if denied_type_ids:
                criteria[CmdbObjectKey.TYPE_ID.value] = {'$nin': sorted(denied_type_ids)}

        stored: list[dict[str, Any]] = self.get_many_from_other_collection(
            collection, projection={id_key: 1}, criteria=criteria,
        )

        return public_ids - {document[id_key] for document in stored}

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes an IsmsRiskAssessment and then every IsmsControlMeasureAssignment linked to it

        **The RiskAssessment goes first.** The two deletes are separate writes, so a failure can fall between
        them, and the order decides what that leaves: assignments left behind point at a RiskAssessment that no
        longer exists, which every reader already treats as "no RiskAssessment" (and a retried delete finds
        nothing to delete) - whereas the old order, assignments first, left a surviving RiskAssessment that had
        silently lost its assignments

        Args:
            public_id (int): The public_id of the IsmsRiskAssessment to delete

        Raises:
            RiskAssessmentManagerDeleteError: If the RiskAssessment or its assignments could not be deleted

        Returns:
            bool: True if the RiskAssessment was deleted, False when there was none
        """
        deleted: bool = self.delete_item(public_id)

        try:
            # One cross-collection delete rather than one delete per assignment
            self.delete_many_from_other_collection(
                IsmsControlMeasureAssignment.COLLECTION,
                {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: public_id}
            )
        except BaseManagerDeleteError as err:
            raise RiskAssessmentManagerDeleteError(err) from err

        return deleted
