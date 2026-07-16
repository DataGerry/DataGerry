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

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.control_measure_manager import (
    CONTROL_MEASURE_MANAGER_ERRORS,
    ControlMeasureManagerGetError,
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
    def __init__(self, dbm: MongoDatabaseManager, database: str = None) -> None:
        super().__init__(dbm, IsmsControlMeasure, CONTROL_MEASURE_MANAGER_ERRORS, database)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def is_control_measure_used(self, public_id: int) -> bool:
        """
        Checks if an IsmsControlMeasure is used in any IsmsControlMeasureAssignment

        Args:
            public_id (int): The public_id of the IsmsControlMeasure

        Returns:
            bool: True if the IsmsControlMeasure is used, False otherwise
        """
        return self.get_one_by({'control_measure_id': public_id}, IsmsControlMeasureAssignment.COLLECTION) is not None


    def get_used_control_measure_ids(self, public_ids: list[int]) -> set[int]:
        """
        Returns which of the given IsmsControlMeasures are referenced by an IsmsControlMeasureAssignment

        The batched counterpart to is_control_measure_used: resolves the whole candidate set in a
        single grouped aggregation on the IsmsControlMeasureAssignment collection (``$match`` on the
        candidate control_measure_ids, then ``$group`` by control_measure_id) instead of one lookup
        per id, so a bulk delete can partition its targets into deletable / still-used with one query

        Args:
            public_ids (list[int]): public_ids of the IsmsControlMeasures to test for usage

        Raises:
            ControlMeasureManagerGetError: If the grouped lookup could not be executed

        Returns:
            set[int]: The subset of public_ids that are referenced by at least one assignment
        """
        if not public_ids:
            return set()

        pipeline: list[dict[str, Any]] = [
            {'$match': {'control_measure_id': {'$in': public_ids}}},
            {'$group': {'_id': '$control_measure_id'}},
        ]

        try:
            result = self.aggregate_from_other_collection(IsmsControlMeasureAssignment.COLLECTION, pipeline)

            return {doc['_id'] for doc in result}
        except BaseManagerIterationError as err:
            raise ControlMeasureManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_used_control_measure_ids] Exception: %s. Type: %s", err, type(err))
            raise ControlMeasureManagerGetError(str(err)) from err
