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
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.utils import Builder
from cmdb.manager.isms_manager.isms_manager_constants import (
    CATALOG_CONTROL_COUNT_KEY,
    CONTROL_MEASURE_IN_USE_MESSAGE,
    GROUPED_ID_KEY,
    MONGO_ID_KEY,
    PUBLIC_ID_KEY,
)
from cmdb.manager.isms_manager.isms_manager_helper import delete_unless_referenced, get_referenced_ids

from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError, BaseManagerUpdateError
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey

from cmdb.errors.manager.control_measure_manager import (
    CONTROL_MEASURE_MANAGER_ERRORS,
    ControlMeasureManagerAssignmentUsageError,
    ControlMeasureManagerGetError,
    ControlMeasureManagerIterationError,
    ControlMeasureManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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


# -------------------------------------------------- CATALOG IMPORT -------------------------------------------------- #

    def get_catalog_controls(self, catalog_id: str, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        """
        The controls imported from a catalog, as raw documents trimmed to public_id, identifier and the given keys

        Args:
            catalog_id (str): id of the bundled catalog (manifest id)
            keys (tuple[str, ...]): Further document keys to read

        Raises:
            ControlMeasureManagerGetError: If the controls could not be read

        Returns:
            list[dict[str, Any]]: The trimmed documents
        """
        projection: dict[str, int] = {
            MONGO_ID_KEY: 0, PUBLIC_ID_KEY: 1, ControlMeasureKey.IDENTIFIER.value: 1, **{key: 1 for key in keys},
        }

        try:
            return self.find({ControlMeasureKey.CATALOG_ID.value: catalog_id}, projection=projection)
        except BaseManagerGetError as err:
            LOGGER.error("[get_catalog_controls] Exception: %s. Type: %s", err, type(err))
            raise ControlMeasureManagerGetError(err) from err


    def update_catalog_fields(self, updates: list[tuple[int, dict[str, Any]]]) -> int:
        """
        Sets the catalog-owned fields of imported controls in one bulk write ($set per control, nothing else touched)

        Args:
            updates (list[tuple[int, dict[str, Any]]]): (public_id, {key: value}) per control

        Raises:
            ControlMeasureManagerUpdateError: If the bulk write fails; the controls written before the failure keep
                their new values (a second import finishes the rest)

        Returns:
            int: How many controls were modified; 0 without a write when there is nothing to update
        """
        if not updates:
            return 0

        operations: list[UpdateOne] = [
            UpdateOne({PUBLIC_ID_KEY: public_id}, {'$set': changes}) for public_id, changes in updates
        ]

        try:
            return self.bulk_write(operations)
        except BaseManagerUpdateError as err:
            LOGGER.error("[update_catalog_fields] Exception: %s. Type: %s", err, type(err))
            raise ControlMeasureManagerUpdateError(err) from err


    def count_controls_per_catalog(self) -> dict[str, int]:
        """
        Counts the imported controls per catalog

        Raises:
            ControlMeasureManagerIterationError: If the aggregation fails

        Returns:
            dict[str, int]: catalog_id -> number of controls, for every catalog with at least one
        """
        pipeline: list[dict[str, Any]] = [
            Builder.match_({ControlMeasureKey.CATALOG_ID.value: {'$nin': [None, '']}}),
            Builder.group_(f'${ControlMeasureKey.CATALOG_ID.value}', {CATALOG_CONTROL_COUNT_KEY: {'$sum': 1}}),
        ]

        try:
            return {row[GROUPED_ID_KEY]: row[CATALOG_CONTROL_COUNT_KEY] for row in self.aggregate_all(pipeline)}
        except BaseManagerIterationError as err:
            LOGGER.error("[count_controls_per_catalog] Exception: %s. Type: %s", err, type(err))
            raise ControlMeasureManagerIterationError(err) from err
