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
Implementation of IsmsProtectionGoal in DataGerry - ISMS
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.isms_model.isms_protection_goal_schema import get_isms_protection_goal_schema

from cmdb.errors.models.isms_protection_goal import (
    IsmsProtectionGoalInitError,
    IsmsProtectionGoalInitFromDataError,
    IsmsProtectionGoalToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsProtectionGoal - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsProtectionGoal(CmdbDAO):
    """
    Implementation of IsmsProtectionGoal

    Extends: CmdbDAO
    """
    COLLECTION = "isms.protectionGoal"
    MODEL = 'ProtectionGoal'

    SCHEMA: dict = get_isms_protection_goal_schema()


    def __init__(self, public_id: int, name: str, predefined: bool = False):
        """
        Initialises an IsmsProtectionGoal

        Args:
            public_id (int): public_id of the IsmsProtectionGoal
            name (str): The name of the IsmsProtectionGoal
            predefined (bool, optional): If True then it was created by DataGerry

        Raises:
            IsmsProtectionGoalInitError: When the IsmsProtectionGoal could not be initialised
        """
        try:
            self.name = name
            self.predefined = predefined

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsProtectionGoalInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsProtectionGoal":
        """
        Initialises a IsmsProtectionGoal from a dict

        Args:
            data (dict): Data with which the IsmsProtectionGoal should be initialised

        Raises:
            IsmsProtectionGoalInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsProtectionGoal: IsmsProtectionGoal with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                predefined = data.get('predefined'),
            )
        except Exception as err:
            raise IsmsProtectionGoalInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsProtectionGoal") -> dict:
        """
        Converts a IsmsProtectionGoal into a json compatible dict

        Args:
            instance (IsmsProtectionGoal): The IsmsProtectionGoal which should be converted

        Raises:
            IsmsProtectionGoalToJsonError: If the IsmsProtectionGoal could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsProtectionGoal values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'predefined': instance.predefined,
            }
        except Exception as err:
            raise IsmsProtectionGoalToJsonError(err) from err
