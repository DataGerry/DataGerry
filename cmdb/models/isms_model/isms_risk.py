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
Implementation of IsmsRisk in DataGerry - ISMS
"""
from logging import Logger, getLogger
from typing import Any
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.risk_type_enum import RiskType

from cmdb.class_schema.isms_model.isms_risk_schema import get_isms_risk_schema

from cmdb.errors.models.isms_risk import (
    IsmsRiskInitError,
    IsmsRiskInitFromDataError,
    IsmsRiskToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   IsmsRisk - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRisk(CmdbDAO):
    """
    Implementation of IsmsRisk which represents a risk in ISMS

    Extends: CmdbDAO
    """
    COLLECTION = "isms.risk"

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('risk_type', CmdbDAO.DAO_ASCENDING)], 'name': 'risk_type', 'unique': False},
        {'keys': [('threats', CmdbDAO.DAO_ASCENDING)], 'name': 'threats', 'unique': False},
        {'keys': [('vulnerabilities', CmdbDAO.DAO_ASCENDING)], 'name': 'vulnerabilities', 'unique': False},
        {'keys': [('identifier', CmdbDAO.DAO_ASCENDING)], 'name': 'identifier', 'unique': False}
    ]

    SCHEMA: dict = get_isms_risk_schema()


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            name: str,
            risk_type: RiskType,
            protection_goals: list[int],
            threats: list[int] = None,
            vulnerabilities: list[int] = None,
            category_id: int = None,
            identifier: str = None,
            consequences: str = None,
            description: str = None,
        ) -> None:
        """
        Initialises an IsmsRisk

        Args:
            public_id (int): public_id of the IsmsRisk
            name (str): The name of the IsmsRisk
            risk_type (RiskType): RiskType of the IsmsRisk
            protection_goals (list[int]): List of affected protection goals of the IsmsRisk
            threats (list[int]): List of threats linked with this IsmsRisk
            vulnerabilities (list[int]): List of vulnerabilities linked with this IsmsRisk
            category_id (int): The public_id of the CmdbExtendableOption representing the value
            identifier (str, optional): Identifier of the IsmsRisk
            consequences (str, optional): Consequences of the IsmsRisk
            description (str, optional): Description of the IsmsRisk

        Raises:
            IsmsRiskInitError: If the IsmsRisk could not be initialised
        """
        try:
            self.name = name
            self.risk_type = risk_type
            self.protection_goals = protection_goals
            self.threats = threats or []
            self.vulnerabilities = vulnerabilities or []
            self.category_id = category_id
            self.identifier = identifier
            self.consequences = consequences
            self.description = description

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsRiskInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsRisk":
        """
        Initialises a IsmsRisk from a dict

        Args:
            data (dict): Data with which the IsmsRisk should be initialised

        Raises:
            IsmsRiskInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsRisk: IsmsRisk with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                risk_type = data.get('risk_type'),
                protection_goals = data.get('protection_goals'),
                threats = data.get('threats', []),
                vulnerabilities = data.get('vulnerabilities', []),
                category_id = data.get('category_id'),
                identifier = data.get('identifier'),
                consequences = data.get('consequences'),
                description = data.get('description'),
            )
        except Exception as err:
            raise IsmsRiskInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsRisk") -> dict:
        """
        Converts a IsmsRisk into a json compatible dict

        Args:
            instance (IsmsRisk): The IsmsRisk which should be converted

        Raises:
            IsmsRiskToJsonError: If the IsmsRisk could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsRisk values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'risk_type': instance.risk_type,
                'protection_goals': instance.protection_goals,
                'threats': instance.threats,
                'vulnerabilities': instance.vulnerabilities,
                'category_id': instance.category_id,
                'identifier': instance.identifier,
                'consequences': instance.consequences,
                'description': instance.description,
            }
        except Exception as err:
            raise IsmsRiskToJsonError(err) from err
