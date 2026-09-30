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
This module contains the implementation of the ControlMeasureAssignmentManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey

from cmdb.errors.manager.control_measure_assignment_manager import CONTROL_MEASURE_ASSIGNMENT_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                       ControlMeasureAssignmentManager - CLASS                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class ControlMeasureAssignmentManager(GenericManager):
    """
    The ControlMeasureAssignmentManager manages the interaction between IsmsControlMeasureAssignments
    and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ControlMeasureAssignmentManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsControlMeasureAssignment, CONTROL_MEASURE_ASSIGNMENT_MANAGER_ERRORS, database)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_missing_control_measure_ids(self, assignments: list[dict[str, Any]]) -> set[int]:
        """
        Returns the control_measure_ids referenced by the given assignments that do not exist.

        Resolves the referenced IsmsControlMeasures in a single query so a RiskAssessment cannot be
        linked to a non-existent ControlMeasure.

        Args:
            assignments (list[dict[str, Any]]): ControlMeasureAssignment payloads to check

        Returns:
            set[int]: The referenced control_measure_ids with no matching IsmsControlMeasure
                      (empty when every reference resolves)
        """
        referenced_ids = {
            assignment[ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value] for assignment in assignments
            if assignment.get(ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value) is not None
        }

        if not referenced_ids:
            return set()

        existing_ids = {
            control_measure[ControlMeasureKey.PUBLIC_ID.value]
            for control_measure in self.get_many_from_other_collection(
                IsmsControlMeasure.COLLECTION, public_id={'$in': list(referenced_ids)})
        }

        return referenced_ids - existing_ids
