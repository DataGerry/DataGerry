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
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.extendable_option_model.extendable_option_constants import (
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
)

from cmdb.class_schema.extendable_option_model.cmdb_extendable_option_schema import get_cmdb_extendable_option_schema

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
    INDEX_KEYS: list[dict[str, Any]] = [
        # An option's identity is its value within its own list, and this index is the actual
        # guarantee. The create and update routes check first (extendable_options_helper.
        # option_value_exists), but that is a read-then-write, and the ISMS CSV importer resolves
        # values through its own read-then-insert - so before this index concurrent writers could
        # (and on installations older than 2026-07-06, without any check at all, did) leave two
        # identical entries in the same dropdown.
        #
        # Compound with option_type FIRST, so it is also a usable index for every 'all options of
        # this type' query - which is why the collection's former non-unique 'option_type' index was
        # dropped rather than kept beside it (updater_20260902).
        #
        # Case- and whitespace-sensitive, exactly like the route guard: 'CAT6', 'cat6' and ' CAT6'
        # are three different options. Existing databases are de-duplicated by updater_20260902
        # before it builds this index; changing INDEX_KEYS alone would have changed nothing for them,
        # since index reconciliation is name-based and purely additive
        {
            'keys': [
                (ExtendableOptionKey.OPTION_TYPE.value, CmdbDAO.DAO_ASCENDING),
                (ExtendableOptionKey.VALUE.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': OPTION_TYPE_VALUE_INDEX_NAME,
            'unique': True,
        },
    ]

    SCHEMA: dict = get_cmdb_extendable_option_schema()


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
