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
dates, normalised by ``normalize_document`` here and by ``GenericManager`` on the raw-dict write paths.
Older databases stored the wrapper itself and are migrated by ``updater_20260907``.

The model reads and writes through the shared ``CmdbDAO.from_data`` / ``to_json``: ``KEYS`` is its key
enum, and ``REQUIRED_INIT_KEYS`` refuses a document without the measure and assessment ids it links
"""
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_control_measure_assignment_constants import (
    CONTROL_MEASURE_ASSIGNMENT_DATE_FIELDS,
    CONTROL_MEASURE_ASSIGNMENT_REQUIRED_DOCUMENT_KEYS,
    ControlMeasureAssignmentKey,
)
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
        {
            'keys': [(key.value, CmdbDAO.DAO_ASCENDING)],
            'name': key.value,
            'unique': False,
        }
        for key in (
            ControlMeasureAssignmentKey.CONTROL_MEASURE_ID,
            ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID,
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE,
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID,
        )
    ]

    SCHEMA: dict[str, Any] = get_isms_control_measure_assignment_schema()

    DATE_FIELDS: tuple[str, ...] = CONTROL_MEASURE_ASSIGNMENT_DATE_FIELDS

    # The shared from_data / to_json; REQUIRED_INIT_KEYS refuses a document that links nothing
    KEYS = ControlMeasureAssignmentKey
    REQUIRED_INIT_KEYS: list[str] = CONTROL_MEASURE_ASSIGNMENT_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsControlMeasureAssignmentInitFromDataError
    TO_JSON_ERROR = IsmsControlMeasureAssignmentToJsonError


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
    def normalize_document(cls, data: dict[str, Any]) -> None:
        """
        Normalises the two date fields of a raw document IN PLACE before the shared from_data reads it

        A payload carries them as ``{'$date': ...}`` wrappers or timestamp strings, a stored document as
        real dates. A date that cannot be read is refused instead of guessed: a fuzzy parse would turn a
        note like 'planned for Q3' into a date built from today

        Args:
            data (dict[str, Any]): The document or validated payload, edited in place

        Raises:
            ValueError: If a present date field is not a readable timestamp; the shared from_data
                reports it as IsmsControlMeasureAssignmentInitFromDataError
        """
        unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")
