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

An IsmsRiskAssessment evaluates one IsmsRisk for one CmdbObject or CmdbObjectGroup, before and after
treatment (collection ``isms.riskAssessment``). Three properties of this document are invariants the
rest of the ISMS relies on:

**Its four date fields are real BSON dates.** They arrive as the Mongo extended-JSON wrapper
``{'$date': <epoch millis>}`` - the shape every DataGerry response uses for a datetime and therefore
the shape the frontend sends back - and are normalised into ``datetime`` objects on the way in, by
``from_data`` here and by ``GenericManager`` on the raw-dict write paths. Storing the wrapper itself
(as this model did until 2026-09-07, migrated by ``updater_20260907``) leaves a sub-document where a
date belongs, which MongoDB cannot sort, range-filter or ``$dateToString`` - the reports could only
ever project such a value, never query it. The wire format is unchanged either way, because
``cmdb.database.json_codec.default`` serialises a datetime back into the same wrapper.

**Its key set is closed.** ``RiskAssessmentKey`` names every persisted key, and ``from_data`` /
``to_json`` are a lossless round-trip over exactly that set - which the read routes depend on, since
they answer with ``to_json(from_data(document))``. A key stored outside the set would therefore be
invisible in every response while still occupying the document, so no write path may persist one:
``control_measure_assignments`` travels in the same payload but belongs to its own collection and is
popped by each write route before the assessment is stored.

**Its enum-typed fields hold the enum's raw value, not a member.** The values are pinned by the
Cerberus schema (``allowed`` lists built from the enums), so validation - not the model - is what
refuses an unknown reference type, treatment option or priority. The attributes are annotated as the
primitives they actually hold; the docstrings name the enum that defines the allowed values
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime

from cmdb.utils import coerce_document_dates

