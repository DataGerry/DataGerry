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
Implementation of IsmsControlMeasureAssignment in DataGerry - ISMS
"""
from logging import Logger, getLogger
from datetime import datetime
from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.errors.models.isms_control_measure_assignment import (
    IsmsControlMeasureAssignmentInitError,
    IsmsControlMeasureAssignmentInitFromDataError,
    IsmsControlMeasureAssignmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                         IsmsControlMeasureAssignment - CLASS                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsControlMeasureAssignment(CmdbDAO):
    """
    Implementation of IsmsControlMeasureAssignment

    Extends: CmdbDAO
    """
    COLLECTION = "isms.controlMeasureAssignment"
    MODEL = 'ControlMeasureAssignment'

    SCHEMA: dict = {
        'public_id': { # public_id of the IsmsControlMeasureAssignment
            'type': 'integer',
            'min': 1,
        },
        'control_measure_id': { # public_id of IsmsControlMeasure
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'risk_assessment_id': { # public_id of IsmsRiskAssessment
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'planned_implementation_date': { # Date of planned implementation
            'type': 'dict',
            'required': True,
            'nullable': True,
        },
        'implementation_status': { # public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            'type': 'integer',
            'required': True,
            'empty': False,
        },
        'finished_implementation_date': { # Date of finished implementation
            'type': 'dict',
            'required': True,
            'nullable': True,
        },
        'priority': { # Priority enum (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            'type': 'integer',
            'required': True,
            'nullable': True,
        },
        'responsible_for_implementation_id_ref_type': { # PersonReferenceType Enum
            'type': 'string',
            'required': True,
            'nullable': True,
        },
        'responsible_for_implementation_id': { # public_id of CmdbPerson or CmdbPersonGroup
            'type': 'integer',
            'min': 1,
            'required': True,
            'nullable': True,
        },
    }


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            control_measure_id: int,
            risk_assessment_id:int,
            planned_implementation_date: datetime,
            implementation_status: int,
            finished_implementation_date: datetime,
            priority: Priority,
            responsible_for_implementation_id_ref_type: PersonReferenceType,
            responsible_for_implementation_id: int):
        """
        Initialises an IsmsControlMeasureAssignment

        Args:
            public_id (int): public_id of the IsmsControlMeasureAssignment
            control_measure_id (int): public_id of IsmsControlMeasure
            risk_assessment_id (int): public_id of IsmsRiskAssessment
            planned_implementation_date (datetime): # Date of planned implementation
            implementation_status (int): public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            finished_implementation_date (datetime): Date of finished implementation
            priority (Priority): Priority enum (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            responsible_for_implementation_id_ref_type (PersonReferenceType): # PersonReferenceType Enum
            responsible_for_implementation_id (int): # public_id of CmdbPerson or CmdbPersonGroup

        Raises:
            IsmsControlMeasureAssignmentInitError: When the IsmsControlMeasureAssignment could not be initialised
        """
        try:
            self.control_measure_id = control_measure_id
            self.risk_assessment_id = risk_assessment_id
            self.planned_implementation_date = planned_implementation_date
            self.implementation_status = implementation_status
            self.finished_implementation_date = finished_implementation_date
            self.priority = priority
            self.responsible_for_implementation_id_ref_type = responsible_for_implementation_id_ref_type
            self.responsible_for_implementation_id = responsible_for_implementation_id

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsControlMeasureAssignmentInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsControlMeasureAssignment":
        """
        Initialises a IsmsControlMeasureAssignment from a dict

        Args:
            data (dict): Data with which the IsmsControlMeasureAssignment should be initialised

        Raises:
            IsmsControlMeasureAssignmentInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsControlMeasureAssignment: IsmsControlMeasureAssignment with the given data
        """
        try:
            planned_implementation_date = data.get('planned_implementation_date', None)
            finished_implementation_date = data.get('finished_implementation_date', None)

            if isinstance(planned_implementation_date, str):
                planned_implementation_date = parse(planned_implementation_date, fuzzy=True)

            if isinstance(finished_implementation_date, str):
                finished_implementation_date = parse(finished_implementation_date, fuzzy=True)

            return cls(
                public_id = data.get('public_id'),
                control_measure_id = data.get('control_measure_id'),
                risk_assessment_id = data.get('risk_assessment_id'),
                planned_implementation_date = planned_implementation_date,
                implementation_status = data.get('implementation_status'),
                finished_implementation_date = finished_implementation_date,
                priority = data.get('priority'),
                responsible_for_implementation_id_ref_type = data.get('responsible_for_implementation_id_ref_type'),
                responsible_for_implementation_id = data.get('responsible_for_implementation_id'),
            )
        except Exception as err:
            raise IsmsControlMeasureAssignmentInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsControlMeasureAssignment") -> dict:
        """
        Converts a IsmsControlMeasureAssignment into a json compatible dict

        Args:
            instance (IsmsControlMeasureAssignment): The IsmsControlMeasureAssignment which should be converted

        Raises:
            IsmsControlMeasureAssignmentToJsonError: If the IsmsControlMeasureAssignment could not be converted
                                                      to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsControlMeasureAssignment values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'control_measure_id': instance.control_measure_id,
                'risk_assessment_id': instance.risk_assessment_id,
                'planned_implementation_date': instance.planned_implementation_date,
                'implementation_status': instance.implementation_status,
                'finished_implementation_date': instance.finished_implementation_date,
                'priority': instance.priority,
                'responsible_for_implementation_id_ref_type': instance.responsible_for_implementation_id_ref_type,
                'responsible_for_implementation_id': instance.responsible_for_implementation_id,
            }
        except Exception as err:
            raise IsmsControlMeasureAssignmentToJsonError(err) from err
