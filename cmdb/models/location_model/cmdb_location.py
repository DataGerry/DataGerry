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
This module contains the implementation of CmdbLocation, which is representing a location in Datagarry
"""
from logging import Logger, getLogger
from typing import Any
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.location_model.cmdb_location_schema import get_cmdb_location_schema

from cmdb.errors.models.cmdb_location import (
    CmdbLocationInitError,
    CmdbLocationInitFromDataError,
    CmdbLocationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbLocation - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbLocation(CmdbDAO):
    """
    The CMDBLocation is the basic data wrapper for storing and holding locations within the database

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.locations'
    MODEL = 'Location'
    DEFAULT_VERSION: str = '1.0.0'
    REQUIRED_INIT_KEYS: list[str] = ['name', 'parent', 'object_id', 'type_id', 'type_label']

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('object_id', CmdbDAO.DAO_ASCENDING)], 'name': 'object_id', 'unique': False},
        {'keys': [('parent', CmdbDAO.DAO_ASCENDING)], 'name': 'parent', 'unique': False},
        {'keys': [('type_id', CmdbDAO.DAO_ASCENDING)], 'name': 'type_id', 'unique': False}
    ]

    SCHEMA: dict = get_cmdb_location_schema()


    #pylint: disable=R0913, R0917
    def __init__(self,
                 public_id: int,
                 name: str,
                 parent: int,
                 object_id: int,
                 type_id: int,
                 type_label: str,
                 type_icon: str = "fas fa-cube",
                 type_selectable: bool = True):
        """
        Initialises a CmdbLocation

        Args:
            public_id (int): public_id of the CmdbLocation
            name (str): name of the CmdbLocation displayed in location tree
            parent (int): public_id of parent CmdbLocation
            object_id (int): public_id of CmdbObject who has this CmdbLocation
            type_id (int): public_id of CmdbType for which this CmdbLocation is set
            type_label (str): label of CmdbType for which this location is set
            type_icon (str): icon of CmdbType for which this CmdbLocation is set, default is 'fas fa-cube'
            type_selectable (bool): sets if this CmdbType is selectable as a parent for other CmdbLocations.
                                    Defaults to True

        Raises:
            CmdbLocationInitError: If the CmdbLocation could not be initialised
        """
        try:
            self.name: str = name
            self.parent: int = parent
            self.object_id: int = object_id
            self.type_id: int = type_id
            self.type_label: str = type_label
            self.type_icon: str = type_icon
            self.type_selectable: bool = type_selectable

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbLocationInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbLocation":
        """
        Initialises a CmdbLocation from a dict

        Args:
            data (dict): Data with which the CmdbLocation should be initialised

        Raises:
            CmdbLocationInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbLocation: CmdbLocation with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                parent = data.get('parent'),
                object_id = data.get('object_id'),
                type_id = data.get('type_id'),
                type_label = data.get('type_label'),
                type_icon = data.get('type_icon', 'fas fa-cube'),
                type_selectable = data.get('type_selectable', True),
            )
        except Exception as err:
            raise CmdbLocationInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbLocation") -> dict:
        """
        Converts a CmdbLocation into a json compatible dict

        Args:
            instance (CmdbLocation): The CmdbLocation which should be converted

        Raises:
            CmdbLocationToJsonError: If the CmdbLocation could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbLocation values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'parent': instance.parent,
                'object_id': instance.object_id,
                'type_id': instance.type_id,
                'type_label': instance.type_label,
                'type_icon': instance.type_icon,
                'type_selectable': instance.type_selectable,
            }
        except Exception as err:
            raise CmdbLocationToJsonError(err) from err
