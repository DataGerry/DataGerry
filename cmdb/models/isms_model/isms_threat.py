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
Implementation of IsmsThreat in DataGerry - ISMS
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.isms_model.isms_threat_schema import get_isms_threat_schema

from cmdb.errors.models.isms_threat import (
    IsmsThreatInitError,
    IsmsThreatInitFromDataError,
    IsmsThreatToJsonError,
)

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  IsmsThreat - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsThreat(CmdbDAO):
    """
    Implementation of IsmsThreat which represents a threat in ISMS

    Extends: CmdbDAO
    """
    COLLECTION = "isms.threat"
    MODEL = 'Threat'
    SCHEMA: dict = get_isms_threat_schema()


    #pylint: disable=R0917
    def __init__(
            self,
            public_id: int,
            name: str,
            source: int,
            identifier: str = None,
            description: str = None,
        ):
        """
        Initialises an IsmsThreat

        Args:
            public_id (int): public_id of the IsmsThreat
            name (str): The name of the IsmsThreat
            source (int): Source of the IsmsThreat
            identifier (str, optional): Identifier of the IsmsThreat
            description (str, optional): Description of the IsmsThreat

        Raises:
            IsmsThreatInitError: If the IsmsThreat could not be initialised
        """
        try:
            self.name = name
            self.source = source
            self.identifier = identifier
            self.description = description

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsThreatInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsThreat":
        """
        Initialises a IsmsThreat from a dict

        Args:
            data (dict): Data with which the IsmsThreat should be initialised

        Raises:
            IsmsThreatInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsThreat: IsmsThreat with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                source = data.get('source'),
                identifier = data.get('identifier'),
                description = data.get('description'),
            )
        except Exception as err:
            raise IsmsThreatInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsThreat") -> dict:
        """
        Converts a IsmsThreat into a json compatible dict

        Args:
            instance (IsmsThreat): The IsmsThreat which should be converted

        Raises:
            IsmsThreatToJsonError: If the IsmsThreat could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsThreat values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'source': instance.source,
                'identifier': instance.identifier,
                'description': instance.description,
            }
        except Exception as err:
            raise IsmsThreatToJsonError(err) from err
