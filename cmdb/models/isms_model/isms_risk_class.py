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
Implementation of IsmsRiskClass in DataGerry - ISMS
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.isms_model.isms_risk_class_schema import get_isms_risk_class_schema

from cmdb.errors.models.isms_risk_class import (
    IsmsRiskClassInitError,
    IsmsRiskClassInitFromDataError,
    IsmsRiskClassToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 IsmsRiskClass - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRiskClass(CmdbDAO):
    """
    Implementation of IsmsRiskClass which represents a risk class of the ISMS general configuration

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskClass"

    SCHEMA: dict = get_isms_risk_class_schema()


    #pylint: disable=R0917
    def __init__(self, public_id: int, name: str, color: str, sort: int = None, description: str = None):
        """
        Initialises an IsmsRiskClass

        Args:
            public_id (int): public_id of the IsmsRiskClass
            name (str): The name of the IsmsRiskClass
            color (float): The color of the IsmsRiskClass
            sort (int): The sort order of the IsmsRiskClass
            description (str): The description of the IsmsRiskClass

        Raises:
            IsmsRiskClassInitError: When the IsmsRiskClass could not be initialised
        """
        try:
            self.name = name
            self.color = color
            self.sort = sort
            self.description = description

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskClassInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsRiskClass":
        """
        Initialises a IsmsRiskClass from a dict

        Args:
            data (dict): Data with which the IsmsRiskClass should be initialised

        Raises:
            IsmsRiskClassInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsRiskClass: IsmsRiskClass with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                color = data.get('color'),
                sort = data.get('sort'),
                description = data.get('description'),
            )
        except Exception as err:
            raise IsmsRiskClassInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsRiskClass") -> dict:
        """
        Converts a IsmsRiskClass into a json compatible dict

        Args:
            instance (IsmsRiskClass): The IsmsRiskClass which should be converted

        Raises:
            IsmsRiskClassToJsonError: If the IsmsRiskClass could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsRiskClass values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'color': instance.color,
                'sort': instance.sort,
                'description': instance.description,
            }
        except Exception as err:
            raise IsmsRiskClassToJsonError(err) from err