from cmdb.class_schema.isms_model.isms_risk_assessment_schema import get_isms_risk_assessment_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_assessment_constants import (
    RISK_ASSESSMENT_DATE_KEYS,
    RiskAssessmentKey,
)

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

    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(RiskAssessmentKey.RISK_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.OBJECT_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.OBJECT_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.OBJECT_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.INTERVIEWED_PERSONS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.INTERVIEWED_PERSONS.value,
            'unique': False
        },
        # Both person-reference halves of the assessor / owner pair are indexed like the responsible
        # and auditor pairs below: deleting one CmdbPerson runs a filtered update over every one of
        # them (see PersonsManager.remove_person_from_risk_assessments), and the two that were missing
        # turned that cascade into a collection scan
        {
            'keys': [(RiskAssessmentKey.RISK_ASSESSOR_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RISK_OWNER_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RISK_OWNER_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.IMPLEMENTATION_STATUS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value,
            'unique': False
        },
        {
            'keys': [(RiskAssessmentKey.AUDITOR_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskAssessmentKey.AUDITOR_ID.value,
            'unique': False
        },
    ]

    SCHEMA: dict = get_isms_risk_assessment_schema()

    # The date-typed fields every write path normalises into real BSON dates
    DATE_FIELDS: tuple[str, ...] = tuple(date_key.value for date_key in RISK_ASSESSMENT_DATE_KEYS)


    #pylint: disable=R0913, R0914
    def __init__(
            self,
            *,
            public_id: int,
            risk_id: int,
            object_id_ref_type: str,
            object_id: int,
            risk_calculation_before: dict[str, Any],
            risk_assessor_id: int | None,
            risk_owner_id_ref_type: str,
            risk_owner_id: int | None,
            interviewed_persons: list[int] | None,
            risk_assessment_date: datetime | None,
            additional_info: str | None,
            risk_treatment_option: str | None,
            responsible_persons_id_ref_type: str,
            responsible_persons_id: int | None,
            risk_treatment_description: str | None,
            planned_implementation_date: datetime | None,
            implementation_status: int | None,
            finished_implementation_date: datetime | None,
            required_resources: str | None,
            costs_for_implementation: float | None,
            costs_for_implementation_currency: str | None,
            priority: int | None,
            risk_calculation_after: dict[str, Any],
            audit_done_date: datetime | None,
            auditor_id_ref_type: str,
            auditor_id: int | None,
            audit_result: str | None
        ) -> None:
        """
        Initialises an IsmsRiskAssessment

        Keyword-only by design: CmdbDAO validates its required init keys in ``__new__``, reading them
        from the keyword arguments, so a positional call could never have constructed this class

        Args:
            public_id (int): public_id of the IsmsRiskAssessment
            risk_id (int): public_id of referenced IsmsRisk
            object_id_ref_type (str): Which collection 'object_id' points at, an ObjectReferenceType value
            object_id (int): public_id of referenced CmdbObject or CmdbObjectGroup
            risk_calculation_before (dict): sliders before treatment
            risk_assessor_id (int | None): public_id of CmdbPerson
            risk_owner_id_ref_type (str): Which collection 'risk_owner_id' points at, a
                PersonReferenceType value
            risk_owner_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            interviewed_persons (list | None): Multiselect of CmdbPersons
            risk_assessment_date (datetime | None): Date of risk calculation before treatment
            additional_info (str | None): Additional information field value
            risk_treatment_option (str | None): A TreatmentOption value
            responsible_persons_id_ref_type (str): Which collection 'responsible_persons_id' points at,
                a PersonReferenceType value
            responsible_persons_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            risk_treatment_description (str | None): Additional information text area field
            planned_implementation_date (datetime | None): Date of planned implementation
            implementation_status (int | None): public_id of CmdbExtendableOption 'IMPLEMENTATION_STATE'
            finished_implementation_date (datetime | None): Date of finished implementation
            required_resources (str | None): Required resources text area field
            costs_for_implementation (float | None): Costs for implementation
            costs_for_implementation_currency (str | None): Costs for implementation currency
            priority (int | None): A Priority value (1 = Low, 2 = Medium, 3 = High, 4 = Very high)
            risk_calculation_after (dict): sliders after treatment
            audit_done_date (datetime | None): Audit done date
            auditor_id_ref_type (str): Which collection 'auditor_id' points at, a PersonReferenceType value
            auditor_id (int | None): public_id of CmdbPerson or CmdbPersonGroup
            audit_result (str | None): Audit result text area field

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
    def from_data(cls, data: dict[str, Any]) -> "IsmsRiskAssessment":
        """
        Initialises a IsmsRiskAssessment from a dict

        Reads a document coming out of MongoDB as well as a validated request payload, so the four
        date fields are normalised first: a payload carries them as ``{'$date': ...}`` wrappers or
        timestamp strings, a stored document as real dates. A date that cannot be read is refused
        instead of guessed - the previous implementation parsed strings with ``fuzzy=True``, which
        turns 'implementation planned for Q3' into a date built from today

        Args:
            data (dict): Data with which the IsmsRiskAssessment should be initialised

        Raises:
            IsmsRiskAssessmentInitFromDataError: If the initialisation with the given data fails,
                including a date field whose value is not a readable timestamp

        Returns:
            IsmsRiskAssessment: IsmsRiskAssessment with the given data
        """
        try:
            unusable_dates: list[str] = coerce_document_dates(data, cls.DATE_FIELDS)

            if unusable_dates:
                raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

            return cls(
                public_id = data.get(RiskAssessmentKey.PUBLIC_ID.value),
                risk_id = data.get(RiskAssessmentKey.RISK_ID.value),
                object_id_ref_type = data.get(RiskAssessmentKey.OBJECT_ID_REF_TYPE.value),
                object_id = data.get(RiskAssessmentKey.OBJECT_ID.value),
                risk_calculation_before = data.get(RiskAssessmentKey.RISK_CALCULATION_BEFORE.value),
                risk_assessor_id = data.get(RiskAssessmentKey.RISK_ASSESSOR_ID.value),
                risk_owner_id_ref_type = data.get(RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value),
                risk_owner_id = data.get(RiskAssessmentKey.RISK_OWNER_ID.value),
                interviewed_persons = data.get(RiskAssessmentKey.INTERVIEWED_PERSONS.value),
                risk_assessment_date = data.get(RiskAssessmentKey.RISK_ASSESSMENT_DATE.value),
                additional_info = data.get(RiskAssessmentKey.ADDITIONAL_INFO.value),
                risk_treatment_option = data.get(RiskAssessmentKey.RISK_TREATMENT_OPTION.value),
                responsible_persons_id_ref_type = data.get(
                                                    RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value
                                                  ),
                responsible_persons_id = data.get(RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value),
                risk_treatment_description = data.get(RiskAssessmentKey.RISK_TREATMENT_DESCRIPTION.value),
                planned_implementation_date = data.get(RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value),
                implementation_status = data.get(RiskAssessmentKey.IMPLEMENTATION_STATUS.value),
                finished_implementation_date = data.get(RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value),
                required_resources = data.get(RiskAssessmentKey.REQUIRED_RESOURCES.value),
                costs_for_implementation = data.get(RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value),
                costs_for_implementation_currency = data.get(
                                                        RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION_CURRENCY.value
                                                    ),
                priority = data.get(RiskAssessmentKey.PRIORITY.value),
                risk_calculation_after = data.get(RiskAssessmentKey.RISK_CALCULATION_AFTER.value),
                audit_done_date = data.get(RiskAssessmentKey.AUDIT_DONE_DATE.value),
                auditor_id_ref_type = data.get(RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value),
                auditor_id = data.get(RiskAssessmentKey.AUDITOR_ID.value),
                audit_result = data.get(RiskAssessmentKey.AUDIT_RESULT.value),
            )
        except Exception as err:
            raise IsmsRiskAssessmentInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsRiskAssessment") -> dict[str, Any]:
        """
        Converts a IsmsRiskAssessment into a storable, serialisable dict

        Emits exactly the keys of ``RiskAssessmentKey``, which makes it the inverse of ``from_data``
        over the closed key set. The date values stay ``datetime`` objects: that is what MongoDB
        stores, and the response encoder (``cmdb.database.json_codec.default``) turns them into
        the ``{'$date': <epoch millis>}`` wrapper the frontend expects

        Args:
            instance (IsmsRiskAssessment): The IsmsRiskAssessment which should be converted

        Raises:
            IsmsRiskAssessmentToJsonError: If the IsmsRiskAssessment could not be converted

        Returns:
            dict: Dict of the IsmsRiskAssessment values, keyed by RiskAssessmentKey
        """
        try:
            return {
                RiskAssessmentKey.PUBLIC_ID.value: instance.get_public_id(),
                RiskAssessmentKey.RISK_ID.value: instance.risk_id,
                RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: instance.object_id_ref_type,
                RiskAssessmentKey.OBJECT_ID.value: instance.object_id,
                RiskAssessmentKey.RISK_CALCULATION_BEFORE.value: instance.risk_calculation_before,
                RiskAssessmentKey.RISK_ASSESSOR_ID.value: instance.risk_assessor_id,
                RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value: instance.risk_owner_id_ref_type,
                RiskAssessmentKey.RISK_OWNER_ID.value: instance.risk_owner_id,
                RiskAssessmentKey.INTERVIEWED_PERSONS.value: instance.interviewed_persons,
                RiskAssessmentKey.RISK_ASSESSMENT_DATE.value: instance.risk_assessment_date,
                RiskAssessmentKey.ADDITIONAL_INFO.value: instance.additional_info,
                RiskAssessmentKey.RISK_TREATMENT_OPTION.value: instance.risk_treatment_option,
                RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value: instance.responsible_persons_id_ref_type,
                RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value: instance.responsible_persons_id,
                RiskAssessmentKey.RISK_TREATMENT_DESCRIPTION.value: instance.risk_treatment_description,
                RiskAssessmentKey.PLANNED_IMPLEMENTATION_DATE.value: instance.planned_implementation_date,
                RiskAssessmentKey.IMPLEMENTATION_STATUS.value: instance.implementation_status,
                RiskAssessmentKey.FINISHED_IMPLEMENTATION_DATE.value: instance.finished_implementation_date,
                RiskAssessmentKey.REQUIRED_RESOURCES.value: instance.required_resources,
                RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION.value: instance.costs_for_implementation,
                RiskAssessmentKey.COSTS_FOR_IMPLEMENTATION_CURRENCY.value:
                    instance.costs_for_implementation_currency,
                RiskAssessmentKey.PRIORITY.value: instance.priority,
                RiskAssessmentKey.RISK_CALCULATION_AFTER.value: instance.risk_calculation_after,
                RiskAssessmentKey.AUDIT_DONE_DATE.value: instance.audit_done_date,
                RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value: instance.auditor_id_ref_type,
                RiskAssessmentKey.AUDITOR_ID.value: instance.auditor_id,
                RiskAssessmentKey.AUDIT_RESULT.value: instance.audit_result,
            }
        except Exception as err:
            raise IsmsRiskAssessmentToJsonError(err) from err
