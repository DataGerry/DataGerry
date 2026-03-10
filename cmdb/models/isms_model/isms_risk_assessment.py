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
Implementation of IsmsRiskAssessment in DataGerry - ISMS
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime
from dateutil.parser import parse

from cmdb.class_schema.isms_risk_assessment_schema import get_isms_risk_assessment_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.isms_model.treatment_option_enum import TreatmentOption
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType

from cmdb.errors.models.isms_risk_assessment import (
    IsmsRiskAssessmentInitError,
    IsmsRiskAssessmentInitFromDataError,
    IsmsRiskAssessmentToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsRiskAssessment - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
#pylint: disable=R0902
class IsmsRiskAssessment(CmdbDAO):
    """
    Implementation of IsmsRiskAssessment

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskAssessment"
    MODEL = 'RiskAssessment'

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('risk_id', CmdbDAO.DAO_ASCENDING)], 'name': 'risk_id', 'unique': False},
        {'keys': [('object_id_ref_type', CmdbDAO.DAO_ASCENDING)], 'name': 'object_id_ref_type', 'unique': False},
        {'keys': [('object_id', CmdbDAO.DAO_ASCENDING)], 'name': 'object_id', 'unique': False},
        {'keys': [('interviewed_persons', CmdbDAO.DAO_ASCENDING)], 'name': 'interviewed_persons', 'unique': False},
        {
            'keys': [('responsible_persons_id_ref_type', CmdbDAO.DAO_ASCENDING)],
            'name': 'responsible_persons_id_ref_type',
            'unique': False
        },
        {
            'keys': [('responsible_persons_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'responsible_persons_id',
            'unique': False
        },
        {'keys': [('implementation_status', CmdbDAO.DAO_ASCENDING)], 'name': 'implementation_status', 'unique': False},
        {'keys': [('auditor_id_ref_type', CmdbDAO.DAO_ASCENDING)], 'name': 'auditor_id_ref_type', 'unique': False},
        {'keys': [('auditor_id', CmdbDAO.DAO_ASCENDING)], 'name': 'auditor_id', 'unique': False},
    ]

    SCHEMA: dict = get_isms_risk_assessment_schema()

    #pylint: disable=R0913, R0914, R0917
    def __init__(
            self,
            public_id: int,
            risk_id: int,
            object_id_ref_type: ObjectReferenceType,
            object_id: int,
            risk_calculation_before: dict,
            risk_assessor_id: int,
            risk_owner_id_ref_type: PersonReferenceType,
            risk_owner_id: int,
            interviewed_persons: list,
            risk_assessment_date: datetime,
            additional_info: str,
            risk_treatment_option: TreatmentOption,
            responsible_persons_id_ref_type: PersonReferenceType,
            responsible_persons_id: int,
            risk_treatment_description: str,
            planned_implementation_date: datetime,
            implementation_status: int,
            finished_implementation_date: datetime,
            required_resources: str,
            costs_for_implementation: float,
            costs_for_implementation_currency: str,
            priority: Priority,
            risk_calculation_after: dict,
            audit_done_date: datetime,
            auditor_id_ref_type: PersonReferenceType,
            auditor_id: int,
            audit_result: str
        ) -> None:
        """
        Initialises an IsmsRiskAssessment

        Args:
            public_id (int): public_id of the IsmsRiskAssessment
            risk_id (int): public_id of referenced IsmsRisk
            object_id_ref_type (ObjectReferenceType): ObjectReferenceType Enum
            object_id (int): public_id of referenced CmdbObject or CmdbObjectGroup
            risk_calculation_before (dict): sliders before treatment
            risk_assessor_id (int): public_id of CmdbPerson
            risk_owner_id_ref_type (PersonReferenceType): PersonReferenceType Enum
            risk_owner_id (int): public_id of CmdbPerson or CmdbPersonGroup
            interviewed_persons (list): Multiselect of CmdbPersons
            risk_assessment_date (datetime): Date of risk calculation before treatment
            additional_info (str): Additional information field value
            risk_treatment_option (TreatmentOption): TreatmentOption Enum
            responsible_persons_id_ref_type (PersonReferenceType): PersonReferenceType Enum
            responsible_persons_id (int): public_id of CmdbPerson or CmdbPersonGroup
            risk_treatment_description (str): Additional information text area field
            planned_implementation_date (datetime): Date of planned implementation
            implementation_status (int): public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            finished_implementation_date (datetime): Date of finished implementation
            required_resources (str): Required resources text area field
            costs_for_implementation (float): Costs for implementation
            costs_for_implementation_currency (str): Costs for implementation currency
            priority (Priority): Priority enum (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            risk_calculation_after (dict): sliders after treatment
            audit_done_date (datetime): Audit done date
            auditor_id_ref_type (PersonReferenceType): PersonReferenceType Enum
            auditor_id (int): public_id of CmdbPerson or CmdbPersonGroup
            audit_result (str): Audit result text area field

        Raises:
            IsmsRiskAssessmentInitError: When the IsmsRiskAssessment could not be initialised
        """
        try:
            self.risk_id = risk_id
            self.object_id_ref_type = object_id_ref_type
            self.object_id = object_id
            self.risk_calculation_before = risk_calculation_before
            self.risk_assessor_id = risk_assessor_id
            self.risk_owner_id_ref_type = risk_owner_id_ref_type
            self.risk_owner_id = risk_owner_id
            self.interviewed_persons = interviewed_persons
            self.risk_assessment_date = risk_assessment_date
            self.additional_info = additional_info
            self.risk_treatment_option = risk_treatment_option
            self.responsible_persons_id_ref_type = responsible_persons_id_ref_type
            self.responsible_persons_id = responsible_persons_id
            self.risk_treatment_description = risk_treatment_description
            self.planned_implementation_date = planned_implementation_date
            self.implementation_status = implementation_status
            self.finished_implementation_date = finished_implementation_date
            self.required_resources = required_resources
            self.costs_for_implementation = costs_for_implementation
            self.costs_for_implementation_currency = costs_for_implementation_currency
            self.priority = priority
            self.risk_calculation_after = risk_calculation_after
            self.audit_done_date = audit_done_date
            self.auditor_id_ref_type = auditor_id_ref_type
            self.auditor_id = auditor_id
            self.audit_result = audit_result

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskAssessmentInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsRiskAssessment":
        """
        Initialises a IsmsRiskAssessment from a dict

        Args:
            data (dict): Data with which the IsmsRiskAssessment should be initialised

        Raises:
            IsmsRiskAssessmentInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsRiskAssessment: IsmsRiskAssessment with the given data
        """
        try:
            risk_assessment_date = data.get('risk_assessment_date', None)
            planned_implementation_date = data.get('planned_implementation_date', None)
            finished_implementation_date = data.get('finished_implementation_date', None)
            audit_done_date = data.get('audit_done_date', None)

            if isinstance(risk_assessment_date, str):
                risk_assessment_date = parse(risk_assessment_date, fuzzy=True)

            if isinstance(planned_implementation_date, str):
                planned_implementation_date = parse(planned_implementation_date, fuzzy=True)

            if isinstance(finished_implementation_date, str):
                finished_implementation_date = parse(finished_implementation_date, fuzzy=True)

            if isinstance(audit_done_date, str):
                audit_done_date = parse(audit_done_date, fuzzy=True)

            return cls(
                public_id = data.get('public_id'),
                risk_id = data.get('risk_id'),
                object_id_ref_type = data.get('object_id_ref_type'),
                object_id = data.get('object_id'),
                risk_calculation_before = data.get('risk_calculation_before'),
                risk_assessor_id = data.get('risk_assessor_id'),
                risk_owner_id_ref_type = data.get('risk_owner_id_ref_type'),
                risk_owner_id = data.get('risk_owner_id'),
                interviewed_persons = data.get('interviewed_persons'),
                risk_assessment_date = risk_assessment_date,
                additional_info = data.get('additional_info'),
                risk_treatment_option = data.get('risk_treatment_option'),
                responsible_persons_id_ref_type = data.get('responsible_persons_id_ref_type'),
                responsible_persons_id = data.get('responsible_persons_id'),
                risk_treatment_description = data.get('risk_treatment_description'),
                planned_implementation_date = planned_implementation_date,
                implementation_status = data.get('implementation_status'),
                finished_implementation_date = finished_implementation_date,
                required_resources = data.get('required_resources'),
                costs_for_implementation = data.get('costs_for_implementation'),
                costs_for_implementation_currency = data.get('costs_for_implementation_currency'),
                priority = data.get('priority'),
                risk_calculation_after = data.get('risk_calculation_after'),
                audit_done_date = audit_done_date,
                auditor_id_ref_type = data.get('auditor_id_ref_type'),
                auditor_id = data.get('auditor_id'),
                audit_result = data.get('audit_result'),
            )
        except Exception as err:
            raise IsmsRiskAssessmentInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsRiskAssessment") -> dict:
        """
        Converts a IsmsRiskAssessment into a json compatible dict

        Args:
            instance (IsmsRiskAssessment): The IsmsRiskAssessment which should be converted

        Raises:
            IsmsRiskAssessmentToJsonError: If the IsmsRiskAssessment could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsRiskAssessment values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'risk_id': instance.risk_id,
                'object_id_ref_type': instance.object_id_ref_type,
                'object_id': instance.object_id,
                'risk_calculation_before': instance.risk_calculation_before,
                'risk_assessor_id': instance.risk_assessor_id,
                'risk_owner_id_ref_type': instance.risk_owner_id_ref_type,
                'risk_owner_id': instance.risk_owner_id,
                'interviewed_persons': instance.interviewed_persons,
                'risk_assessment_date': instance.risk_assessment_date,
                'additional_info': instance.additional_info,
                'risk_treatment_option': instance.risk_treatment_option,
                'responsible_persons_id_ref_type': instance.responsible_persons_id_ref_type,
                'responsible_persons_id': instance.responsible_persons_id,
                'risk_treatment_description': instance.risk_treatment_description,
                'planned_implementation_date': instance.planned_implementation_date,
                'implementation_status': instance.implementation_status,
                'finished_implementation_date': instance.finished_implementation_date,
                'required_resources': instance.required_resources,
                'costs_for_implementation': instance.costs_for_implementation,
                'costs_for_implementation_currency': instance.costs_for_implementation_currency,
                'priority': instance.priority,
                'risk_calculation_after': instance.risk_calculation_after,
                'audit_done_date': instance.audit_done_date,
                'auditor_id_ref_type': instance.auditor_id_ref_type,
                'auditor_id': instance.auditor_id,
                'audit_result': instance.audit_result,
            }
        except Exception as err:
            raise IsmsRiskAssessmentToJsonError(err) from err
