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
Implementation of IsmsControlMeasure in DataGerry - ISMS
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.control_measure_type_enum import ControlMeasureType

<<<<<<< HEAD
=======
from cmdb.class_schema.isms_model.isms_control_measure_schema import get_isms_control_measure_schema

>>>>>>> origin/version-3.2
from cmdb.errors.models.isms_control_measure import (
    IsmsControlMeasureInitError,
    IsmsControlMeasureInitFromDataError,
    IsmsControlMeasureToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsControlMeasure - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsControlMeasure(CmdbDAO):
    """
    Implementation of IsmsControlMeasure which represents a control measure in ISMS

    Extends: CmdbDAO
    """
    COLLECTION = "isms.controlMeasure"
<<<<<<< HEAD
    MODEL = 'ControlMeasure'
=======
>>>>>>> origin/version-3.2

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('control_measure_type', CmdbDAO.DAO_ASCENDING)], 'name': 'control_measure_type', 'unique': False},
    ]

<<<<<<< HEAD
    # pylint: disable=R0801
    SCHEMA: dict = {
        'public_id': {
            'type': 'integer',
            'min': 1,
        },
        'title': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'control_measure_type': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'source': {
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'implementation_state': {
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'identifier': {
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'chapter': {
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'description': {
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'is_applicable': {
            'type': 'boolean',
            'required': True,
            'nullable': True,
        },
        'reason': {
            'type': 'string',
            'required': True,
            'nullable': True,
        }
    }
=======
    SCHEMA: dict = get_isms_control_measure_schema()
>>>>>>> origin/version-3.2

    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            title: str,
            control_measure_type: ControlMeasureType,
            source: int,
            implementation_state: int,
            identifier: str = None,
            chapter: str = None,
            description: str = None,
            is_applicable: bool = False,
            reason: str = None
        ) -> None:
        """
        Initialises an IsmsControlMeasure

        Args:
            title (str): The title of the IsmsControlMeasure
            control_measure_type (ControlMeasureType): A ControlMeasureType of the IsmsControlMeasure
            source: (int): public_id of CmdbExtendableOption('CONTROL_MEASURE') of the IsmsControlMeasure
            implementation_state: (int): public_id of CmdbExtendableOption('IMPLEMENTATION_STATE')
                                         of the IsmsControlMeasure
            identifier (str, optional): The identifier of the IsmsControlMeasure
            chapter (str, optional): The chapter of the IsmsControlMeasure
            description (str, optional): The description of the IsmsControlMeasure
            is_applicable (bool): = If True then the IsmsControlMeasure is applicable. Defaults to False
            reason (str, optional): The reason of the IsmsControlMeasure
        Raises:
            IsmsControlMeasureInitError: If the IsmsControlMeasure could not be initialised
        """
        try:
            self.title = title
            self.control_measure_type = control_measure_type
            self.source = source
            self.implementation_state = implementation_state
            self.identifier = identifier
            self.chapter = chapter
            self.description = description
            self.is_applicable = is_applicable
            self.reason = reason

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsControlMeasureInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsControlMeasure":
        """
        Initialises a IsmsControlMeasure from a dict

        Args:
            data (dict): Data with which the IsmsControlMeasure should be initialised

        Raises:
            IsmsControlMeasureInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsControlMeasure: IsmsControlMeasure with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                title = data.get('title'),
                control_measure_type = data.get('control_measure_type'),
                source = data.get('source'),
                implementation_state = data.get('implementation_state'),
                identifier = data.get('identifier'),
                chapter = data.get('chapter'),
                description = data.get('description'),
                is_applicable = data.get('is_applicable'),
                reason = data.get('reason'),
            )
        except Exception as err:
            raise IsmsControlMeasureInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsControlMeasure") -> dict:
        """
        Converts a IsmsControlMeasure into a json compatible dict

        Args:
            instance (IsmsControlMeasure): The IsmsControlMeasure which should be converted

        Raises:
            IsmsControlMeasureToJsonError: If the IsmsControlMeasure could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsControlMeasure values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'title': instance.title,
                'control_measure_type': instance.control_measure_type,
                'source': instance.source,
                'implementation_state': instance.implementation_state,
                'identifier': instance.identifier,
                'chapter': instance.chapter,
                'description': instance.description,
                'is_applicable': instance.is_applicable,
                'reason': instance.reason,
            }
        except Exception as err:
            raise IsmsControlMeasureToJsonError(err) from err
