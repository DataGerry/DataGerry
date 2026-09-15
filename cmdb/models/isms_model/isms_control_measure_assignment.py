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

An IsmsControlMeasureAssignment links one IsmsControlMeasure to one IsmsRiskAssessment and tracks its
implementation (collection ``isms.controlMeasureAssignment``).

Its two date fields follow the same rule as the assessment's four (see IsmsRiskAssessment): they
arrive as the Mongo extended-JSON wrapper ``{'$date': <epoch millis>}`` and are stored as real BSON
dates, normalised by ``from_data`` here and by ``GenericManager`` on the raw-dict write paths. Older
databases stored the wrapper itself and are migrated by ``updater_20260907``
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.class_schema.isms_model.isms_control_measure_assignment_schema import (
    get_isms_control_measure_assignment_schema,
)

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

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('control_measure_id', CmdbDAO.DAO_ASCENDING)], 'name': 'control_measure_id', 'unique': False},
        {'keys': [('risk_assessment_id', CmdbDAO.DAO_ASCENDING)], 'name': 'risk_assessment_id', 'unique': False},
        {
            'keys': [('responsible_for_implementation_id_ref_type', CmdbDAO.DAO_ASCENDING)],
            'name': 'responsible_for_implementation_id_ref_type',
            'unique': False
        },
        {
            'keys': [('responsible_for_implementation_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'responsible_for_implementation_id',
            'unique': False
        }
    ]

    SCHEMA: dict[str, Any] = get_isms_control_measure_assignment_schema()

    # The date-typed fields every write path normalises into real BSON dates. Spelled out here rather
    # than taken from a key enum: this model's remaining literals are consolidated in its own sweep
    DATE_FIELDS: tuple[str, ...] = ('planned_implementation_date', 'finished_implementation_date')


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            control_measure_id: int,
            risk_assessment_id: int,
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
    def from_data(cls, data: dict[str, Any]) -> "IsmsControlMeasureAssignment":
        """
        Initialises a IsmsControlMeasureAssignment from a dict

        Reads a stored document as well as a validated request payload, normalising the two date
        fields in place first: a payload carries them as ``{'$date': ...}`` wrappers or timestamp
        strings, a stored document as real dates. A date that cannot be read is refused instead of
        guessed - the previous implementation parsed strings with ``fuzzy=True``, which turns a note
        like 'planned for Q3' into a date built from today

        Args:
            data (dict): Data with which the IsmsControlMeasureAssignment should be initialised

        Raises:
            IsmsControlMeasureAssignmentInitFromDataError: If the initialisation with the given data
                fails, including a date field whose value is not a readable timestamp

        Returns:
            IsmsControlMeasureAssignment: IsmsControlMeasureAssignment with the given data
        """
        try:
            unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

            if unusable_dates:
                raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

            return cls(
                public_id = data.get('public_id'),
                control_measure_id = data.get('control_measure_id'),
                risk_assessment_id = data.get('risk_assessment_id'),
                planned_implementation_date = data.get('planned_implementation_date'),
                implementation_status = data.get('implementation_status'),
                finished_implementation_date = data.get('finished_implementation_date'),
                priority = data.get('priority'),
                responsible_for_implementation_id_ref_type = data.get('responsible_for_implementation_id_ref_type'),
                responsible_for_implementation_id = data.get('responsible_for_implementation_id'),
            )
        except Exception as err:
            raise IsmsControlMeasureAssignmentInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsControlMeasureAssignment") -> dict[str, Any]:
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
