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
Implementation of CmdbExtendableOption in DataGerry
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.extendable_option_model.option_type_enum import OptionType

from cmdb.errors.models.cmdb_extendable_option import (
    CmdbExtendableOptionInitError,
    CmdbExtendableOptionInitFromDataError,
    CmdbExtendableOptionToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbExtendableOption - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbExtendableOption(CmdbDAO):
    """
    Implementation of CmdbExtendableOption which is single value for an OptionType

    Extends: CmdbDAO
    """
    COLLECTION = "framework.extendableOptions"
    MODEL = 'ExtendableOption'
    INDEX_KEYS = [
        {'keys': [('option_type', CmdbDAO.DAO_ASCENDING)], 'name': 'option_type', 'unique': False}
    ]

    # pylint: disable=R0801
    SCHEMA: dict = {
        'public_id': {
            'type': 'integer',
            'min': 1,
        },
        'value': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'option_type': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'predefined': {
            'type': 'boolean',
            'required': True,
            'empty': False
        }
    }


    def __init__(self, public_id: int, value: str, option_type: OptionType, predefined: bool = False):
        """
        Initialises an CmdbExtendableOption

        Args:
            public_id (int): public_id of the CmdbExtendableOption
            value (str): value of the CmdbExtendableOption
            option_type (str): OptionType of CmdbExtendableOption
            predefined (bool): If True it is created by 

        Raises:
            CmdbExtendableOptionInitError: If the CmdbExtendableOption could not be initialised
        """
        try:
            self.value = value
            self.option_type = option_type
            self.predefined = predefined

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbExtendableOptionInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbExtendableOption":
        """
        Initialises a CmdbExtendableOption from a dict

        Args:
            data (dict): Data with which the CmdbExtendableOption should be initialised

        Raises:
            CmdbExtendableOptionInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbExtendableOption: CmdbExtendableOption with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                value = data.get('value'),
                option_type = data.get('option_type'),
                predefined = data.get('predefined', False),
            )
        except Exception as err:
            raise CmdbExtendableOptionInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbExtendableOption") -> dict:
        """
        Converts a CmdbExtendableOption into a json compatible dict

        Args:
            instance (CmdbExtendableOption): The CmdbExtendableOption which should be converted

        Raises:
            CmdbExtendableOptionToJsonError: If the CmdbExtendableOption could not be converted to a json dict

        Returns:
            dict: Json compatible dict of the CmdbExtendableOption values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'value': instance.value,
                'option_type': instance.option_type,
                'predefined': instance.predefined,
            }
        except Exception as err:
            raise CmdbExtendableOptionToJsonError(err) from err
