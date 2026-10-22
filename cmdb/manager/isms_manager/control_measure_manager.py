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
This module contains the implementation of the ControlMeasureManager
"""
from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import CONTROL_MEASURE_IN_USE_MESSAGE
from cmdb.manager.isms_manager.isms_manager_helper import delete_unless_referenced, get_referenced_ids

from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.control_measure_manager import (
    CONTROL_MEASURE_MANAGER_ERRORS,
    ControlMeasureManagerAssignmentUsageError,
    ControlMeasureManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                            ControlMeasureManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class ControlMeasureManager(GenericManager):
    """
    The ControlMeasureManager manages the interaction between IsmsControlMeasures and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ControlMeasureManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsControlMeasure, CONTROL_MEASURE_MANAGER_ERRORS, database)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def is_control_measure_used(self, public_id: int) -> bool:
        """
        Checks if an IsmsControlMeasure is used in any IsmsControlMeasureAssignment

        Args:
            public_id (int): The public_id of the IsmsControlMeasure

        Raises:
            BaseManagerGetError: If the assignments could not be read

        Returns:
            bool: True if the IsmsControlMeasure is used, False otherwise
        """
        return self.get_one_by(
            {ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value: public_id},
            IsmsControlMeasureAssignment.COLLECTION,
        ) is not None


    def get_used_control_measure_ids(self, public_ids: list[int]) -> set[int]:
        """
        Returns which of the given IsmsControlMeasures are referenced by an IsmsControlMeasureAssignment

        The batched counterpart to is_control_measure_used: resolves the whole candidate set in a
        single grouped aggregation on the IsmsControlMeasureAssignment collection instead of one lookup
        per id, so a bulk delete can partition its targets into deletable / still-used with one query

        Args:
            public_ids (list[int]): public_ids of the IsmsControlMeasures to test for usage

        Raises:
            ControlMeasureManagerGetError: If the grouped lookup could not be executed

        Returns:
            set[int]: The subset of public_ids that are referenced by at least one assignment; empty for an
                empty list
        """
        try:
            return get_referenced_ids(
                self,
                IsmsControlMeasureAssignment.COLLECTION,
                ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value,
                public_ids,
            )
        except BaseManagerIterationError as err:
            raise ControlMeasureManagerGetError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_if_unused(self, public_id: int) -> bool:
        """
        Deletes an IsmsControlMeasure that no IsmsControlMeasureAssignment references

        Deleting a referenced one would strip the control out of a RiskAssessment's treatment plan

        Args:
            public_id (int): public_id of the IsmsControlMeasure to delete

        Raises:
            ControlMeasureManagerAssignmentUsageError: If an IsmsControlMeasureAssignment references it
            ControlMeasureManagerDeleteError: If the usage check, the delete or the restore of an item that
                gained a reference meanwhile fails

        Returns:
            bool: True if the IsmsControlMeasure was deleted, False when it did not exist
        """
        return delete_unless_referenced(
            self,
            public_id,
            lambda: self.is_control_measure_used(public_id),
            ControlMeasureManagerAssignmentUsageError,
            CONTROL_MEASURE_IN_USE_MESSAGE,
        )
